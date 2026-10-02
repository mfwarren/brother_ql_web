use std::path::PathBuf;
use serde_json::{Value, json};
#[derive(Clone, Debug)]
pub struct Config {
    pub data_dir: PathBuf,
    pub labels_dir: PathBuf,
    pub static_dir: PathBuf,
    pub font_folder: Option<PathBuf>,
    pub printer: String,
    pub model: String,
    pub defaults: Value,
    pub webhook_password: String,
    pub seed_samples: bool,
}
impl Default for Config {
    fn default() -> Self {
        Self { data_dir: "instance".into(), labels_dir: "instance/studio-labels".into(),
            static_dir: "app/static/studio".into(), font_folder: None,
            printer: "simulation".into(), model: "QL-800".into(),
            defaults: json!({"font":"DejaVu Serif,Book","sizeId":"62","orientation":"standard","margin":24,"fontSize":70,"autoDetectRoll":true}),
            webhook_password: String::new(), seed_samples: true }
    }
}
