//! Rasterize the saved Studio document format without an interpreter.
use crate::fonts::Fonts;
use anyhow::{Context, Result, bail, ensure};
use base64::Engine;
use freetype::{
    Face, Library, RenderMode,
    face::{KerningMode, LoadFlag},
};
use image::{Rgb, RgbImage, imageops};
use serde_json::Value;
use std::{collections::HashMap, io::Cursor, path::Path, process::Command};

const WHITE: Rgb<u8> = Rgb([255; 3]);
const MAX_PIXELS: u64 = 16_000_000;

#[derive(Clone, Copy, Debug)]
pub struct Geometry {
    pub width: u32,
    pub height: u32,
    pub continuous: bool,
    pub rotated: bool,
}

pub fn geometry(draft: &Value) -> Result<Geometry> {
    let media = crate::media::lookup(string(draft, "sizeId"))?;
    let (mut width, mut height) = media.dots_printable;
    let continuous = !media.fixed_size();
    if boolean(draft, "highRes") {
        width *= 2;
        height *= 2;
    }
    if height > width {
        std::mem::swap(&mut width, &mut height);
    }
    let rotated = string(draft, "orientation") == "rotated";
    if rotated {
        std::mem::swap(&mut width, &mut height);
    }
    Ok(Geometry {
        width,
        height,
        continuous,
        rotated,
    })
}
fn string<'a>(v: &'a Value, key: &str) -> &'a str {
    v[key].as_str().unwrap_or("")
}
fn boolean(v: &Value, key: &str) -> bool {
    v[key].as_bool().unwrap_or(false)
}
fn number(v: &Value, key: &str, fallback: i64) -> i64 {
    v[key].as_i64().unwrap_or(fallback)
}
fn color(draft: &Value) -> Rgb<u8> {
    if string(draft, "color") == "red" {
        Rgb([255, 0, 0])
    } else {
        Rgb([0, 0, 0])
    }
}
fn margins(draft: &Value) -> [i64; 4] {
    ["left", "right", "top", "bottom"]
        .map(|side| number(&draft["margins"], side, number(draft, "margin", 0)))
}
fn canvas(w: i64, h: i64) -> Result<RgbImage> {
    let (w, h) = (w.max(1) as u64, h.max(1) as u64);
    ensure!(
        w <= 11000 && h <= 11000 && w * h <= MAX_PIXELS,
        "Label is too large to render."
    );
    Ok(RgbImage::from_pixel(w as u32, h as u32, WHITE))
}

