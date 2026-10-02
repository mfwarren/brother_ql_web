use crate::{
    bulk,
    config::Config,
    fonts::{self, Fonts},
    media, printer, remote_images, rendering, storage, validation,
};
use anyhow::{Result, ensure};
use axum::{
    Router,
    extract::{DefaultBodyLimit, Multipart, Path, Query, State},
    http::{StatusCode, header},
    response::{IntoResponse, Redirect, Response},
    routing::{get, post, put},
};
use serde_json::{Value, json};
use std::{
    collections::HashMap,
    io::Cursor,
    sync::{Arc, RwLock},
};
pub struct Json<T>(pub T);
impl<S, T> axum::extract::FromRequest<S> for Json<T>
where
    S: Send + Sync,
    T: serde::de::DeserializeOwned,
{
    type Rejection = ApiError;
    async fn from_request(req: axum::extract::Request, state: &S) -> ApiResult<Self> {
        axum::Json::<T>::from_request(req, state)
            .await
            .map(|v| Self(v.0))
            .map_err(|e| {
                ApiError(
                    if e.status() == StatusCode::PAYLOAD_TOO_LARGE {
                        e.status()
                    } else {
                        StatusCode::BAD_REQUEST
                    },
                    e.body_text(),
                )
            })
    }
}
impl<T: serde::Serialize> IntoResponse for Json<T> {
    fn into_response(self) -> Response {
        axum::Json(self.0).into_response()
    }
}
#[derive(Clone)]
pub struct AppState {
    pub config: Arc<Config>,
    pub fonts: Arc<RwLock<Fonts>>,
}
#[derive(Debug)]
pub struct ApiError(pub StatusCode, pub String);
impl From<anyhow::Error> for ApiError {
    fn from(e: anyhow::Error) -> Self {
        Self(
            e.downcast_ref::<printer::PrintError>()
                .and_then(|p| StatusCode::from_u16(p.status).ok())
                .unwrap_or(StatusCode::BAD_REQUEST),
            e.to_string(),
        )
    }
}
impl IntoResponse for ApiError {
    fn into_response(self) -> Response {
        (self.0, Json(json!({"message":self.1}))).into_response()
    }
}
type ApiResult<T> = std::result::Result<T, ApiError>;
pub(crate) async fn blocking<T: Send + 'static>(
    f: impl FnOnce() -> Result<T> + Send + 'static,
) -> ApiResult<T> {
    static WORKERS: std::sync::LazyLock<Arc<tokio::sync::Semaphore>> =
        std::sync::LazyLock::new(|| Arc::new(tokio::sync::Semaphore::new(2)));
    let permit = WORKERS
        .clone()
        .acquire_owned()
        .await
        .map_err(|e| ApiError(StatusCode::SERVICE_UNAVAILABLE, e.to_string()))?;
    tokio::task::spawn_blocking(move || {
        let _permit = permit;
        f()
    })
    .await
    .map_err(|e| ApiError(StatusCode::INTERNAL_SERVER_ERROR, e.to_string()))?
    .map_err(Into::into)
}
fn registry(s: &AppState) -> Result<Fonts> {
    s.fonts
        .read()
        .map(|r| r.clone())
        .map_err(|_| anyhow::anyhow!("Font registry unavailable"))
}
fn defaults(s: &AppState, f: &Fonts) -> Result<Value> {
    let mut d = s.config.defaults.clone();
    let p = s.config.data_dir.join("settings.json");
    if p.exists() {
        let saved: Value = serde_json::from_slice(&std::fs::read(p)?)?;
        if let Some(m) = saved["defaults"].as_object() {
            for (k, v) in m {
                d[k] = v.clone();
            }
        }
    }
    let name = f.canonical(d["font"].as_str().unwrap_or(""));
    d["font"] = if f.get(&name).is_ok() {
        name
    } else {
        f.default_font()
    }
    .into();
    Ok(d)
}
pub fn router(config: Config) -> Result<Router> {
    let fonts = Fonts::load(&config)?;
    let assets = config.static_dir.join("assets");
    let static_dir = config.static_dir.clone();
    let s = AppState {
        config: Arc::new(config),
        fonts: Arc::new(RwLock::new(fonts)),
    };
    let pages = Router::new()
        .route("/", get(|| async { Redirect::to("/studio/") }))
        .route(
            "/labeldesigner/",
            get(|| async { Redirect::to("/studio/") }),
        )
        .route("/studio", get(|| async { Redirect::to("/studio/") }))
        .route("/studio/", get(index))
        .nest_service(
            "/studio/assets",
            tower_http::services::ServeDir::new(assets),
        )
        .nest_service(
            "/static/studio",
            tower_http::services::ServeDir::new(static_dir),
        );
    let endpoints = Router::new()
        .route("/studio/api/config", get(config_get))
        .route("/studio/api/status", get(status))
        .route("/studio/api/preview", post(preview))
        .route("/studio/api/print", post(print))
        .route("/studio/api/labels", get(labels).post(save))
        .route(
            "/studio/api/labels/{id}",
            get(load).put(update).delete(delete),
        )
        .route("/studio/api/settings", put(settings))
        .route("/studio/api/bulk/prepare", post(prepare))
        .route("/studio/api/bulk/print", post(print_bulk))
        .route("/studio/api/bulk/image", post(remote_image))
        .route("/studio/api/fonts/catalog", get(font_catalog))
        .route("/studio/api/fonts/file", get(font_file))
        .route("/studio/api/fonts/install", post(install_font))
        .route("/studio/api/fonts/upload", post(upload_font))
        .route(
            "/labeldesigner/api/webhook/print",
            post(crate::webhook::print),
        )
        .layer(DefaultBodyLimit::max(8 * 1024 * 1024 + 65536))
        .layer(tower_http::timeout::RequestBodyTimeoutLayer::new(
            std::time::Duration::from_secs(30),
        ))
        .route_layer(axum::middleware::from_fn_with_state(
            Arc::new(tokio::sync::Semaphore::new(4)),
            admit_request,
        ));
    Ok(pages.merge(endpoints).with_state(s))
}
async fn admit_request(
    State(slots): State<Arc<tokio::sync::Semaphore>>,
    request: axum::extract::Request,
    next: axum::middleware::Next,
) -> Response {
    let Ok(_permit) = slots.try_acquire_owned() else {
        return (
            StatusCode::SERVICE_UNAVAILABLE,
            [(header::RETRY_AFTER, "1")],
            Json(json!({"success":false,"message":"Server busy. Please try again shortly."})),
        )
            .into_response();
    };
    next.run(request).await
}
async fn index(State(s): State<AppState>) -> ApiResult<Response> {
    let bytes = tokio::fs::read(s.config.static_dir.join("index.html"))
        .await
        .map_err(|e| {
            ApiError(
                StatusCode::SERVICE_UNAVAILABLE,
                format!("Build the frontend first: {e}"),
            )
        })?;
    Ok(([(header::CONTENT_TYPE, "text/html")], bytes).into_response())
}
async fn config_get(State(s): State<AppState>) -> ApiResult<Json<Value>> {
    blocking(move || {
        let fonts = registry(&s)?;
        let defaults = defaults(&s, &fonts)?;
        let mode = if s.config.printer == "simulation" {
            "simulation"
        } else {
            "physical"
        };
        Ok(Json(json!({
            "model": s.config.model,
            "fonts": fonts.list(),
            "sizes": media::sizes(&s.config.model),
            "defaultFont": defaults["font"],
            "defaultSize": defaults["sizeId"],
            "defaults": defaults,
            "mode": mode,
        })))
    })
    .await
}
async fn status(State(s): State<AppState>) -> ApiResult<Json<Value>> {
    blocking(move || printer::status(&s.config).map(Json)).await
}
async fn preview(State(s): State<AppState>, Json(v): Json<Value>) -> ApiResult<Response> {
    let png = blocking(move || {
        let f = registry(&s)?;
        let d = validation::draft(&v, &s.config, &f, false)?;
        let img = rendering::render(&d, &f, true)?;
        let mut out = Cursor::new(Vec::new());
        img.write_to(&mut out, image::ImageFormat::Png)?;
        Ok(out.into_inner())
    })
    .await?;
    Ok((
        [
            (header::CONTENT_TYPE, "image/png"),
            (header::CACHE_CONTROL, "no-store"),
        ],
        png,
    )
        .into_response())
}
async fn print(State(s): State<AppState>, Json(v): Json<Value>) -> ApiResult<Json<Value>> {
    blocking(move || {
        let f = registry(&s)?;
        let d = validation::draft(&v["draft"], &s.config, &f, false)?;
        let copies = validation::integer(&v["copies"], "Copies", 1, 100)?;
        let cut = cut(&v)?;
        printer::print_copies(
            &s.config,
            &f,
            &d,
            copies as usize,
            cut,
            v["confirmRedMedia"] == true,
        )
        .map(Json)
    })
    .await
}
fn cut(v: &Value) -> Result<&str> {
    let cut = v["cut"].as_str().unwrap_or("each");
    ensure!(["each", "end"].contains(&cut), "Invalid cut option.");
    Ok(cut)
}
async fn labels(State(s): State<AppState>) -> ApiResult<Json<Value>> {
    blocking(move || storage::list(&s.config, &registry(&s)?).map(Json)).await
}
fn record(s: &AppState, v: &Value, id: &str) -> Result<Value> {
    let f = registry(s)?;
    let name = validation::string(&v["name"], "name", 100, false)?.trim();
    let d = validation::draft(&v["draft"], &s.config, &f, false)?;
    rendering::render(&d, &f, true)?;
    let rec = json!({"version":1,"id":id,"name":name,"updatedAt":chrono::Utc::now().to_rfc3339(),"draft":d});
    storage::write_json(&storage::path(&s.config, id)?, &rec)?;
    storage::saved(rec, &f)
}
async fn save(State(s): State<AppState>, Json(v): Json<Value>) -> ApiResult<Response> {
    let rec = blocking(move || record(&s, &v, &uuid::Uuid::new_v4().to_string())).await?;
    Ok((StatusCode::CREATED, Json(rec)).into_response())
}
async fn load(State(s): State<AppState>, Path(id): Path<String>) -> ApiResult<Json<Value>> {
    let path = storage::path(&s.config, &id)?;
    if !path.exists() {
        return Err(ApiError(StatusCode::NOT_FOUND, "Label not found".into()));
    }
    blocking(move || {
        storage::saved(
            serde_json::from_slice(&std::fs::read(path)?)?,
            &registry(&s)?,
        )
        .map(Json)
    })
    .await
}
async fn update(
    State(s): State<AppState>,
    Path(id): Path<String>,
    Json(v): Json<Value>,
) -> ApiResult<Json<Value>> {
    if !storage::path(&s.config, &id)?.exists() {
        return Err(ApiError(StatusCode::NOT_FOUND, "Label not found".into()));
    }
    blocking(move || record(&s, &v, &id).map(Json)).await
}
async fn delete(State(s): State<AppState>, Path(id): Path<String>) -> ApiResult<Json<Value>> {
    let path = storage::path(&s.config, &id)?;
    tokio::fs::remove_file(path).await.map_err(|e| {
        ApiError(
            if e.kind() == std::io::ErrorKind::NotFound {
                StatusCode::NOT_FOUND
            } else {
                StatusCode::INTERNAL_SERVER_ERROR
            },
            e.to_string(),
        )
    })?;
    Ok(Json(json!({"success":true})))
}
async fn settings(State(s): State<AppState>, Json(v): Json<Value>) -> ApiResult<Json<Value>> {
    blocking(move || {
        let fonts = registry(&s)?;
        fonts.get(validation::string(&v["font"], "font", 200, false)?)?;
        ensure!(
            media::sizes(&s.config.model)
                .as_array()
                .unwrap()
                .iter()
                .any(|size| size["id"] == v["sizeId"]),
            "Choose a supported label roll."
        );
        ensure!(
            v["orientation"] == "standard" || v["orientation"] == "rotated",
            "Choose a valid orientation."
        );
        let auto_detect = v.get("autoDetectRoll").cloned().unwrap_or(json!(true));
        ensure!(
            auto_detect.is_boolean(),
            "Automatic roll detection must be on or off."
        );
        let defaults = json!({
            "font": v["font"],
            "sizeId": v["sizeId"],
            "orientation": v["orientation"],
            "margin": validation::integer(&v["margin"], "Margin", 0, 100)?,
            "fontSize": validation::integer(&v["fontSize"], "Font size", 8, 200)?,
            "autoDetectRoll": auto_detect,
        });
        storage::write_json(
            &s.config.data_dir.join("settings.json"),
            &json!({"version": 1, "defaults": defaults}),
        )?;
        Ok(Json(json!({"defaults": defaults})))
    })
    .await
}
async fn prepare(State(s): State<AppState>, Json(v): Json<Value>) -> ApiResult<Json<Value>> {
    blocking(move || bulk::prepare(&v, &s.config, &registry(&s)?).map(Json)).await
}
async fn print_bulk(State(s): State<AppState>, Json(v): Json<Value>) -> ApiResult<Json<Value>> {
    blocking(move || {
        let f = registry(&s)?;
        let entries = v["drafts"]
            .as_array()
            .ok_or_else(|| anyhow::anyhow!("Select 1–100 labels."))?;
        ensure!((1..=100).contains(&entries.len()), "Select 1–100 labels.");
        let job = uuid::Uuid::parse_str(v["jobId"].as_str().unwrap_or(""))?.to_string();
        let drafts = entries
            .iter()
            .map(|d| validation::draft(d, &s.config, &f, false))
            .collect::<Result<Vec<_>>>()?;
        printer::print_drafts(
            &s.config,
            &f,
            &drafts.iter().collect::<Vec<_>>(),
            cut(&v)?,
            Some(&job),
            false,
        )
        .map(Json)
    })
    .await
}
async fn remote_image(Json(v): Json<Value>) -> ApiResult<Json<Value>> {
    blocking(move || {
        remote_images::fetch(validation::string(&v["url"], "image URL", 2000, false)?).map(Json)
    })
    .await
}
async fn font_catalog(State(s): State<AppState>) -> ApiResult<Json<Value>> {
    blocking(move || fonts::catalog(&s.config).map(Json)).await
}
async fn font_file(
    State(s): State<AppState>,
    Query(q): Query<HashMap<String, String>>,
) -> ApiResult<Response> {
    let f = registry(&s)?;
    let p = f
        .get(q.get("font").map(String::as_str).unwrap_or(""))?
        .path
        .clone();
    let bytes = tokio::fs::read(p).await.map_err(anyhow::Error::from)?;
    Ok(([(header::CONTENT_TYPE, "font/ttf")], bytes).into_response())
}
fn reload(s: &AppState) -> Result<()> {
    let f = Fonts::load(&s.config)?;
    *s.fonts
        .write()
        .map_err(|_| anyhow::anyhow!("Font registry unavailable"))? = f;
    Ok(())
}
async fn install_font(State(s): State<AppState>, Json(v): Json<Value>) -> ApiResult<Json<Value>> {
    blocking(move || {
        let result = fonts::install_google(
            &s.config,
            validation::string(&v["id"], "font family", 150, false)?,
        )?;
        reload(&s)?;
        Ok(Json(result))
    })
    .await
}
async fn upload_font(
    State(s): State<AppState>,
    mut multipart: Multipart,
) -> ApiResult<Json<Value>> {
    while let Some(field) = multipart.next_field().await.map_err(anyhow::Error::from)? {
        if field.name() != Some("font") {
            continue;
        }
        let name = field.file_name().unwrap_or("").to_lowercase();
        if !name.ends_with(".ttf") && !name.ends_with(".otf") {
            return Err(ApiError(
                StatusCode::BAD_REQUEST,
                "Choose a TTF or OTF font.".into(),
            ));
        }
        let bytes = field.bytes().await.map_err(anyhow::Error::from)?;
        return blocking(move || {
            let result = fonts::upload(&s.config, &bytes)?;
            reload(&s)?;
            Ok(Json(result))
        })
        .await;
    }
    Err(ApiError(
        StatusCode::BAD_REQUEST,
        "Choose a TTF or OTF font.".into(),
    ))
}
