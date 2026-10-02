use crate::{api::AppState, media, printer};
use anyhow::{Result, ensure};
use axum::{
    Json,
    extract::{FromRequest, Multipart, Request, State},
    http::StatusCode,
    response::{IntoResponse, Response},
};
use base64::{Engine, engine::general_purpose::STANDARD};
use serde_json::{Value, json};
use subtle::ConstantTimeEq;

fn failure(status: StatusCode, message: impl ToString) -> Response {
    (
        status,
        Json(json!({"success":false,"message":message.to_string()})),
    )
        .into_response()
}
pub async fn print(State(s): State<AppState>, request: Request) -> Response {
    if s.config.webhook_password.is_empty() {
        return failure(StatusCode::FORBIDDEN, "Webhook is not enabled");
    }
    let auth = request
        .headers()
        .get("authorization")
        .and_then(|v| v.to_str().ok())
        .unwrap_or("")
        .trim_start_matches("Bearer ")
        .trim()
        .to_owned();
    let query: std::collections::HashMap<String, String> =
        url::form_urlencoded::parse(request.uri().query().unwrap_or("").as_bytes())
            .into_owned()
            .collect();
    let is_multipart = request
        .headers()
        .get("content-type")
        .and_then(|v| v.to_str().ok())
        .is_some_and(|v| v.starts_with("multipart/form-data"));
    let mut params = json!({});
    let mut images = Vec::new();
    if is_multipart {
        let mut multipart = match Multipart::from_request(request, &s).await {
            Ok(m) => m,
            Err(e) => return failure(StatusCode::BAD_REQUEST, e),
        };
        loop {
            let field = match multipart.next_field().await {
                Ok(Some(f)) => f,
                Ok(None) => break,
                Err(e) => return failure(StatusCode::BAD_REQUEST, e),
            };
            let name = field.name().unwrap_or("").to_owned();
            let file = field.file_name().unwrap_or("").to_owned();
            let bytes = match field.bytes().await {
                Ok(b) => b,
                Err(e) => return failure(StatusCode::BAD_REQUEST, e),
            };
            if name == "images" && !file.is_empty() {
                images.push((file, bytes.to_vec()));
            } else if let Ok(text) = String::from_utf8(bytes.to_vec()) {
                params[&name] = text.into();
            }
        }
    } else {
        let bytes = match axum::body::to_bytes(request.into_body(), 8 * 1024 * 1024).await {
            Ok(b) => b,
            Err(e) => return failure(StatusCode::PAYLOAD_TOO_LARGE, e),
        };
        params = serde_json::from_slice(&bytes).unwrap_or(json!({}));
        if let Some(entries) = params["images"].as_array() {
            for entry in entries {
                if let Some(b64) = entry.as_str().or_else(|| entry["data"].as_str()) {
                    match STANDARD.decode(b64) {
                        Ok(b) => images.push(("image".into(), b)),
                        Err(_) => return failure(StatusCode::BAD_REQUEST, "Failed to read images"),
                    }
                }
            }
        }
    }
    for (k, v) in query {
        params[&k] = v.into();
    }
    let provided = if auth.is_empty() {
        params["password"].as_str().unwrap_or("")
    } else {
        &auth
    };
    if !bool::from(
        provided
            .as_bytes()
            .ct_eq(s.config.webhook_password.as_bytes()),
    ) {
        return failure(StatusCode::UNAUTHORIZED, "Unauthorized");
    }
    match crate::api::blocking(move || process(&s, &params, images)).await {
        Ok(value) => Json(value).into_response(),
        Err(e) => failure(e.0, e.1),
    }
}
fn process(s: &AppState, v: &Value, files: Vec<(String, Vec<u8>)>) -> Result<Value> {
    ensure!(
        !files.is_empty() && files.len() <= 100,
        "Provide 1–100 images."
    );
    let mut config = (*s.config).clone();
    if let Some(p) = v["printer"].as_str().filter(|s| !s.is_empty()) {
        config.printer = p.into();
    }
    if let Some(m) = v["model"].as_str().filter(|s| !s.is_empty()) {
        config.model = m.into();
    }
    let size = v["label_size"]
        .as_str()
        .unwrap_or(config.defaults["sizeId"].as_str().unwrap_or("62"));
    let media = media::lookup(size)?;
    let rotated = v["orientation"].as_str().unwrap_or(
        config.defaults["orientation"]
            .as_str()
            .unwrap_or("standard"),
    ) == "rotated";
    let high = v["high_res"].as_i64().unwrap_or_else(|| {
        v["high_res"]
            .as_str()
            .and_then(|s| s.parse().ok())
            .unwrap_or(0)
    }) != 0;
    let mode = v["image_mode"].as_str().unwrap_or("grayscale");
    let threshold = v["bw_threshold"].as_u64().unwrap_or_else(|| {
        v["bw_threshold"]
            .as_str()
            .and_then(|s| s.parse().ok())
            .unwrap_or(70)
    });
    ensure!(threshold <= 255, "Invalid black/white threshold.");
    let (mut w, mut h) = media.dots_printable;
    if high {
        w *= 2;
        h *= 2;
    }
    if h > w {
        std::mem::swap(&mut w, &mut h);
    }
    if rotated {
        std::mem::swap(&mut w, &mut h);
    }
    let mut images = Vec::new();
    let mut total_pixels = 0u64;
    for (name, data) in files {
        let mime = if name.to_lowercase().ends_with(".pdf") || data.starts_with(b"%PDF-") {
            "application/pdf"
        } else if data.starts_with(b"\x89PNG") {
            "image/png"
        } else {
            "image/jpeg"
        };
        let mut image = crate::rendering::decode_image(&data, mime)?;
        for p in image.pixels_mut() {
            *p = convert_pixel(*p, mode, threshold as u8);
        }
        let scale = if media.form_factor == 2 {
            if rotated {
                h as f64 / image.height() as f64
            } else {
                w as f64 / image.width() as f64
            }
        } else {
            (w as f64 / image.width() as f64).min(h as f64 / image.height() as f64)
        };
        let nw = (image.width() as f64 * scale).max(1.) as u32;
        let nh = (image.height() as f64 * scale).max(1.) as u32;
        ensure!(
            u64::from(nw) * u64::from(nh) <= 16_000_000,
            "Image is too large."
        );
        total_pixels +=
            u64::from(if w == 0 { nw } else { w }) * u64::from(if h == 0 { nh } else { h });
        ensure!(
            total_pixels <= 64_000_000,
            "Batch images are too large. Select fewer labels."
        );
        let resized =
            image::imageops::resize(&image, nw, nh, image::imageops::FilterType::Lanczos3);
        let mut canvas = image::RgbImage::from_pixel(
            if w == 0 { nw } else { w },
            if h == 0 { nh } else { h },
            image::Rgb([255; 3]),
        );
        let x = (canvas.width().saturating_sub(nw)) / 2;
        let y = (canvas.height().saturating_sub(nh)) / 2;
        image::imageops::overlay(&mut canvas, &resized, x.into(), y.into());
        images.push(canvas);
    }
    printer::print_images(
        &config,
        &images,
        size,
        rotated,
        high,
        matches!(mode, "grayscale" | "red_and_black" | "colored"),
    )?;
    Ok(json!({"success":true,"count":images.len()}))
}

