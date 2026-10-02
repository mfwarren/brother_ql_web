use crate::{config::Config, fonts::Fonts, validation};
use anyhow::{Result, bail, ensure};
use regex::Regex;
use std::sync::LazyLock;
static TOKEN: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"\{\{([^{}]+)\}\}").unwrap());
use serde_json::{Value, json};
use std::collections::HashMap;

use crate::csv_input::{Row, parse as csv_rows};
const MAX_FIELD_BYTES: usize = 40_000;
const MAX_BATCH_BYTES: usize = 7 * 1024 * 1024;
fn append_field(out: &mut String, text: &str) -> Result<()> {
    ensure!(
        out.len() + text.len() <= MAX_FIELD_BYTES,
        "Expanded field is too long. Shorten the value or use fewer placeholders."
    );
    out.push_str(text);
    Ok(())
}
fn substitute(text: &str, values: &HashMap<String, String>) -> Result<String> {
    ensure!(text.len() <= MAX_FIELD_BYTES, "Template field is too long.");
    let token = &*TOKEN;
    let remaining = token.replace_all(text, "");
    ensure!(
        !remaining.contains("{{") && !remaining.contains("}}"),
        "Unclosed or nested field. Use {{{{Column name}}}}."
    );
    let mut out = String::new();
    let mut cursor = 0;
    for caps in token.captures_iter(text) {
        let m = caps.get(0).unwrap();
        append_field(&mut out, &text[cursor..m.start()])?;
        let name = caps[1].trim();
        append_field(
            &mut out,
            values.get(name).ok_or_else(|| {
                anyhow::anyhow!("Unknown field {{{{{name}}}}}. Match the CSV column name exactly.")
            })?,
        )?;
        cursor = m.end();
    }
    append_field(&mut out, &text[cursor..])?;
    Ok(out)
}
pub fn merge(template: &Value, values: &HashMap<String, String>) -> Result<Value> {
    let mut d = template.clone();
    let c = d
        .get_mut("content")
        .ok_or_else(|| anyhow::anyhow!("Choose a label template."))?;
    if c["kind"] == "text" {
        if let Some(paragraphs) = c["paragraphs"].as_array() {
            let mut result = Vec::new();
            for p in paragraphs {
                let runs = p["runs"]
                    .as_array()
                    .ok_or_else(|| anyhow::anyhow!("Invalid text runs."))?;
                let mut text = String::new();
                let mut spans = Vec::new();
                for r in runs {
                    let start = text.len();
                    text.push_str(
                        r["text"]
                            .as_str()
                            .ok_or_else(|| anyhow::anyhow!("Invalid formatted text."))?,
                    );
                    spans.push((start, text.len(), r));
                }
                substitute(&text, values)?;
                let token = &*TOKEN;
                let mut merged = Vec::new();
                let mut cursor = 0;
                let append = |a: usize, b: usize, target: &mut Vec<Value>| {
                    for (start, end, run) in &spans {
                        let l = a.max(*start);
                        let r = b.min(*end);
                        if l < r {
                            let mut v = (*run).clone();
                            v["text"] = text[l..r].into();
                            target.push(v);
                        }
                    }
                };
                for m in token.find_iter(&text) {
                    append(cursor, m.start(), &mut merged);
                    let mut style = spans
                        .iter()
                        .find(|(a, b, _)| *a <= m.start() && m.start() < *b)
                        .map(|(_, _, r)| (*r).clone())
                        .unwrap_or(json!({}));
                    style["text"] = substitute(m.as_str(), values)?.into();
                    merged.push(style);
                    cursor = m.end();
                }
                append(cursor, text.len(), &mut merged);
                let mut current = Vec::new();
                for r in merged {
                    let normalized = r["text"]
                        .as_str()
                        .unwrap()
                        .replace("\r\n", "\n")
                        .replace('\r', "\n");
                    for (i, line) in normalized.split('\n').enumerate() {
                        if i > 0 {
                            result.push(json!({"runs":current}));
                            current = Vec::new();
                        }
                        let mut copy = r.clone();
                        copy["text"] = line.into();
                        current.push(copy);
                    }
                }
                result.push(json!({"runs":current}));
            }
            let text = result
                .iter()
                .map(|p| {
                    p["runs"]
                        .as_array()
                        .unwrap()
                        .iter()
                        .map(|r| r["text"].as_str().unwrap())
                        .collect::<String>()
                })
                .collect::<Vec<_>>()
                .join("\n");
            c["paragraphs"] = result.into();
            c["text"] = text.into();
        } else {
            c["text"] = substitute(
                c["text"]
                    .as_str()
                    .ok_or_else(|| anyhow::anyhow!("Invalid text."))?,
                values,
            )?
            .into();
        }
    } else {
        for field in ["caption", "code", "imageUrl"] {
            if let Some(s) = c.get(field).and_then(Value::as_str) {
                c[field] = substitute(s, values)?.into();
            }
        }
    }
    Ok(d)
}
pub fn prepare(data: &Value, config: &Config, fonts: &Fonts) -> Result<Value> {
    let template = &data["template"];
    ensure!(template["content"].is_object(), "Choose a label template.");
    let zone = match data.get("timezone") {
        None => "UTC",
        Some(v) => v
            .as_str()
            .ok_or_else(|| anyhow::anyhow!("Invalid timezone."))?,
    }
    .parse::<chrono_tz::Tz>()?;
    let now = chrono::Utc::now().with_timezone(&zone);
    let (headers, rows) = if let Some(s) = data["csv"].as_str().filter(|s| !s.is_empty()) {
        csv_rows(s)?
    } else {
        if data.get("csv").is_some_and(|v| !v.is_string()) {
            bail!("Invalid CSV.");
        }
        let n = validation::integer(data.get("count").unwrap_or(&json!(1)), "Labels", 1, 100)?;
        (
            Vec::new(),
            (1..=n)
                .map(|i| Row {
                    line: i as u64,
                    values: HashMap::new(),
                    error: None,
                })
                .collect(),
        )
    };
    let count = rows.len();
    ensure!(
        serde_json::to_vec(template)?.len().saturating_mul(count) <= MAX_BATCH_BYTES,
        "Batch data is too large. Use fewer rows or a smaller image."
    );
    let mut results = Vec::new();
    let mut result_bytes = 0;
    for (i, mut row) in rows.into_iter().enumerate() {
        let result = (|| -> Result<Value> {
            if let Some(e) = row.error {
                bail!(e);
            }
            row.values.extend([
                ("@today".into(), now.format("%Y-%m-%d").to_string()),
                ("@time".into(), now.format("%H:%M").to_string()),
                ("@row".into(), (i + 1).to_string()),
                ("@total".into(), count.to_string()),
            ]);
            validation::draft(&merge(template, &row.values)?, config, fonts, true)
        })();
        let item = match result {
            Ok(draft) => json!({"row":i+1,"line":row.line,"kind":"ready","draft":draft}),
            Err(e) => json!({"row":i+1,"line":row.line,"kind":"error","message":e.to_string()}),
        };
        result_bytes += serde_json::to_vec(&item)?.len();
        ensure!(
            result_bytes <= MAX_BATCH_BYTES,
            "Expanded batch data is too large. Use fewer rows or shorter values."
        );
        results.push(item);
    }
    Ok(
        json!({"headers":headers,"rows":results,"timestamp":now.to_rfc3339(),"jobId":uuid::Uuid::new_v4().to_string()}),
    )
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn repeated_placeholders_cannot_amplify_large_cells() {
        let values = HashMap::from([("A".into(), "x".repeat(1_000))]);
        assert!(
            substitute(&"{{A}}".repeat(2_000), &values)
                .unwrap_err()
                .to_string()
                .contains("too long")
        );
        assert_eq!(
            substitute("{{A}}", &HashMap::from([("A".into(), "é".repeat(10_000))]))
                .unwrap()
                .chars()
                .count(),
            10_000
        );
    }
    #[test]
    fn repeated_image_templates_are_bounded_before_cloning() {
        let directory = tempfile::tempdir().unwrap();
        let config = Config {
            data_dir: directory.path().into(),
            ..Default::default()
        };
        let fonts = Fonts::load(&config).unwrap();
        let template = json!({"content":{"kind":"image","image":{"base64":"A".repeat(100_000)}}});
        let error =
            prepare(&json!({"template":template,"count":100}), &config, &fonts).unwrap_err();
        assert!(error.to_string().contains("Batch data is too large"));
    }
    #[test]
    fn literal_and_split_style() {
        let d = json!({"content":{"kind":"text","text":"{{Name}}","paragraphs":[{"runs":[{"text":"{{Na","bold":true},{"text":"me}}"}]}]}});
        let merged = merge(
            &d,
            &HashMap::from([("Name".into(), "A\n{{literal}}".into())]),
        )
        .unwrap();
        assert_eq!(merged["content"]["text"], "A\n{{literal}}");
        assert_eq!(merged["content"]["paragraphs"][1]["runs"][0]["bold"], true);
    }
    #[test]
    fn csv_preserves_values_and_reports_rows() {
        let (h, r) = csv_rows("Code,Name\n001,\"A\nB\"\n002\n").unwrap();
        assert_eq!(h, vec!["Code", "Name"]);
        assert_eq!(r[0].values["Code"], "001");
        assert_eq!(r[0].line, 3);
        assert!(r[1].error.is_some());
    }
    #[test]
    fn duplicate_headers_fail() {
        assert!(csv_rows("A,A\nx,y").is_err());
    }
}
