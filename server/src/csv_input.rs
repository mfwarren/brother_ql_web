//! Strict CSV records with source line numbers, including quoted CR/LF fields.
use anyhow::{Result, ensure};
use std::collections::{HashMap, HashSet};

#[derive(Debug)]
pub struct Row {
    pub line: u64,
    pub values: HashMap<String, String>,
    pub error: Option<String>,
}

#[derive(Clone, Copy)]
enum State {
    Start,
    Plain,
    Quoted,
    Closed,
}

fn records(text: &str) -> Result<Vec<(u64, Vec<String>)>> {
    let mut records = Vec::new();
    let mut fields = Vec::new();
    let mut field = String::new();
    let mut state = State::Start;
    let mut line = 1;
    let mut started = false;
    let mut chars = text.trim_start_matches('\u{feff}').chars().peekable();
    while let Some(ch) = chars.next() {
        if matches!(state, State::Quoted) {
            if ch == '"' {
                if chars.peek() == Some(&'"') {
                    chars.next();
                    field.push('"');
                } else {
                    state = State::Closed;
                }
            } else {
                field.push(ch);
                if ch == '\r' {
                    if chars.peek() == Some(&'\n') {
                        chars.next();
                        field.push('\n');
                    }
                    line += 1;
                } else if ch == '\n' {
                    line += 1;
                }
            }
            continue;
        }
        if matches!(state, State::Closed) {
            ensure!(
                matches!(ch, ',' | '\r' | '\n'),
                "CSV line {line}: Unexpected text after a quoted CSV field."
            );
        }
        match ch {
            '\r' | '\n' => {
                if started {
                    fields.push(std::mem::take(&mut field));
                }
                records.push((line, std::mem::take(&mut fields)));
                if ch == '\r' && chars.peek() == Some(&'\n') {
                    chars.next();
                }
                line += 1;
                state = State::Start;
                started = false;
            }
            ',' => {
                fields.push(std::mem::take(&mut field));
                state = State::Start;
                started = true;
            }
            '"' if matches!(state, State::Start) => {
                state = State::Quoted;
                started = true;
            }
            _ => {
                field.push(ch);
                state = State::Plain;
                started = true;
            }
        }
    }
    ensure!(
        !matches!(state, State::Quoted),
        "CSV line {line}: Unclosed quoted CSV field."
    );
    if started {
        fields.push(field);
        records.push((line, fields));
    }
    Ok(records)
}

pub fn parse(text: &str) -> Result<(Vec<String>, Vec<Row>)> {
    ensure!(
        text.len() <= 1_000_000,
        "Choose a UTF-8 CSV smaller than 1 MB."
    );
    let mut records = records(text)?.into_iter();
    let (_, raw_headers) = records
        .next()
        .ok_or_else(|| anyhow::anyhow!("The CSV is empty."))?;
    let headers: Vec<_> = raw_headers
        .into_iter()
        .map(|s| s.trim().to_owned())
        .collect();
    ensure!(
        !headers.is_empty() && headers.len() <= 50 && headers.iter().all(|s| !s.is_empty()),
        "Use 1–50 named columns. Every header needs a name."
    );
    ensure!(
        headers.iter().collect::<HashSet<_>>().len() == headers.len(),
        "Column names must be unique."
    );
    ensure!(
        headers
            .iter()
            .all(|s| !s.contains(['{', '}']) && !s.starts_with('@')),
        "Column names cannot contain braces or start with @."
    );
    let mut rows = Vec::new();
    for (line, fields) in records {
        if fields.iter().all(|s| s.trim().is_empty()) {
            continue;
        }
        ensure!(
            rows.len() < 100,
            "Use at most 100 data rows per batch. Split larger CSV files."
        );
        let error = (fields.len() != headers.len()).then(|| {
            format!(
                "Expected {} columns, found {}.",
                headers.len(),
                fields.len()
            )
        });
        rows.push(Row {
            line,
            values: headers.iter().cloned().zip(fields).collect(),
            error,
        });
    }
    ensure!(!rows.is_empty(), "The CSV has headers but no data rows.");
    Ok((headers, rows))
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn bom_quoted_headers_still_require_strict_quotes() {
        assert!(parse("\u{feff}\"Name\"junk\nCoffee").is_err());
        assert!(parse("\u{feff}\"Name\nCoffee").is_err());
        let (headers, rows) = parse("\u{feff}\"Name\"\r\nCoffee").unwrap();
        assert_eq!(headers, ["Name"]);
        assert_eq!(rows[0].values["Name"], "Coffee");
    }
    #[test]
    fn quoted_newlines_preserve_values_and_end_line_numbers() {
        let (_, rows) =
            parse("Name,SKU\r\n\"Coffee\rbeans\r\nbag\nlarge\",0012\r\nTea,0013").unwrap();
        assert_eq!(rows[0].values["Name"], "Coffee\rbeans\r\nbag\nlarge");
        assert_eq!(rows[0].values["SKU"], "0012");
        assert_eq!(rows[0].line, 5);
        assert_eq!(rows[1].line, 6);
    }
    #[test]
    fn leading_empty_header_is_not_silently_skipped() {
        assert!(parse("\nName\nCoffee").is_err());
        assert!(parse("\r\nName\nCoffee").is_err());
        assert!(parse("\"\"\nCoffee").is_err());
    }
    #[test]
    fn empty_rows_and_escaped_quotes_match_csv_reader() {
        let (_, rows) =
            parse("Name,SKU\n\n , \n\"Coffee, \"\"dark\"\"\",001\nshort\ntoo,many,columns\n")
                .unwrap();
        assert_eq!(rows.len(), 3);
        assert_eq!(rows[0].line, 4);
        assert_eq!(rows[0].values["Name"], "Coffee, \"dark\"");
        assert!(rows[1].error.as_ref().unwrap().contains("found 1"));
        assert!(rows[2].error.as_ref().unwrap().contains("found 3"));
    }
    #[test]
    fn quotes_inside_unquoted_fields_are_literal() {
        let (_, rows) = parse("Name\n Coffee\"beans\n\"Tea\"\"pot\"").unwrap();
        assert_eq!(rows[0].values["Name"], " Coffee\"beans");
        assert_eq!(rows[1].values["Name"], "Tea\"pot");
        assert!(parse("Name\n\"Tea\" ").is_err());
    }
    #[test]
    fn data_row_limits_and_duplicate_headers_are_checked() {
        assert!(parse("Name,Name\nA,B").is_err());
        assert!(parse(&format!("Name\n{}", "A\n".repeat(101))).is_err());
        assert_eq!(
            parse(&format!("Name\n{}", "A\n".repeat(100)))
                .unwrap()
                .1
                .len(),
            100
        );
    }
}
