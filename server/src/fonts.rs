//! Installed font catalog and original variable font files shared by preview and browser.
use crate::config::Config;
use anyhow::{Context, Result, bail, ensure};
use fs2::FileExt;
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::{
    collections::{BTreeMap, HashMap},
    fs,
    io::{Read, Write},
    path::{Path, PathBuf},
    time::Duration,
};
use ttf_parser::{Face, Tag};
use walkdir::WalkDir;

const FONT_LIMIT: usize = 8 * 1024 * 1024;
const WEIGHTS: [(u16, &str); 9] = [
    (100, "Thin"),
    (200, "ExtraLight"),
    (300, "Light"),
    (400, "Regular"),
    (500, "Medium"),
    (600, "SemiBold"),
    (700, "Bold"),
    (800, "ExtraBold"),
    (900, "Black"),
];

#[derive(Clone, Debug)]
pub struct FontFace {
    pub path: PathBuf,
    pub axes: Vec<f32>,
    pub weight: u16,
    pub italic: bool,
}
#[derive(Clone, Debug)]
pub struct Fonts {
    faces: BTreeMap<String, FontFace>,
    aliases: HashMap<String, String>,
    default: String,
}
#[derive(Debug, Clone, Serialize, Deserialize)]
struct ManifestFace {
    family: String,
    style: String,
    file: String,
    axes: Vec<f32>,
    weight: u16,
    italic: bool,
}