struct Font {
    face: Face,
    size: u32,
    ascent: i64,
    descent: i64,
}
#[derive(Default, Clone, Copy, Debug)]
struct Bounds {
    left: i64,
    top: i64,
    right: i64,
    bottom: i64,
    advance: f64,
}
impl Font {
    #[allow(
        clippy::unnecessary_cast,
        reason = "FreeType C long is 32 bits on the Pi and 64 bits on desktop"
    )]
    fn from_face(mut face: Face, size: u32, axes: &[f32]) -> Result<Self> {
        if !axes.is_empty() {
            let mut coordinates: Vec<freetype::ffi::FT_Fixed> = axes
                .iter()
                .map(|x| (*x as f64 * 65536.).round() as _)
                .collect();
            // The face owns its FreeType handle and the coordinates remain live for this call.
            let result = unsafe {
                freetype::ffi::FT_Set_Var_Design_Coordinates(
                    face.raw_mut(),
                    coordinates.len() as _,
                    coordinates.as_mut_ptr(),
                )
            };
            ensure!(
                result == 0,
                "Unable to select variable font style ({result})."
            );
        }
        face.set_pixel_sizes(0, size)?;
        let metrics = face.size_metrics().context("Font has no size metrics")?;
        Ok(Self {
            face,
            size,
            ascent: metrics.ascender as i64 / 64,
            descent: -metrics.descender as i64 / 64,
        })
    }
    fn load(library: &Library, path: &Path, size: u32, axes: &[f32]) -> Result<Self> {
        Self::from_face(library.new_face(path, 0)?, size, axes)
    }
    #[allow(
        clippy::unnecessary_cast,
        reason = "FreeType C long is 32 bits on the Pi and 64 bits on desktop"
    )]
    fn bounds(&self, text: &str) -> Result<Bounds> {
        let mut b = Bounds::default();
        let mut pen = 0f64;
        let mut previous = 0;
        for ch in text.chars() {
            let index = self.face.get_char_index(ch as usize).unwrap_or(0);
            if previous != 0 && index != 0 {
                // Pillow's BASIC layout stores the grid-fitted kerning in 26.6 units.
                pen += self
                    .face
                    .get_kerning(previous, index, KerningMode::KerningDefault)?
                    .x as f64
                    / 4096.;
            }
            self.face.load_glyph(index, LoadFlag::DEFAULT)?;
            let glyph = self.face.glyph();
            let metrics = glyph.metrics();
            let x = pen.round() as i64;
            b.left = b.left.min(x + metrics.horiBearingX as i64 / 64);
            b.right = b
                .right
                .max(x + (metrics.horiBearingX as i64 + metrics.width as i64 + 63) / 64);
            b.top = b.top.min(-metrics.horiBearingY as i64 / 64);
            b.bottom = b
                .bottom
                .max((-metrics.horiBearingY as i64 + metrics.height as i64 + 63) / 64);
            pen += glyph.advance().x as f64 / 64.;
            previous = index;
        }
        b.right = b.right.max(pen.round() as i64);
        b.advance = pen;
        Ok(b)
    }
    fn draw(
        &self,
        image: &mut RgbImage,
        text: &str,
        x: f64,
        baseline: f64,
        ink: Rgb<u8>,
    ) -> Result<()> {
        let mut pen = (x * 64.).round() / 64.;
        let mut previous = 0;
        for ch in text.chars() {
            let index = self.face.get_char_index(ch as usize).unwrap_or(0);
            if previous != 0 && index != 0 {
                pen += self
                    .face
                    .get_kerning(previous, index, KerningMode::KerningDefault)?
                    .x as f64
                    / 4096.;
            }
            self.face.load_glyph(index, LoadFlag::DEFAULT)?;
            let glyph = self.face.glyph();
            let advance = glyph.advance().x as f64 / 64.;
            glyph.render_glyph(RenderMode::Normal)?;
            let bitmap = glyph.bitmap();
            let ox = pen.round() as i64 + glyph.bitmap_left() as i64;
            let oy = ((baseline + 0.5).ceil() - 1.) as i64 - glyph.bitmap_top() as i64;
            let pitch = bitmap.pitch();
            for row in 0..bitmap.rows() {
                for col in 0..bitmap.width() {
                    let (xx, yy) = (ox + col as i64, oy + row as i64);
                    if xx < 0 || yy < 0 || xx >= image.width() as i64 || yy >= image.height() as i64
                    {
                        continue;
                    }
                    let offset = if pitch >= 0 {
                        row * pitch + col
                    } else {
                        (bitmap.rows() - row - 1) * -pitch + col
                    };
                    let alpha = bitmap.buffer()[offset as usize] as u32;
                    let dst = image.get_pixel_mut(xx as u32, yy as u32);
                    for channel in 0..3 {
                        dst[channel] = ((ink[channel] as u32 * alpha
                            + dst[channel] as u32 * (255 - alpha)
                            + 127)
                            / 255) as u8;
                    }
                }
            }
            pen += advance;
            previous = index;
        }
        Ok(())
    }
}
struct FontCache<'a> {
    library: Library,
    registry: &'a Fonts,
    fonts: HashMap<(String, u32), Font>,
}
impl<'a> FontCache<'a> {
    fn new(registry: &'a Fonts) -> Result<Self> {
        Ok(Self {
            library: Library::init()?,
            registry,
            fonts: HashMap::new(),
        })
    }
    fn get(&mut self, id: &str, size: u32) -> Result<&Font> {
        let key = (id.to_owned(), size);
        if !self.fonts.contains_key(&key) {
            let face = self.registry.get(id)?;
            self.fonts.insert(
                key.clone(),
                Font::load(&self.library, &face.path, size, &face.axes)?,
            );
        }
        Ok(&self.fonts[&key])
    }
}