fn convert_pixel(pixel: image::Rgb<u8>, mode: &str, threshold: u8) -> image::Rgb<u8> {
    let [r, g, b] = pixel.0;
    let l = ((r as u32 * 19595 + g as u32 * 38470 + b as u32 * 7471 + 32768) >> 16) as u8;
    match mode {
        "colored" => pixel,
        "grayscale" => image::Rgb([l; 3]),
        "red_and_black" => {
            if l < 127 {
                image::Rgb([(l as u16 * 255 / 127) as u8, 0, 0])
            } else {
                let shade = ((l as u16 - 127) * 255 / 128) as u8;
                image::Rgb([255, shade, shade])
            }
        }
        _ => image::Rgb([if l <= threshold { 0 } else { 255 }; 3]),
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn webhook_color_mapping_matches_existing_palette() {
        for (level, expected) in [
            (0, [0, 0, 0]),
            (63, [126, 0, 0]),
            (127, [255, 0, 0]),
            (191, [255, 127, 127]),
            (255, [255, 255, 255]),
        ] {
            assert_eq!(
                convert_pixel(image::Rgb([level; 3]), "red_and_black", 70).0,
                expected
            );
        }
        assert_eq!(convert_pixel(image::Rgb([70; 3]), "bw", 70).0, [0; 3]);
        assert_eq!(convert_pixel(image::Rgb([71; 3]), "bw", 70).0, [255; 3]);
    }
}
