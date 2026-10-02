//! Device geometry from brother_ql-inventree 1.3 (GPL-3.0); SKU names are shared with Studio.
use anyhow::{Result, bail};
use serde::Deserialize;
use serde_json::{Value, json};
use std::sync::LazyLock;
#[derive(Clone, Debug, Deserialize)]
pub struct Media {
    pub identifier: String,
    pub name: String,
    pub tape_size: (u32, u32),
    pub dots_printable: (u32, u32),
    pub form_factor: u8,
    pub offset_r: i32,
    pub feed_margin: u16,
    pub restricted_to_models: Vec<String>,
    pub color: u8,
}
impl Media {
    pub fn fixed_size(&self) -> bool {
        matches!(self.form_factor, 1 | 3)
    }
}
#[derive(Clone, Debug, Deserialize)]
pub struct Model {
    pub identifier: String,
    pub number_bytes_per_row: usize,
    pub additional_offset_r: i32,
    pub mode_setting: bool,
    pub cutting: bool,
    pub expanded_mode: bool,
    pub compression_support: bool,
    pub two_color: bool,
    pub num_invalidate_bytes: usize,
    pub series_code: u8,
    pub model_code: u8,
}
static MEDIA: LazyLock<Vec<Media>> =
    LazyLock::new(|| serde_json::from_str(include_str!("../data/media.json")).unwrap());
static MODELS: LazyLock<Vec<Model>> =
    LazyLock::new(|| serde_json::from_str(include_str!("../data/models.json")).unwrap());
pub fn all() -> &'static [Media] {
    &MEDIA
}
pub fn model(id: &str) -> Result<Model> {
    MODELS
        .iter()
        .find(|m| m.identifier == id)
        .cloned()
        .ok_or_else(|| anyhow::anyhow!("Unknown printer model: {id}"))
}
pub fn model_code(series: u8, code: u8) -> String {
    MODELS
        .iter()
        .find(|m| m.series_code == series && m.model_code == code)
        .map(|m| m.identifier.clone())
        .unwrap_or("Unknown".into())
}
pub fn lookup(id: &str) -> Result<Media> {
    MEDIA
        .iter()
        .find(|m| m.identifier == id)
        .cloned()
        .ok_or_else(|| anyhow::anyhow!("Unknown label size: {id}"))
}
pub fn supported(m: &Media, model: &Model) -> bool {
    (m.form_factor == 4) == model.identifier.starts_with("PT-")
        && (m.restricted_to_models.is_empty() || m.restricted_to_models.contains(&model.identifier))
        && (m.color == 0 || model.two_color)
}
pub fn validate(id: &str, model_id: &str) -> Result<Media> {
    let m = lookup(id)?;
    if !supported(&m, &model(model_id)?) {
        bail!("Label size is not supported by this printer");
    }
    Ok(m)
}
pub fn sizes(model_id: &str) -> Value {
    let Ok(model) = model(model_id) else {
        return json!([]);
    };
    let catalog: Value =
        serde_json::from_str(include_str!("../../app/data/label-rolls.json")).unwrap();
    Value::Array(MEDIA.iter().filter(|m|supported(m,&model)).map(|m|{
 let info=&catalog[&m.identifier];let codes=info["codes"].as_array().cloned().unwrap_or_default();
 let mut name=m.name.clone();if !codes.is_empty(){name+=&format!(" · {}",codes.iter().take(2).filter_map(Value::as_str).collect::<Vec<_>>().join(" / "));}else if m.identifier=="12+17"{name+=" (12+17 profile)";}
 json!({"id":m.identifier,"name":name,"fixedSize":m.fixed_size(),"codes":codes,"description":info["description"].as_str().unwrap_or("Generic driver profile")})}).collect())
}