#[derive(Clone)]
struct Run {
    text: String,
    font: String,
    size: u32,
    underline: bool,
}
struct TextLine {
    runs: Vec<Run>,
    ascent: i64,
    descent: i64,
    left: i64,
    width: i64,
}
fn finish_line(lines: &mut Vec<Vec<Run>>, runs: &mut Vec<Run>) {
    while runs.last().is_some_and(|r| r.text.trim().is_empty()) {
        runs.pop();
    }
    if let Some(last) = runs.last_mut() {
        last.text = last.text.trim_end().to_owned();
    }
    lines.push(std::mem::take(runs));
}
fn rich_text(draft: &Value, fonts: &mut FontCache, width: i64, height: i64) -> Result<RgbImage> {
    let fallback_id = fonts.registry.styled(string(draft, "font"), false, false)?;
    let size = number(draft, "fontSize", 40) as u32;
    let fallback = fonts.get(&fallback_id, size)?;
    let fallback_metrics = (fallback.ascent, fallback.descent);
    let max_width = if width > 0 { width } else { 11000 };
    let synthesized;
    let paragraphs = if let Some(p) = draft["content"]["paragraphs"].as_array() {
        p
    } else {
        synthesized = string(&draft["content"], "text")
            .split('\n')
            .map(|text| serde_json::json!({"runs":[{"text":text}]}))
            .collect::<Vec<_>>();
        &synthesized
    };
    let mut lines = Vec::new();
    let tokenizer = regex::Regex::new(r"\s+|\S+")?;
    let mut runs = Vec::new();
    let mut advance = 0.;
    for paragraph in paragraphs {
        for run in paragraph["runs"]
            .as_array()
            .context("Invalid text paragraph")?
        {
            let id = fonts.registry.styled(
                run["font"].as_str().unwrap_or(string(draft, "font")),
                boolean(run, "bold"),
                boolean(run, "italic"),
            )?;
            let size = number(run, "size", size as i64) as u32;
            let font = fonts.get(&id, size)?;
            for token in tokenizer.find_iter(string(run, "text")) {
                let mut token = token.as_str().to_owned();
                let mut token_width = font.bounds(&token)?.advance;
                if !runs.is_empty()
                    && advance + token_width > max_width as f64
                    && !token.trim().is_empty()
                {
                    finish_line(&mut lines, &mut runs);
                    advance = 0.;
                }
                if token_width > max_width as f64 {
                    let mut fragment = String::new();
                    for ch in token.chars() {
                        let next = format!("{fragment}{ch}");
                        if !fragment.is_empty()
                            && advance + font.bounds(&next)?.advance > max_width as f64
                        {
                            runs.push(Run {
                                text: std::mem::take(&mut fragment),
                                font: id.clone(),
                                size,
                                underline: boolean(run, "underline"),
                            });
                            finish_line(&mut lines, &mut runs);
                            advance = 0.;
                        }
                        fragment.push(ch);
                    }
                    token = fragment;
                    token_width = font.bounds(&token)?.advance;
                }
                if !token.is_empty() {
                    runs.push(Run {
                        text: token,
                        font: id.clone(),
                        size,
                        underline: boolean(run, "underline"),
                    });
                    advance += token_width;
                }
            }
        }
        finish_line(&mut lines, &mut runs);
        advance = 0.;
    }
    let mut layouts = Vec::new();
    for runs in lines {
        let (mut ascent, mut descent) = if runs.is_empty() {
            fallback_metrics
        } else {
            (0, 0)
        };
        let (mut x, mut left, mut right) = (0f64, 0f64, 0f64);
        for run in &runs {
            let font = fonts.get(&run.font, run.size)?;
            ascent = ascent.max(font.ascent);
            descent = descent.max(font.descent);
            let b = font.bounds(&run.text)?;
            left = left.min(x + b.left as f64);
            right = right.max(x + b.right as f64);
            x += b.advance;
        }
        let ink_width = (right.max(x) - left).ceil() as i64;
        ensure!(
            ink_width <= max_width,
            "Text exceeds the label width. Reduce the selected text size or margins."
        );
        layouts.push(TextLine {
            runs,
            ascent,
            descent,
            left: left.floor() as i64,
            width: ink_width,
        });
    }
    ensure!(!layouts.is_empty(), "Use at least one text paragraph.");
    let width = if width > 0 {
        width
    } else {
        layouts.iter().map(|l| l.width).max().unwrap_or(1).max(1)
    };
    let spacing = number(draft, "lineSpacing", 100) as f64 / 100.;
    let advances: Vec<i64> = layouts
        .iter()
        .map(|l| ((l.ascent + l.descent) as f64 * spacing).ceil() as i64)
        .collect();
    let last = layouts.last().unwrap();
    let actual_height =
        advances[..advances.len() - 1].iter().sum::<i64>() + last.ascent + last.descent;
    ensure!(
        actual_height <= if height > 0 { height } else { 11000 },
        "Text exceeds the label height. Reduce text size, text, or margins."
    );
    let mut image = canvas(width, actual_height)?;
    let mut y = 0;
    for (i, line) in layouts.iter().enumerate() {
        let mut x = match string(draft, "align") {
            "left" => 0.,
            "right" => (width - line.width) as f64,
            _ => (width - line.width) as f64 / 2.,
        } - line.left as f64;
        for run in &line.runs {
            let font = fonts.get(&run.font, run.size)?;
            font.draw(
                &mut image,
                &run.text,
                x,
                (y + line.ascent) as f64,
                color(draft),
            )?;
            let length = font.bounds(&run.text)?.advance;
            if run.underline && !run.text.is_empty() {
                let thickness = (run.size as f64 / 16.).round_ties_even().max(1.) as i64;
                let baseline =
                    (y + line.ascent + (run.size as f64 / 12.).round_ties_even().max(1.) as i64)
                        .min(y + line.ascent + line.descent - thickness);
                fill_rect(
                    &mut image,
                    x as i64,
                    baseline,
                    (x + length) as i64,
                    baseline + thickness - 1,
                    color(draft),
                );
            }
            x += length;
        }
        y += advances[i];
    }
    Ok(image)
}
fn fill_rect(image: &mut RgbImage, x0: i64, y0: i64, x1: i64, y1: i64, color: Rgb<u8>) {
    for y in y0.max(0)..=y1.min(image.height() as i64 - 1) {
        for x in x0.max(0)..=x1.min(image.width() as i64 - 1) {
            image.put_pixel(x as u32, y as u32, color);
        }
    }
}
fn ink_vertical(image: &RgbImage) -> Option<(u32, u32)> {
    let mut top = image.height();
    let mut bottom = 0;
    for (x, y, pixel) in image.enumerate_pixels() {
        let _ = x;
        if *pixel != WHITE {
            top = top.min(y);
            bottom = bottom.max(y + 1);
        }
    }
    (bottom > top).then_some((top, bottom))
}
struct LegacyText {
    lines: Vec<String>,
    bounds: Vec<Bounds>,
    ys: Vec<i64>,
    width: i64,
    height: i64,
}
fn legacy_layout(text: &str, font: &Font, spacing: i64) -> Result<LegacyText> {
    let lines: Vec<String> = text.lines().map(str::to_owned).collect();
    let mut bounds = Vec::new();
    let mut ys = Vec::new();
    let mut y = 0;
    let all = (33u8..=126).map(char::from).collect::<String>();
    let full = font.bounds(&all)?;
    for (index, line) in lines.iter().enumerate() {
        let b = font.bounds(line)?;
        let height = if index + 1 < lines.len() {
            full.bottom - full.top
        } else {
            b.bottom - b.top
        };
        bounds.push(b);
        ys.push(y);
        y += height;
        if index + 1 < lines.len() {
            y += (font.size as f64 * (spacing - 100) as f64 / 100.) as i64;
        }
    }
    Ok(LegacyText {
        width: bounds.iter().map(|b| b.right).max().unwrap_or(0),
        height: y,
        lines,
        bounds,
        ys,
    })
}
fn draw_legacy(
    image: &mut RgbImage,
    text: &LegacyText,
    font: &Font,
    draft: &Value,
    x: f64,
    y: f64,
) -> Result<()> {
    let left = text.bounds.iter().map(|b| b.left).min().unwrap_or(0);
    let right = text.bounds.iter().map(|b| b.right).max().unwrap_or(0);
    for (i, line) in text.lines.iter().enumerate() {
        let b = text.bounds[i];
        let xx = match string(draft, "align") {
            "left" => x + left as f64,
            "right" => x + right as f64 - b.advance.round(),
            _ => x + ((right - left).div_euclid(2) + left) as f64 - (b.advance / 2.).round(),
        };
        font.draw(
            image,
            line,
            xx,
            y + text.ys[i] as f64 - b.top as f64,
            color(draft),
        )?;
    }
    Ok(())
}