fn name(face: &Face<'_>, id: u16) -> Option<String> {
    face.names()
        .into_iter()
        .filter(|n| n.name_id == id)
        .find_map(|n| n.to_string())
}
fn valid_name(family: &str, style: &str) -> bool {
    !family.is_empty()
        && !style.is_empty()
        && !family.contains(',')
        && family.len() + style.len() < 200
}
fn basic_face(path: &Path) -> Result<(String, FontFace)> {
    let data = fs::read(path)?;
    let face = Face::parse(&data, 0)?;
    let family = name(&face, 1).context("Font has no family name")?;
    let style = name(&face, 2).context("Font has no style name")?;
    ensure!(valid_name(&family, &style), "Invalid font names");
    let lower = style.to_lowercase();
    // Keep historical metadata for unmanaged fonts so rich-text face selection is stable.
    Ok((
        format!("{family},{style}"),
        FontFace {
            path: path.to_owned(),
            axes: vec![],
            weight: if lower.contains("bold") { 700 } else { 400 },
            italic: lower.contains("italic") || lower.contains("oblique"),
        },
    ))
}
impl Fonts {
    pub fn load(config: &Config) -> Result<Self> {
        let mut roots: Vec<PathBuf> = [
            "/usr/share/fonts",
            "/usr/local/share/fonts",
            "/Library/Fonts",
            "/System/Library/Fonts",
            "C:\\Windows\\Fonts",
        ]
        .into_iter()
        .map(PathBuf::from)
        .collect();
        if let Some(home) = std::env::var_os("HOME") {
            roots.push(PathBuf::from(&home).join(".fonts"));
            roots.push(PathBuf::from(home).join(".local/share/fonts"));
        }
        if let Some(path) = &config.font_folder {
            roots.push(path.clone());
        }
        Self::load_roots(config, &roots)
    }
    fn load_roots(config: &Config, roots: &[PathBuf]) -> Result<Self> {
        let mut families: BTreeMap<String, BTreeMap<String, FontFace>> = BTreeMap::new();
        for root in roots {
            for entry in WalkDir::new(root)
                .sort_by_file_name()
                .into_iter()
                .filter_map(Result::ok)
            {
                let path = entry.path();
                if !entry.file_type().is_file()
                    || !path.extension().is_some_and(|ext| {
                        ext.eq_ignore_ascii_case("ttf") || ext.eq_ignore_ascii_case("otf")
                    })
                {
                    continue;
                }
                if let Ok((id, face)) = basic_face(path) {
                    let (family, style) = id.split_once(',').unwrap();
                    families
                        .entry(family.to_owned())
                        .or_default()
                        .insert(style.to_owned(), face);
                }
            }
        }
        let mut names: Vec<_> = families.keys().cloned().collect();
        names.sort_by_key(|s| s.to_lowercase());
        for family in &names {
            if !families.contains_key(family) {
                continue;
            }
            for other in &names {
                if other == family || !other.contains(family.as_str()) {
                    continue;
                }
                if let Some(styles) = families.remove(other) {
                    let extra = other.replace(&format!("{family} "), "");
                    for (style, face) in styles {
                        let new_style = if style == "Regular" {
                            extra.clone()
                        } else {
                            format!("{extra} / {style}")
                        };
                        families.get_mut(family).unwrap().insert(new_style, face);
                    }
                }
            }
        }
        let mut faces: BTreeMap<String, FontFace> = families
            .into_iter()
            .flat_map(|(family, styles)| {
                styles
                    .into_iter()
                    .map(move |(style, face)| (format!("{family},{style}"), face))
            })
            .collect();
        let mut aliases = HashMap::new();
        let directory = config.data_dir.join("fonts");
        if directory.exists() {
            let mut folders: Vec<_> =
                fs::read_dir(&directory)?.collect::<std::io::Result<Vec<_>>>()?;
            folders.sort_by_key(|e| e.file_name());
            for entry in folders {
                if !entry.file_type()?.is_dir()
                    || entry.file_name().to_string_lossy().starts_with('.')
                {
                    continue;
                }
                let folder = entry.path();
                let manifest = folder.join("faces.json");
                if manifest.exists() {
                    let records: Vec<ManifestFace> = serde_json::from_slice(&fs::read(&manifest)?)
                        .with_context(|| format!("Reading {}", manifest.display()))?;
                    for record in records {
                        ensure!(
                            valid_name(&record.family, &record.style),
                            "Invalid installed font name"
                        );
                        ensure!(
                            Path::new(&record.file).components().count() == 1
                                && !record.file.starts_with('.'),
                            "Invalid installed font filename"
                        );
                        let path = folder.join(&record.file);
                        ensure!(
                            path.is_file(),
                            "Installed font is missing: {}",
                            path.display()
                        );
                        faces.insert(
                            format!("{},{}", record.family, record.style),
                            FontFace {
                                path,
                                axes: record.axes,
                                weight: record.weight,
                                italic: record.italic,
                            },
                        );
                    }
                    if folder.join("aliases.json").exists() {
                        aliases.extend(serde_json::from_slice::<HashMap<String, String>>(
                            &fs::read(folder.join("aliases.json"))?,
                        )?);
                    }
                } else if folder.join("font.ttf").exists() {
                    let (id, face) = basic_face(&folder.join("font.ttf"))?;
                    faces.insert(id, face);
                }
            }
        }
        ensure!(
            !faces.is_empty(),
            "No fonts installed. Install DejaVu fonts or configure a font folder."
        );
        let preferred = config.defaults["font"]
            .as_str()
            .unwrap_or("DejaVu Serif,Book");
        let preferred = aliases
            .get(preferred)
            .map(String::as_str)
            .unwrap_or(preferred);
        let default = if faces.contains_key(preferred) {
            preferred.to_owned()
        } else {
            let mut ids: Vec<_> = faces.keys().collect();
            ids.sort_by_key(|id| {
                let (family, style) = id.split_once(',').unwrap();
                (family.to_lowercase(), style.to_owned())
            });
            ids[0].clone()
        };
        Ok(Self {
            faces,
            aliases,
            default,
        })
    }
    pub fn get(&self, id: &str) -> Result<&FontFace> {
        self.faces
            .get(&self.canonical(id))
            .context("Choose an installed font.")
    }
    pub fn canonical(&self, id: &str) -> String {
        self.aliases
            .get(id)
            .cloned()
            .unwrap_or_else(|| id.to_owned())
    }
    pub fn default_font(&self) -> String {
        self.default.clone()
    }
    pub fn styled(&self, id: &str, bold: bool, italic: bool) -> Result<String> {
        let id = self.canonical(id);
        let base = self.get(&id)?;
        if !bold && !italic {
            return Ok(id);
        }
        let (family, _) = id.split_once(',').context("Invalid font name")?;
        let weight = if bold { 700 } else { base.weight };
        let slanted = italic || base.italic;
        let (selected, face) = self
            .faces
            .iter()
            .filter(|(key, face)| {
                key.split_once(',').is_some_and(|(f, _)| f == family) && face.italic == slanted
            })
            .min_by_key(|(_, face)| face.weight.abs_diff(weight))
            .with_context(|| format!("{family} has no italic face installed."))?;
        ensure!(
            !bold || face.weight >= 600,
            "{family} has no bold face installed."
        );
        Ok(selected.clone())
    }
    pub fn list(&self) -> Value {
        let mut entries: Vec<_> = self.faces.iter().collect();
        entries.sort_by_key(|(id, _)| id.to_lowercase());
        json!(entries.into_iter().map(|(id, face)| json!({"id":id,"name":id.replace(',', " "),"weight":face.weight,"italic":face.italic})).collect::<Vec<_>>())
    }
}
fn source_catalog() -> Result<Value> {
    Ok(serde_json::from_str(include_str!(
        "../../app/data/google-fonts.json"
    ))?)
}
pub fn catalog(config: &Config) -> Result<Value> {
    let source = source_catalog()?;
    Ok(
        json!({"families": source["families"].as_array().context("Invalid font catalog")?.iter().map(|family| {
        let id = family["id"].as_str().unwrap();
        json!({"id":id,"name":family["name"],"installed":config.data_dir.join("fonts").join(format!("google-{}", id.replace('/', "-"))).join("source.json").exists()})
    }).collect::<Vec<_>>()}),
    )
}
fn inspect_faces(
    data: &[u8],
    filename: &str,
    family_override: Option<&str>,
) -> Result<Vec<ManifestFace>> {
    let face =
        Face::parse(data, 0).context("Choose a valid TTF or OTF font with printable outlines.")?;
    let family = family_override
        .map(str::to_owned)
        .or_else(|| name(&face, 16))
        .or_else(|| name(&face, 1))
        .context("Missing font family")?;
    let style = name(&face, 17)
        .or_else(|| name(&face, 2))
        .context("Missing font style")?;
    ensure!(valid_name(&family, &style), "Invalid font names");
    let axes = face.variation_axes();
    let weight_axis = axes
        .into_iter()
        .find(|axis| axis.tag == Tag::from_bytes(b"wght"));
    let weights: Vec<_> = if let Some(axis) = weight_axis {
        WEIGHTS
            .iter()
            .map(|(weight, _)| *weight)
            .filter(|weight| axis.min_value <= *weight as f32 && *weight as f32 <= axis.max_value)
            .collect()
    } else {
        vec![face.weight().to_number()]
    };
    let intrinsic_italic = face.is_italic()
        || style.to_lowercase().contains("italic")
        || style.to_lowercase().contains("oblique");
    let variable_italic = axes
        .into_iter()
        .any(|axis| axis.tag == Tag::from_bytes(b"ital") || axis.tag == Tag::from_bytes(b"slnt"));
    let italic_values = if variable_italic {
        vec![false, true]
    } else {
        vec![intrinsic_italic]
    };
    let mut records = Vec::new();
    for weight in weights {
        for &italic in &italic_values {
            let coordinates = axes
                .into_iter()
                .map(|axis| {
                    let value = match &axis.tag.to_bytes() {
                        b"wght" => weight as f32,
                        b"ital" => u8::from(italic) as f32,
                        b"slnt" => {
                            if italic {
                                -12.0
                            } else {
                                0.0
                            }
                        }
                        _ => axis.def_value,
                    };
                    value.clamp(axis.min_value, axis.max_value)
                })
                .collect();
            let mut name = if axes.is_empty() {
                style.clone()
            } else {
                WEIGHTS
                    .iter()
                    .find(|(w, _)| *w == weight)
                    .map(|(_, name)| name.to_string())
                    .unwrap_or_else(|| style.clone())
            };
            if !axes.is_empty() && italic {
                name = if name == "Regular" {
                    "Italic".to_owned()
                } else {
                    format!("{name} Italic")
                };
            }
            records.push(ManifestFace {
                family: family.clone(),
                style: name,
                file: filename.to_owned(),
                axes: coordinates,
                weight,
                italic,
            });
        }
    }
    ensure!(!records.is_empty(), "Font contains no supported weight");
    // Validate printable outlines with the same engine used by the rasterizer.
    let library = freetype::Library::init()?;
    let mut ft = library.new_memory_face(data.to_vec(), 0)?;
    let regular = records
        .iter()
        .min_by_key(|face| (face.italic, face.weight.abs_diff(400)))
        .unwrap();
    if !regular.axes.is_empty() {
        let coordinates: Vec<freetype::ffi::FT_Fixed> = regular
            .axes
            .iter()
            .map(|value| (*value as f64 * 65536.0).round() as freetype::ffi::FT_Fixed)
            .collect();
        // The face owns the font bytes, and coordinates are live for this synchronous call.
        let error = unsafe {
            freetype::ffi::FT_Set_Var_Design_Coordinates(
                ft.raw_mut(),
                coordinates.len() as u32,
                coordinates.as_ptr(),
            )
        };
        ensure!(error == 0, "Font variation axes cannot be rendered.");
    }
    ft.set_pixel_sizes(0, 30)?;
    for ch in "Label 123".chars() {
        ft.load_char(ch as usize, freetype::face::LoadFlag::RENDER)?;
    }
    Ok(records)
}
fn atomic_write(path: &Path, bytes: &[u8]) -> Result<()> {
    let directory = path.parent().context("Missing destination directory")?;
    let mut temporary = tempfile::NamedTempFile::new_in(directory)?;
    temporary.write_all(bytes)?;
    temporary.as_file().sync_all()?;
    temporary.persist(path)?;
    Ok(())
}
fn installed_result(config: &Config, destination: &Path) -> Result<Value> {
    let records: Vec<ManifestFace> =
        serde_json::from_slice(&fs::read(destination.join("faces.json"))?)?;
    let regular = records
        .iter()
        .min_by_key(|face| (face.italic, face.weight.abs_diff(400)))
        .context("Font has no faces")?;
    Ok(
        json!({"font":format!("{},{}",regular.family,regular.style), "fonts":Fonts::load(config)?.list()}),
    )
}
fn install_files(
    config: &Config,
    directory: &str,
    files: BTreeMap<String, Vec<u8>>,
    extra: BTreeMap<String, Vec<u8>>,
    family_name: Option<&str>,
) -> Result<Value> {
    let records = files
        .iter()
        .map(|(filename, data)| inspect_faces(data, filename, family_name))
        .collect::<Result<Vec<_>>>()?
        .into_iter()
        .flatten()
        .collect::<Vec<_>>();
    ensure!(!records.is_empty(), "No usable font files");
    let root = config.data_dir.join("fonts");
    fs::create_dir_all(&root)?;
    let lock = fs::OpenOptions::new()
        .read(true)
        .write(true)
        .create(true)
        .truncate(false)
        .open(root.join(".install.lock"))?;
    lock.lock_exclusive()?;
    let destination = root.join(directory);
    fs::create_dir_all(&destination)?;
    if family_name.is_some() && destination.join("font.ttf").exists() {
        let (old_name, _) = basic_face(&destination.join("font.ttf"))?;
        let regular = records
            .iter()
            .min_by_key(|face| (face.italic, face.weight.abs_diff(400)))
            .unwrap();
        let new_name = format!("{},{}", regular.family, regular.style);
        if old_name != new_name {
            let aliases_path = destination.join("aliases.json");
            let mut aliases: BTreeMap<String, String> = if aliases_path.exists() {
                serde_json::from_slice(&fs::read(&aliases_path)?)?
            } else {
                BTreeMap::new()
            };
            aliases.insert(old_name, new_name);
            atomic_write(&aliases_path, &serde_json::to_vec(&aliases)?)?;
        }
    }
    for (name, data) in files.into_iter().chain(extra) {
        atomic_write(&destination.join(name), &data)?;
    }
    atomic_write(
        &destination.join("faces.json"),
        &serde_json::to_vec(&records)?,
    )?;
    installed_result(config, &destination)
}
pub fn upload(config: &Config, data: &[u8]) -> Result<Value> {
    ensure!(
        !data.is_empty() && data.len() <= FONT_LIMIT,
        "Font must be no larger than 8 MB."
    );
    let digest = format!("{:x}", Sha256::digest(data));
    install_files(
        config,
        &format!("upload-{digest}"),
        BTreeMap::from([("font.ttf".to_owned(), data.to_vec())]),
        BTreeMap::new(),
        None,
    )
}
fn download(client: &reqwest::blocking::Client, revision: &str, path: &str) -> Result<Vec<u8>> {
    let mut url = url::Url::parse("https://raw.githubusercontent.com/google/fonts/")?;
    url.path_segments_mut()
        .unwrap()
        .pop_if_empty()
        .push(revision)
        .extend(path.split('/'));
    let response = client
        .get(url)
        .send()
        .context("Font download failed. Check the Pi internet connection and try again.")?
        .error_for_status()?;
    let mut data = Vec::new();
    response
        .take(FONT_LIMIT as u64 + 1)
        .read_to_end(&mut data)?;
    ensure!(
        data.len() <= FONT_LIMIT,
        "This font exceeds the 8 MB download limit."
    );
    Ok(data)
}
pub fn install_google(config: &Config, id: &str) -> Result<Value> {
    let source = source_catalog()?;
    let family = source["families"]
        .as_array()
        .context("Invalid font catalog")?
        .iter()
        .find(|family| family["id"] == id)
        .context("Choose a font from the catalog.")?;
    let directory = format!("google-{}", id.replace('/', "-"));
    let destination = config.data_dir.join("fonts").join(&directory);
    if destination.join("faces.json").exists() {
        return installed_result(config, &destination);
    }
    let names: Vec<_> = family["files"]
        .as_array()
        .context("Invalid font files")?
        .iter()
        .filter_map(Value::as_str)
        .collect();
    let ttf: Vec<_> = names
        .iter()
        .copied()
        .filter(|name| name.ends_with(".ttf"))
        .collect();
    let mut selected: Vec<_> = ttf
        .iter()
        .copied()
        .filter(|name| name.contains('['))
        .collect();
    if selected.is_empty() {
        selected = ttf
            .iter()
            .copied()
            .filter(|name| {
                ["Regular", "Bold", "Italic", "BoldItalic"]
                    .iter()
                    .any(|style| name.ends_with(&format!("-{style}.ttf")))
            })
            .collect();
        if selected.is_empty() {
            selected.extend(ttf.first().copied());
        }
    }
    if selected.is_empty() {
        bail!("This family has no supported TTF files.");
    }
    let revision = source["revision"]
        .as_str()
        .context("Invalid catalog revision")?;
    let client = reqwest::blocking::Client::builder()
        .timeout(Duration::from_secs(25))
        .build()?;
    let mut extra = BTreeMap::new();
    for name in names.iter().filter(|name| name.ends_with(".txt")) {
        extra.insert(
            (*name).to_owned(),
            download(&client, revision, &format!("{id}/{name}"))?,
        );
    }
    extra.insert("source.json".to_owned(), serde_json::to_vec(&json!({"family":family["name"],"revision":revision,"files":selected,"nativeVariations":true}))?);
    let mut files = BTreeMap::new();
    for name in selected {
        let data = download(&client, revision, &format!("{id}/{name}"))?;
        files.insert(format!("{:x}.ttf", Sha256::digest(&data)), data);
    }
    install_files(config, &directory, files, extra, family["name"].as_str())
}

