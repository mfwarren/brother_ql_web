use serde_json::{Value, json};
use std::path::PathBuf;
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
        Self {
            data_dir: "instance".into(),
            labels_dir: "instance/studio-labels".into(),
            static_dir: "app/static/studio".into(),
            font_folder: None,
            printer: "simulation".into(),
            model: "QL-800".into(),
            defaults: json!({"font":"DejaVu Serif,Book","sizeId":"62","orientation":"standard","margin":24,"fontSize":70,"autoDetectRoll":true}),
            webhook_password: String::new(),
            seed_samples: true,
        }
    }
}
impl Config {
    pub fn load() -> anyhow::Result<Self> {
        let mut config = Self::default();
        if let Ok(path) = std::env::var("LABEL_STUDIO_CONFIG") {
            let v: Value = serde_json::from_slice(&std::fs::read(path)?)?;
            for (key, target) in [
                ("dataDir", &mut config.data_dir),
                ("labelsDir", &mut config.labels_dir),
                ("staticDir", &mut config.static_dir),
            ] {
                if let Some(s) = v[key].as_str() {
                    *target = s.into();
                }
            }
            if v["dataDir"].is_string() && !v["labelsDir"].is_string() {
                config.labels_dir = config.data_dir.join("labels");
            }
            if let Some(s) = v["fontFolder"].as_str() {
                config.font_folder = Some(s.into());
            }
            if let Some(s) = v["printer"].as_str() {
                config.printer = s.into();
            }
            if let Some(s) = v["model"].as_str() {
                config.model = s.into();
            }
            if let Some(s) = v["webhookPassword"].as_str() {
                config.webhook_password = s.into();
            }
            if let Some(d) = v["defaults"].as_object() {
                for (k, v) in d {
                    config.defaults[k] = v.clone();
                }
            }
            if let Some(s) = v["seedSamples"].as_bool() {
                config.seed_samples = s;
            }
        }
        if let Ok(s) = std::env::var("STUDIO_DATA_DIR") {
            config.data_dir = s.into();
            config.labels_dir = config.data_dir.join("labels");
        }
        if let Ok(s) = std::env::var("STUDIO_LABELS_DIR") {
            config.labels_dir = s.into();
        }
        if let Ok(s) = std::env::var("STUDIO_STATIC_DIR") {
            config.static_dir = s.into();
        }
        if let Ok(s) = std::env::var("FONT_FOLDER") {
            config.font_folder = Some(s.into());
        }
        if let Ok(s) = std::env::var("PRINTER_PRINTER") {
            config.printer = s;
        }
        if let Ok(s) = std::env::var("PRINTER_MODEL") {
            config.model = s;
        }
        if let Ok(s) = std::env::var("WEBHOOK_PASSWORD") {
            config.webhook_password = s;
        }
        crate::media::model(&config.model)?;
        std::fs::create_dir_all(&config.data_dir)?;
        std::fs::create_dir_all(&config.labels_dir)?;
        Ok(config)
    }
}
