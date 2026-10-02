use crate::{config::Config, fonts::Fonts, media};
use anyhow::{Result, bail, ensure};
use base64::{Engine, engine::general_purpose::STANDARD};
use serde_json::Value;

pub fn string<'a>(v: &'a Value, name: &str, max: usize, empty: bool) -> Result<&'a str> {
    let s = v
        .as_str()
        .ok_or_else(|| anyhow::anyhow!("Invalid {name}."))?;
    ensure!(
        s.chars().count() <= max && (empty || !s.trim().is_empty()),
        "Invalid {name}."
    );
    Ok(s)
}
pub fn integer(v: &Value, name: &str, lo: i64, hi: i64) -> Result<i64> {
    let n = v
        .as_i64()
        .ok_or_else(|| anyhow::anyhow!("{name} must be between {lo} and {hi}."))?;
    ensure!(
        (lo..=hi).contains(&n),
        "{name} must be between {lo} and {hi}."
    );
    Ok(n)
}
fn choice(v: &Value, name: &str, options: &[&str]) -> Result<()> {
    ensure!(
        v.as_str().is_some_and(|s| options.contains(&s)),
        "Invalid {name}."
    );
    Ok(())
}
pub fn draft(v: &Value, config: &Config, fonts: &Fonts, allow_url: bool) -> Result<Value> {
    ensure!(v.is_object(), "Expected a label draft.");
    let mut d = v.clone();
    let size = string(&v["sizeId"], "label size", 32, false)?;
    ensure!(
        media::sizes(&config.model)
            .as_array()
            .is_some_and(|sizes| sizes.iter().any(|s| s["id"] == size)),
        "Unknown label size."
    );
    choice(&v["orientation"], "orientation", &["standard", "rotated"])?;
    let font = fonts.canonical(string(&v["font"], "font", 200, false)?);
    fonts.get(&font)?;
    d["font"] = font.into();
    integer(&v["fontSize"], "Font size", 8, 200)?;
    choice(&v["align"], "alignment", &["left", "center", "right"])?;
    if let Some(x) = v.get("verticalAlign") {
        choice(x, "vertical alignment", &["top", "center", "bottom"])?;
    }
    choice(&v["color"], "color", &["black", "red"])?;
    integer(&v["margin"], "Margin", 0, 100)?;
    if let Some(x) = v.get("lineSpacing") {
        integer(x, "Line spacing", 100, 300)?;
    }
    if let Some(m) = v.get("margins") {
        ensure!(
            m.as_object().is_some_and(|m| m.len() == 4),
            "Provide all four margins."
        );
        for s in ["left", "right", "top", "bottom"] {
            integer(&m[s], s, 0, 100)?;
        }
    }
    ensure!(v["highRes"].is_boolean(), "Invalid highRes.");
    ensure!(
        size != "62red" || v["highRes"] == false,
        "High resolution is unavailable for red media."
    );
    let c = &v["content"];
    ensure!(
        (v["color"] != "red" && c["mode"] != "red") || size == "62red",
        "Red requires 62red media."
    );
    match c["kind"].as_str() {
        Some("text") => {
            let text = string(&c["text"], "text", 10000, false)?;
            if let Some(p) = c.get("paragraphs") {
                paragraphs(p, text, fonts)?;
            }
        }
        Some("qr") => {
            string(&c["code"], "QR code", 2000, false)?;
            string(&c["caption"], "caption", 10000, true)?;
        }
        Some("barcode") => {
            barcode(c)?;
            string(&c["caption"], "caption", 10000, true)?;
        }
        Some("image") => {
            string(&c["caption"], "caption", 10000, true)?;
            choice(&c["mode"], "image mode", &["grayscale", "bw", "red"])?;
            ensure!(c["fit"].is_boolean(), "Invalid image fit.");
            if allow_url && c["imageUrl"].as_str().is_some_and(|s| !s.is_empty()) {
                string(&c["imageUrl"], "image URL", 2000, false)?;
            } else {
                let i = &c["image"];
                let name = string(&i["name"], "image name", 255, false)?.to_lowercase();
                let raw = STANDARD.decode(string(&i["base64"], "image data", 7_000_000, false)?)?;
                ensure!(
                    !raw.is_empty() && raw.len() <= 5 * 1024 * 1024,
                    "Image must be no larger than 5 MiB."
                );
                let valid = match i["mime"].as_str() {
                    Some("image/png") => {
                        name.ends_with(".png") && raw.starts_with(b"\x89PNG\r\n\x1a\n")
                    }
                    Some("image/jpeg") => {
                        (name.ends_with(".jpg") || name.ends_with(".jpeg"))
                            && raw.starts_with(b"\xff\xd8")
                    }
                    Some("application/pdf") => name.ends_with(".pdf") && raw.starts_with(b"%PDF-"),
                    _ => false,
                };
                ensure!(valid, "Invalid image data or filename.");
            }
        }
        _ => bail!("Invalid content type."),
    };
    Ok(d)
}
fn barcode(c: &Value) -> Result<()> {
    let s = string(&c["code"], "barcode value", 80, false)?;
    let n = match c["format"].as_str() {
        Some("code128") => {
            ensure!(
                s.bytes().all(|b| (32..=126).contains(&b)),
                "Code 128 supports printable ASCII text and numbers."
            );
            return Ok(());
        }
        Some("ean13") => 12,
        Some("ean8") => 7,
        Some("upca") => 11,
        _ => bail!("Unknown barcode type."),
    };
    ensure!(
        s.bytes().all(|b| b.is_ascii_digit()) && (s.len() == n || s.len() == n + 1),
        "Incorrect barcode length or digits."
    );
    if s.len() == n + 1 {
        let sum: u32 = s[..n]
            .bytes()
            .rev()
            .enumerate()
            .map(|(i, b)| (b - b'0') as u32 * if i % 2 == 0 { 3 } else { 1 })
            .sum();
        ensure!(
            s.as_bytes()[n] - b'0' == ((10 - sum % 10) % 10) as u8,
            "Incorrect barcode check digit."
        );
    }
    Ok(())
}
fn paragraphs(p: &Value, text: &str, fonts: &Fonts) -> Result<()> {
    let ps = p
        .as_array()
        .ok_or_else(|| anyhow::anyhow!("Invalid paragraphs."))?;
    ensure!((1..=100).contains(&ps.len()), "Use 1–100 text paragraphs.");
    let mut count = 0;
    let mut lines = Vec::new();
    for p in ps {
        ensure!(
            p.as_object().is_some_and(|m| m.len() == 1),
            "Invalid text paragraph."
        );
        let runs = p["runs"]
            .as_array()
            .ok_or_else(|| anyhow::anyhow!("Invalid text runs."))?;
        count += runs.len();
        ensure!(count <= 500, "Too many formatting changes in this label.");
        let mut line = String::new();
        for r in runs {
            ensure!(
                r.as_object().is_some_and(|m| m.keys().all(|s| [
                    "text",
                    "size",
                    "bold",
                    "italic",
                    "font",
                    "underline"
                ]
                .contains(&s.as_str()))),
                "Invalid formatted text."
            );
            let s = string(&r["text"], "formatted text", 2000, true)?;
            ensure!(
                !s.contains(['\n', '\r']),
                "Use separate paragraphs for line breaks."
            );
            line.push_str(s);
            if let Some(f) = r.get("font") {
                fonts.get(string(f, "font", 200, false)?)?;
            }
            if let Some(n) = r.get("size") {
                integer(n, "Text size", 8, 200)?;
            }
            for mark in ["bold", "italic", "underline"] {
                if let Some(x) = r.get(mark) {
                    ensure!(x.is_boolean(), "Invalid text style.");
                }
            }
        }
        lines.push(line);
    }
    ensure!(
        lines.join("\n") == text && text.chars().count() <= 2000,
        "Formatted text must match the label text and be at most 2,000 characters."
    );
    Ok(())
}