/// Native print raster; preview applies the same display rotation as the prior server.
pub fn render(draft: &Value, registry: &Fonts, preview: bool) -> Result<RgbImage> {
    let geometry = geometry(draft)?;
    let [left, right, top, bottom] = margins(draft);
    let mut fonts = FontCache::new(registry)?;
    let kind = string(&draft["content"], "kind");
    let flow = kind == "text"
        && (draft["content"].get("paragraphs").is_some()
            || ["verticalAlign", "lineSpacing", "margins"]
                .iter()
                .any(|k| draft.get(k).is_some()));
    let mut image = if flow {
        ensure!(
            (geometry.width == 0 || geometry.width as i64 > left + right)
                && (geometry.height == 0 || geometry.height as i64 > top + bottom),
            "Margins leave no printable text area."
        );
        let mut content = rich_text(
            draft,
            &mut fonts,
            if geometry.width > 0 {
                geometry.width as i64 - left - right
            } else {
                0
            },
            if geometry.height > 0 {
                geometry.height as i64 - top - bottom
            } else {
                0
            },
        )?;
        if !geometry.continuous && draft.get("verticalAlign").is_some() {
            let available = geometry.height as i64 - top - bottom;
            if let Some((y0, y1)) = ink_vertical(&content) {
                content = imageops::crop_imm(&content, 0, y0, content.width(), y1 - y0).to_image();
            }
            let offset = match string(draft, "verticalAlign") {
                "top" => 0,
                "bottom" => available - content.height() as i64,
                _ => (available - content.height() as i64).div_euclid(2),
            };
            let mut aligned = canvas(content.width() as i64, available)?;
            imageops::overlay(&mut aligned, &content, 0, offset);
            content = aligned;
        }
        compose(draft, geometry, Some(content), None, &mut fonts, false)?
    } else {
        let content = match kind {
            "text" => None,
            "qr" => Some(qr(draft)?),
            "barcode" => Some(barcode(draft, geometry)?),
            "image" => Some(label_image(draft)?),
            _ => bail!("Invalid content type."),
        };
        let text = if kind == "text" {
            string(&draft["content"], "text")
        } else {
            string(&draft["content"], "caption")
        };
        let fit = kind == "qr" || (kind == "image" && boolean(&draft["content"], "fit"));
        compose(draft, geometry, content, Some(text), &mut fonts, fit)?
    };
    if preview
        && ((geometry.rotated && geometry.continuous)
            || (!geometry.rotated && !geometry.continuous))
    {
        image = imageops::rotate90(&image);
    }
    Ok(image)
}
fn compose(
    draft: &Value,
    g: Geometry,
    mut content: Option<RgbImage>,
    text: Option<&str>,
    fonts: &mut FontCache,
    fit: bool,
) -> Result<RgbImage> {
    let [left, right, top, bottom] = margins(draft);
    if let Some(image) = content.as_mut()
        && fit
    {
        let max_w = (g.width as i64 - left - right).max(1) as f64;
        let max_h = (g.height as i64 - top - bottom).max(1) as f64;
        let scale = if g.continuous {
            if g.rotated {
                max_h / image.height() as f64
            } else {
                max_w / image.width() as f64
            }
        } else {
            (max_w / image.width() as f64).min(max_h / image.height() as f64)
        };
        let (w, h) = (
            (image.width() as f64 * scale) as i64,
            (image.height() as f64 * scale) as i64,
        );
        let _ = canvas(w, h)?;
        let monochrome = string(&draft["content"], "kind") == "qr"
            && string(draft, "color") != "red"
            || string(&draft["content"], "kind") == "image"
                && (string(&draft["content"], "mode") == "bw"
                    || string(&draft["content"], "mode") == "red"
                        && string(&draft["content"]["image"], "mime") == "application/pdf");
        *image = if monochrome {
            imageops::resize(
                image,
                w.max(1) as u32,
                h.max(1) as u32,
                imageops::FilterType::Nearest,
            )
        } else {
            resize_lanczos(image, w.max(1) as u32, h.max(1) as u32)
        };
    }
    let (iw, ih) = content
        .as_ref()
        .map(|i| (i.width() as i64, i.height() as i64))
        .unwrap_or((0, 0));
    let want_text = text.is_some_and(|s| content.is_none() || !s.trim().is_empty());
    let font = fonts.get(string(draft, "font"), number(draft, "fontSize", 40) as u32)?;
    let layout = legacy_layout(
        if want_text { text.unwrap_or("") } else { "" },
        font,
        number(draft, "lineSpacing", 100),
    )?;
    let (mut width, mut height) = (g.width as i64, g.height as i64);
    if g.continuous {
        if g.rotated {
            width = iw + layout.width + left + right;
        } else {
            height = ih + layout.height + top + bottom;
        }
    }
    let need_distance = string(&draft["content"], "kind") != "text";
    let (tx, ty, ix, iy) = if !g.rotated {
        let ty = if !g.continuous {
            ((height - ih - layout.height).div_euclid(2) + (top - bottom).div_euclid(2)) as f64
        } else if need_distance {
            top as f64 * 1.25
        } else {
            top as f64
        };
        (
            (left + (width - left - right - layout.width).div_euclid(2)).max(0) as f64,
            ty + ih as f64,
            left + (width - left - right - iw).div_euclid(2),
            top,
        )
    } else {
        let tx = if !g.continuous {
            (width - iw - layout.width).div_euclid(2).max(0) as f64
        } else if need_distance {
            left as f64 * 1.25
        } else {
            left as f64
        };
        (
            tx + iw as f64,
            ((height - layout.height).div_euclid(2) + (top - bottom).div_euclid(2)) as f64,
            left,
            top + (height - top - bottom - ih).div_euclid(2),
        )
    };
    let mut output = canvas(width, height)?;
    if let Some(image) = content {
        imageops::overlay(&mut output, &image, ix, iy);
    }
    if want_text {
        draw_legacy(&mut output, &layout, font, draft, tx, ty)?;
    }
    Ok(output)
}
// Separable Lanczos uses fixed-point coefficients and clips between passes, preserving
// the 8-bit Pillow raster behavior used by existing saved image labels.
fn resize_lanczos(source: &RgbImage, width: u32, height: u32) -> RgbImage {
    const PRECISION: i64 = 1 << 22;
    fn weights(input: u32, output: u32) -> Vec<(u32, Vec<i64>)> {
        let scale = input as f64 / output as f64;
        let filter_scale = scale.max(1.);
        (0..output)
            .map(|position| {
                let center = (position as f64 + 0.5) * scale;
                let first = ((center - 3. * filter_scale + 0.5) as i64).max(0) as u32;
                let end = ((center + 3. * filter_scale + 0.5) as u32).min(input);
                let mut coefficients: Vec<f64> = (first..end)
                    .map(|x| {
                        let x = (x as f64 - center + 0.5) / filter_scale;
                        if x == 0. {
                            1.
                        } else if x.abs() >= 3. {
                            0.
                        } else {
                            let a = x * std::f64::consts::PI;
                            (a.sin() / a) * ((a / 3.).sin() / (a / 3.))
                        }
                    })
                    .collect();
                let sum: f64 = coefficients.iter().sum();
                for coefficient in &mut coefficients {
                    *coefficient /= sum;
                }
                (
                    first,
                    coefficients
                        .into_iter()
                        .map(|c| (c * PRECISION as f64).round() as i64)
                        .collect(),
                )
            })
            .collect()
    }
    let horizontal = if width == source.width() {
        source.clone()
    } else {
        let weights = weights(source.width(), width);
        let mut output = RgbImage::new(width, source.height());
        for (x, y, pixel) in output.enumerate_pixels_mut() {
            let (first, coefficients) = &weights[x as usize];
            for channel in 0..3 {
                let sum = PRECISION / 2
                    + coefficients
                        .iter()
                        .enumerate()
                        .map(|(i, c)| source.get_pixel(first + i as u32, y)[channel] as i64 * c)
                        .sum::<i64>();
                pixel[channel] = (sum >> 22).clamp(0, 255) as u8;
            }
        }
        output
    };
    if height == source.height() {
        return horizontal;
    }
    let weights = weights(source.height(), height);
    let mut output = RgbImage::new(width, height);
    for (x, y, pixel) in output.enumerate_pixels_mut() {
        let (first, coefficients) = &weights[y as usize];
        for channel in 0..3 {
            let sum = PRECISION / 2
                + coefficients
                    .iter()
                    .enumerate()
                    .map(|(i, c)| horizontal.get_pixel(x, first + i as u32)[channel] as i64 * c)
                    .sum::<i64>();
            pixel[channel] = (sum >> 22).clamp(0, 255) as u8;
        }
    }
    output
}

