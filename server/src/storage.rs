use crate::{config::Config, fonts::Fonts};
use anyhow::{Result, ensure};
use serde_json::{Value, json};
use std::{
    fs,
    io::Write,
    path::{Path, PathBuf},
};
use uuid::Uuid;

pub fn write_json(path: &Path, value: &Value) -> Result<()> {
    let parent = path
        .parent()
        .ok_or_else(|| anyhow::anyhow!("Missing parent directory"))?;
    fs::create_dir_all(parent)?;
    let mut tmp = tempfile::NamedTempFile::new_in(parent)?;
    serde_json::to_writer(&mut tmp, value)?;
    tmp.flush()?;
    tmp.as_file().sync_all()?;
    tmp.persist(path)?;
    Ok(())
}
pub fn path(config: &Config, id: Uuid) -> PathBuf {
    config.labels_dir.join(format!("{id}.json"))
}
pub fn saved(mut v: Value, fonts: &Fonts) -> Result<Value> {
    for key in ["id", "name", "updatedAt", "draft"] {
        ensure!(v.get(key).is_some(), "Damaged label record");
    }
    v.as_object_mut().unwrap().remove("version");
    if let Some(f) = v["draft"]["font"].as_str() {
        v["draft"]["font"] = fonts.canonical(f).into();
    }
    Ok(v)
}
pub fn list(config: &Config, fonts: &Fonts) -> Result<Value> {
    fs::create_dir_all(&config.labels_dir)?;
    if config.seed_samples {
        seed(config, fonts)?;
    }
    let mut items: Vec<Value> = fs::read_dir(&config.labels_dir)?
        .filter_map(|e| e.ok())
        .filter(|e| e.path().extension().is_some_and(|s| s == "json"))
        .filter_map(|e| fs::read(e.path()).ok())
        .filter_map(|s| serde_json::from_slice(&s).ok())
        .filter_map(|v| saved(v, fonts).ok())
        .collect();
    items.sort_by(|a, b| b["updatedAt"].as_str().cmp(&a["updatedAt"].as_str()));
    Ok(json!({"labels":items}))
}
fn seed(config: &Config, fonts: &Fonts) -> Result<()> {
    use fs2::FileExt;
    let lock = fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(config.labels_dir.join(".starter-labels.lock"))?;
    lock.lock_exclusive()?;
    let marker = config.labels_dir.join(".starter-labels-v1");
    if marker.exists() {
        return Ok(());
    }
    let samples: Value = serde_json::from_str(include_str!("../data/starter-labels.json"))?;
    let mut records = Vec::new();
    for sample in samples.as_array().unwrap() {
        let slug = sample[0].as_str().unwrap();
        let id = Uuid::new_v5(
            &Uuid::NAMESPACE_URL,
            format!("https://github.com/mfwarren/brother_ql_web/starter/{slug}").as_bytes(),
        )
        .to_string();
        let mut draft = sample[2].clone();
        if fonts.get(draft["font"].as_str().unwrap_or("")).is_err() {
            draft["font"] = fonts.default_font().into();
        }
        records.push(json!({"version":1,"id":id,"name":sample[1],"updatedAt":"2026-01-01T00:00:00+00:00","draft":draft}));
    }
    let existing: Vec<_> = fs::read_dir(&config.labels_dir)?
        .filter_map(|e| e.ok())
        .filter(|e| e.path().extension().is_some_and(|s| s == "json"))
        .map(|e| e.file_name().to_string_lossy().into_owned())
        .collect();
    if existing.iter().all(|f| {
        records
            .iter()
            .any(|r| format!("{}.json", r["id"].as_str().unwrap()) == *f)
    }) {
        for record in records {
            let p = path(config, Uuid::parse_str(record["id"].as_str().unwrap())?);
            if !p.exists() {
                write_json(&p, &record)?;
            }
        }
    }
    write_json(&marker, &json!({"version":1}))
}