#[cfg(test)]
mod tests {
    use super::*;
    fn test_config() -> (tempfile::TempDir, Config) {
        let root = tempfile::tempdir().unwrap();
        let config = Config {
            data_dir: root.path().to_owned(),
            ..Config::default()
        };
        (root, config)
    }
    fn available_font(config: &Config) -> Vec<u8> {
        let fonts =
            Fonts::load(config).expect("Install DejaVu fonts to run font integration tests");
        fs::read(&fonts.get(&fonts.default_font()).unwrap().path).unwrap()
    }
    #[test]
    fn uploaded_original_survives_restart_and_repeat_install() {
        let (_root, config) = test_config();
        let data = available_font(&config);
        let result = upload(&config, &data).unwrap();
        let id = result["font"].as_str().unwrap();
        let restarted = Fonts::load(&config).unwrap();
        let face = restarted.get(id).unwrap();
        assert!(face.path.starts_with(&config.data_dir));
        assert_eq!(fs::read(&face.path).unwrap(), data);
        assert_eq!(upload(&config, &data).unwrap()["font"], id);
        let folders = fs::read_dir(config.data_dir.join("fonts"))
            .unwrap()
            .filter_map(Result::ok)
            .filter(|entry| entry.file_type().unwrap().is_dir())
            .count();
        assert_eq!(folders, 1);
    }
    #[test]
    fn managed_axes_and_legacy_alias_are_preserved() {
        let (_root, config) = test_config();
        let data = available_font(&config);
        let folder = config.data_dir.join("fonts/managed");
        fs::create_dir_all(&folder).unwrap();
        fs::write(folder.join("original.ttf"), data).unwrap();
        fs::write(folder.join("faces.json"), serde_json::to_vec(&json!([
            {"family":"Managed","style":"Regular","file":"original.ttf","axes":[400,0,14],"weight":400,"italic":false},
            {"family":"Managed","style":"Bold Italic","file":"original.ttf","axes":[700,1,14],"weight":700,"italic":true}
        ])).unwrap()).unwrap();
        fs::write(
            folder.join("aliases.json"),
            br#"{"Old Font,Thin":"Managed,Regular"}"#,
        )
        .unwrap();
        let fonts = Fonts::load_roots(&config, &[]).unwrap();
        assert_eq!(
            fonts.get("Old Font,Thin").unwrap().axes,
            vec![400.0, 0.0, 14.0]
        );
        assert_eq!(
            fonts.styled("Old Font,Thin", true, true).unwrap(),
            "Managed,Bold Italic"
        );
        assert!(fonts.styled("Managed,Regular", true, false).is_err());
        assert_eq!(fonts.list().as_array().unwrap().len(), 2);
    }
    #[test]
    fn invalid_uploads_and_catalog_ids_do_not_write_files() {
        let (_root, config) = test_config();
        assert!(upload(&config, b"broken font").is_err());
        assert!(upload(&config, &vec![0; FONT_LIMIT + 1]).is_err());
        assert!(install_google(&config, "../../etc/passwd").is_err());
        assert!(!config.data_dir.join("fonts").exists());
        assert!(
            catalog(&config).unwrap()["families"]
                .as_array()
                .unwrap()
                .len()
                > 1500
        );
    }
    #[test]
    fn damaged_font_offsets_and_truncations_return_errors_without_panicking() {
        let (_root, config) = test_config();
        let original = available_font(&config);
        for length in [0, 1, 4, 11] {
            assert!(upload(&config, &original[..length]).is_err());
        }
        let mut damaged = original.clone();
        // Corrupt all sfnt table offsets while retaining a recognizable font header.
        let count = u16::from_be_bytes([damaged[4], damaged[5]]) as usize;
        for index in 0..count {
            let offset = 12 + index * 16 + 8;
            damaged[offset..offset + 4].copy_from_slice(&u32::MAX.to_be_bytes());
        }
        assert!(upload(&config, &damaged).is_err());
        assert!(!config.data_dir.join("fonts").exists());
    }
    #[test]
    fn invalid_managed_manifest_cannot_escape_its_font_directory() {
        let (_root, config) = test_config();
        let folder = config.data_dir.join("fonts/managed");
        fs::create_dir_all(&folder).unwrap();
        fs::write(folder.join("faces.json"), serde_json::to_vec(&json!([
            {"family":"Managed","style":"Regular","file":"../../outside.ttf","axes":[],"weight":400,"italic":false}
        ])).unwrap()).unwrap();
        assert!(Fonts::load_roots(&config, &[]).is_err());
    }
    #[test]
    fn catalog_installation_marker_is_persistent() {
        let (_root, config) = test_config();
        fs::create_dir_all(config.data_dir.join("fonts/google-ofl-roboto")).unwrap();
        fs::write(
            config.data_dir.join("fonts/google-ofl-roboto/source.json"),
            b"{}",
        )
        .unwrap();
        let catalog = catalog(&config).unwrap();
        let roboto = catalog["families"]
            .as_array()
            .unwrap()
            .iter()
            .find(|family| family["id"] == "ofl/roboto")
            .unwrap();
        assert_eq!(roboto["installed"], true);
    }
    #[test]
    #[ignore = "Downloads the pinned Google Fonts source; run explicitly for integration verification"]
    fn google_variable_font_keeps_regular_weight_and_license() {
        let (_root, config) = test_config();
        let result = install_google(&config, "ofl/roboto").unwrap();
        assert_eq!(result["font"], "Roboto,Regular");
        let fonts = Fonts::load(&config).unwrap();
        let regular = fonts.get("Roboto,Regular").unwrap();
        assert_eq!(regular.weight, 400);
        assert!(regular.axes.contains(&400.0));
        assert_eq!(fonts.get("Roboto,Thin").unwrap().weight, 100);
        assert_eq!(
            fonts.styled("Roboto,Regular", true, true).unwrap(),
            "Roboto,Bold Italic"
        );
        assert!(
            config
                .data_dir
                .join("fonts/google-ofl-roboto/OFL.txt")
                .exists()
        );
        assert_eq!(
            install_google(&config, "ofl/roboto").unwrap()["font"],
            "Roboto,Regular"
        );
    }
}