fn qr(draft: &Value) -> Result<RgbImage> {
    let code = qrcode::QrCode::with_error_correction_level(
        string(&draft["content"], "code").trim().as_bytes(),
        qrcode::EcLevel::L,
    )?;
    let width = code.width() as u32;
    let mut image = canvas(((width + 8) * 10) as i64, ((width + 8) * 10) as i64)?;
    for y in 0..width {
        for x in 0..width {
            if code[(x as usize, y as usize)] == qrcode::Color::Dark {
                fill_rect(
                    &mut image,
                    ((x + 4) * 10) as i64,
                    ((y + 4) * 10) as i64,
                    ((x + 5) * 10 - 1) as i64,
                    ((y + 5) * 10 - 1) as i64,
                    color(draft),
                );
            }
        }
    }
    Ok(image)
}
fn barcode(draft: &Value, g: Geometry) -> Result<RgbImage> {
    use barcoders::sym::{code128::Code128, ean8::EAN8, ean13::EAN13};
    let value = string(&draft["content"], "code").trim();
    let format = string(&draft["content"], "format");
    ensure!(
        !value.is_empty() && value.len() <= 80 && value.bytes().all(|b| (32..=126).contains(&b)),
        "Barcode supports printable ASCII text and numbers."
    );
    if format != "code128" {
        ensure!(
            value.bytes().all(|b| b.is_ascii_digit()),
            "Barcode requires digits."
        );
    }

    let (modules, human) = match format {
        "code128" => {
            let encoded = code128_input(value);
            (Code128::new(encoded)?.encode(), value.to_owned())
        }
        "ean13" => {
            let data = &value[..12.min(value.len())];
            (EAN13::new(data)?.encode(), with_check_digit(data))
        }
        "ean8" => {
            let data = &value[..7.min(value.len())];
            (EAN8::new(data)?.encode(), with_check_digit(data))
        }
        "upca" => {
            let data = &value[..11.min(value.len())];
            let ean = format!("0{data}");
            (EAN13::new(&ean)?.encode(), with_check_digit(data))
        }
        _ => bail!("Unknown barcode type."),
    };
    let [left, right, _, _] = margins(draft);
    let available = if g.continuous && g.rotated {
        1200
    } else {
        g.width as i64 - left - right
    };
    let pixels = (available / (modules.len() as i64 + 20)).min(3);
    ensure!(
        pixels >= 2,
        "Barcode is too wide for this label. Use a shorter value, wider paper, or change orientation."
    );
    let module_mm = pixels as f64 * 25.4 / 300.;
    let quiet_mm = module_mm * 10.;
    let width = ((2. * quiet_mm + modules.len() as f64 * module_mm) * 300. / 25.4) as i64;
    let height = ((10. + 8. * 25.4 / 72. / 2. + 5.) * 300. / 25.4) as i64;
    let mut image = canvas(width, height)?;
    let mut xpos = quiet_mm;
    let mut i = 0;
    while i < modules.len() {
        let value = modules[i];
        let start = i;
        while i < modules.len() && modules[i] == value {
            i += 1;
        }
        let width = (i - start) as f64 * module_mm;
        if value == 1 {
            fill_rect(
                &mut image,
                (xpos * 300. / 25.4) as i64,
                11,
                ((xpos + width) * 300. / 25.4 - 1.) as i64,
                106,
                Rgb([0, 0, 0]),
            );
        }
        xpos += width;
    }
    let library = Library::init()?;
    let face =
        library.new_memory_face(include_bytes!("../assets/DejaVuSansMono.ttf").to_vec(), 0)?;
    let font = Font::from_face(face, 33, &[])?;
    let b = font.bounds(&human)?;
    // python-barcode's default ImageWriter places its human-readable value at 14 mm, anchor md.
    font.draw(
        &mut image,
        &human,
        ((quiet_mm + xpos) / 2. * 300. / 25.4) - (b.advance / 2.).round(),
        (14. * 300. / 25.4) - font.descent as f64,
        Rgb([0, 0, 0]),
    )?;
    Ok(image)
}
fn with_check_digit(data: &str) -> String {
    let sum: u32 = data
        .bytes()
        .rev()
        .enumerate()
        .map(|(i, b)| (b - b'0') as u32 * if i % 2 == 0 { 3 } else { 1 })
        .sum();
    format!("{data}{}", (10 - sum % 10) % 10)
}
fn code128_input(value: &str) -> String {
    let bytes = value.as_bytes();
    let mut out = String::new();
    let mut i = 0;
    let mut c = false;
    // Start C only when the first numeric run has at least four digits; otherwise B.
    while i < bytes.len() {
        let n = bytes[i..].iter().take_while(|b| b.is_ascii_digit()).count();
        if n >= 4 || (c && n >= 2) {
            if !c {
                out.push('Ć');
                c = true;
            }
            let pairs = n / 2 * 2;
            out.push_str(&value[i..i + pairs]);
            i += pairs;
        } else {
            if c || out.is_empty() {
                out.push('Ɓ');
                c = false;
            }
            out.push(bytes[i] as char);
            i += 1;
        }
    }
    out
}

pub fn decode_image(bytes: &[u8], mime: &str) -> Result<RgbImage> {
    decode_image_with_dpi(bytes, mime, 300)
}

pub fn decode_image_with_dpi(bytes: &[u8], mime: &str, dpi: u32) -> Result<RgbImage> {
    decode_image_options(bytes, mime, dpi, None)
}

/// Rasterize vector PDFs at the destination label scale without allocating a full page at 600 dpi.
pub fn decode_image_for_label(
    bytes: &[u8],
    mime: &str,
    dpi: u32,
    max_dimension: u32,
) -> Result<RgbImage> {
    if mime != "application/pdf" {
        return decode_image(bytes, mime);
    }
    ensure!(
        max_dimension > 0 && u64::from(max_dimension).pow(2) <= MAX_PIXELS,
        "PDF label dimensions exceed the render limit."
    );
    decode_image_options(bytes, mime, dpi, Some(max_dimension))
}

fn decode_image_options(
    bytes: &[u8],
    mime: &str,
    dpi: u32,
    max_dimension: Option<u32>,
) -> Result<RgbImage> {
    let bytes = if mime == "application/pdf" {
        ensure!(
            matches!(dpi, 300 | 600),
            "PDF resolution must be 300 or 600 dpi."
        );
        let directory = tempfile::tempdir()?;
        let input = directory.path().join("input.pdf");
        let output = directory.path().join("page");
        std::fs::write(&input, bytes)?;
        let mut command = Command::new("pdftoppm");
        command
            .args(["-f", "1", "-l", "1", "-r"])
            .arg(dpi.to_string())
            .args(["-singlefile", "-png"]);
        if let Some(max_dimension) = max_dimension {
            command.arg("-scale-to").arg(max_dimension.to_string());
        }
        command.arg(&input).arg(&output);
        command
            .stdout(std::process::Stdio::null())
            .stderr(std::process::Stdio::null());
        #[cfg(unix)]
        {
            use std::os::unix::process::CommandExt;
            // Poppler is a separate native process: bound its work and output as well as the decoded image.
            unsafe {
                command.pre_exec(|| {
                    let cpu = libc::rlimit {
                        rlim_cur: 20,
                        rlim_max: 21,
                    };
                    let output = libc::rlimit {
                        rlim_cur: 64 * 1024 * 1024,
                        rlim_max: 64 * 1024 * 1024,
                    };
                    if libc::setrlimit(libc::RLIMIT_CPU, &cpu) != 0
                        || libc::setrlimit(libc::RLIMIT_FSIZE, &output) != 0
                    {
                        return Err(std::io::Error::last_os_error());
                    }
                    #[cfg(target_os = "linux")]
                    {
                        let memory = libc::rlimit {
                            rlim_cur: 512 * 1024 * 1024,
                            rlim_max: 512 * 1024 * 1024,
                        };
                        if libc::setrlimit(libc::RLIMIT_AS, &memory) != 0 {
                            return Err(std::io::Error::last_os_error());
                        }
                    }
                    Ok(())
                });
            }
        }
        let mut child = command
            .spawn()
            .context("PDF previews require Poppler (pdftoppm).")?;
        let deadline = std::time::Instant::now() + std::time::Duration::from_secs(20);
        loop {
            if let Some(status) = child.try_wait()? {
                ensure!(status.success(), "Unable to render the first PDF page.");
                break;
            }
            if std::time::Instant::now() > deadline {
                let _ = child.kill();
                let _ = child.wait();
                bail!("PDF rendering took too long.");
            }
            std::thread::sleep(std::time::Duration::from_millis(25));
        }
        std::fs::read(output.with_extension("png"))?
    } else {
        bytes.to_vec()
    };
    let mut reader = image::ImageReader::new(Cursor::new(bytes)).with_guessed_format()?;
    let mut limits = image::Limits::default();
    limits.max_image_width = Some(11000);
    limits.max_image_height = Some(11000);
    limits.max_alloc = Some(128 * 1024 * 1024);
    reader.limits(limits);
    let image = reader.decode()?;
    ensure!(
        image.width() as u64 * image.height() as u64 <= MAX_PIXELS,
        "Image has too many pixels."
    );
    Ok(image.to_rgb8())
}
fn label_image(draft: &Value) -> Result<RgbImage> {
    let content = &draft["content"];
    let bytes =
        base64::engine::general_purpose::STANDARD.decode(string(&content["image"], "base64"))?;
    let mime = string(&content["image"], "mime");
    let mut image = decode_image(&bytes, mime)?;
    for pixel in image.pixels_mut() {
        let gray =
            ((pixel[0] as u32 * 19595 + pixel[1] as u32 * 38470 + pixel[2] as u32 * 7471 + 32768)
                >> 16) as u8;
        *pixel = match string(content, "mode") {
            "grayscale" => Rgb([gray; 3]),
            "red" if mime != "application/pdf" => {
                if gray < 127 {
                    Rgb([(gray as u32 * 255 / 127) as u8, 0, 0])
                } else {
                    let n = ((gray as u32 - 127) * 255 / 128) as u8;
                    Rgb([255, n, n])
                }
            }
            _ => Rgb([if gray > 70 { 255 } else { 0 }; 3]),
        };
    }
    Ok(image)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn variable_font_axes_match_pillow_weight_rasters() {
        let library = Library::init().unwrap();
        for (weight, expected_ink) in [(100., 57120), (400., 250096), (700., 443296)] {
            let face = library
                .new_memory_face(
                    include_bytes!("../tests/fixtures/rendering/variable.ttf").to_vec(),
                    0,
                )
                .unwrap();
            let font = Font::from_face(face, 80, &[weight]).unwrap();
            let mut image = canvas(100, 100).unwrap();
            font.draw(&mut image, "A", 0., 80., Rgb([0; 3])).unwrap();
            let ink: u32 = image.pixels().map(|p| 255 - p[0] as u32).sum();
            assert_eq!(ink, expected_ink, "weight {weight}");
        }
    }
    fn vector_pdf(width: u32, height: u32, content: &str) -> Vec<u8> {
        let objects = [
            "<< /Type /Catalog /Pages 2 0 R >>".to_owned(),
            "<< /Type /Pages /Kids [3 0 R] /Count 1 >>".to_owned(),
            format!(
                "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {width} {height}] /Resources << >> /Contents 4 0 R >>"
            ),
            format!(
                "<< /Length {} >>\nstream\n{content}endstream",
                content.len()
            ),
        ];
        let mut pdf = b"%PDF-1.4\n".to_vec();
        let mut offsets = Vec::new();
        for (index, object) in objects.iter().enumerate() {
            offsets.push(pdf.len());
            pdf.extend_from_slice(format!("{} 0 obj\n{object}\nendobj\n", index + 1).as_bytes());
        }
        let xref = pdf.len();
        pdf.extend_from_slice(b"xref\n0 5\n0000000000 65535 f \n");
        for offset in offsets {
            pdf.extend_from_slice(format!("{offset:010} 00000 n \n").as_bytes());
        }
        pdf.extend_from_slice(
            format!("trailer\n<< /Size 5 /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n").as_bytes(),
        );
        pdf
    }

    #[test]
    fn pdf_high_resolution_preserves_native_vector_detail() {
        let pdf = vector_pdf(72, 36, "0 g 36 5 0.12 26 re f 36.24 5 0.12 26 re f\n");
        let normal = decode_image(&pdf, "application/pdf").unwrap();
        let high = decode_image_with_dpi(&pdf, "application/pdf", 600).unwrap();
        assert_eq!(normal.dimensions(), (300, 150));
        assert_eq!(high.dimensions(), (600, 300));
        assert!(normal.get_pixel(150, 75)[0] < 128 && normal.get_pixel(151, 75)[0] < 128);
        assert!(high.get_pixel(300, 150)[0] < 128 && high.get_pixel(302, 150)[0] < 128);
        assert!(
            high.get_pixel(301, 150)[0] > 200,
            "600 dpi must resolve the white gap between fine strokes"
        );
        // Separate vector strokes remain distinct at 600 dpi instead of enlarging the 300 dpi bitmap.
        assert_ne!(
            high,
            imageops::resize(&normal, 600, 300, imageops::FilterType::Nearest)
        );
    }
    #[test]
    fn letter_pdf_is_bounded_to_label_resolution_without_losing_vector_detail() {
        let pdf = vector_pdf(612, 792, "0 g 396 20 0.4 752 re f 396.8 20 0.4 752 re f\n");
        assert!(
            decode_image_with_dpi(&pdf, "application/pdf", 600).is_err(),
            "A full Letter page at 600 dpi exceeds the 16 MP limit"
        );
        let continuous = decode_image_for_label(&pdf, "application/pdf", 600, 1392).unwrap();
        let fixed = decode_image_for_label(&pdf, "application/pdf", 600, 1982).unwrap();
        assert_eq!(continuous.dimensions(), (1076, 1392));
        assert_eq!(fixed.dimensions(), (1532, 1982));
        assert!(fixed.get_pixel(991, 991)[0] < 128 && fixed.get_pixel(993, 991)[0] < 128);
        assert!(
            fixed.get_pixel(992, 991)[0] > 200,
            "Direct vector rasterization must retain the white gap between fine strokes"
        );
        assert!(decode_image_for_label(&pdf, "application/pdf", 600, 4001).is_err());
    }
}
