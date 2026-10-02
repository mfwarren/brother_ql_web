use label_studio_server::{config::Config, fonts::Fonts, rendering};
use serde_json::{Value, json};
use std::{path::PathBuf, sync::OnceLock};
fn fonts() -> &'static Fonts {
    static FONTS: OnceLock<Fonts> = OnceLock::new();
    FONTS.get_or_init(|| {
        Fonts::load(&Config {
            font_folder: Some(PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("assets")),
            ..Config::default()
        })
        .unwrap()
    })
}
fn mono() -> String {
    fonts()
        .list()
        .as_array()
        .unwrap()
        .iter()
        .find_map(|entry| {
            let id = entry["id"].as_str().unwrap();
            (fonts().get(id).unwrap().path.file_name().unwrap() == "DejaVuSansMono.ttf")
                .then(|| id.to_owned())
        })
        .unwrap()
}
fn draft() -> Value {
    json!({"content":{"kind":"text","text":"Coffee beans"},"font":mono(),"fontSize":31,"sizeId":"62","orientation":"standard","align":"center","color":"black","margin":17,"highRes":false})
}
#[test]
fn legacy_and_formatted_documents_preserve_python_reference_pixels() {
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("tests/fixtures/rendering");
    let drafts: Vec<Value> =
        serde_json::from_slice(&std::fs::read(root.join("drafts.json")).unwrap()).unwrap();
    for (index, mut draft) in drafts.into_iter().enumerate() {
        draft["font"] = mono().into();
        let expected = image::open(root.join(format!("{index}.png")))
            .unwrap()
            .to_rgb8();
        let actual = rendering::render(&draft, fonts(), true).unwrap();
        assert_eq!(actual.dimensions(), expected.dimensions(), "case {index}");
        assert_eq!(
            actual.as_raw(),
            expected.as_raw(),
            "Python reference case {index}"
        );
    }
}
#[test]
fn high_resolution_and_preview_rotation_preserve_paper_geometry() {
    let mut value = draft();
    value["sizeId"] = "29x90".into();
    value["highRes"] = true.into();
    let print = rendering::render(&value, fonts(), false).unwrap();
    let preview = rendering::render(&value, fonts(), true).unwrap();
    assert_eq!(print.dimensions(), (1982, 612));
    assert_eq!(preview.dimensions(), (612, 1982));
    assert_eq!(image::imageops::rotate90(&print), preview);
}
#[test]
fn formatted_text_reports_overflow_instead_of_clipping() {
    let mut value = draft();
    value["sizeId"] = "29x90".into();
    value["fontSize"] = 200.into();
    value["content"] = json!({"kind":"text","text":"A\nA\nA","paragraphs":[{"runs":[{"text":"A"}]},{"runs":[{"text":"A"}]},{"runs":[{"text":"A"}]}]});
    assert!(
        rendering::render(&value, fonts(), false)
            .unwrap_err()
            .to_string()
            .contains("height")
    );
}
#[test]
fn vertical_alignment_moves_ink_without_resizing_fixed_paper() {
    let mut value = draft();
    value["sizeId"] = "29x90".into();
    value["verticalAlign"] = "top".into();
    let top = rendering::render(&value, fonts(), false).unwrap();
    value["verticalAlign"] = "bottom".into();
    let bottom = rendering::render(&value, fonts(), false).unwrap();
    let first_row = |image: &image::RgbImage| {
        image
            .enumerate_pixels()
            .filter(|(_, _, p)| p.0 != [255; 3])
            .map(|(_, y, _)| y)
            .min()
            .unwrap()
    };
    assert_eq!(top.dimensions(), bottom.dimensions());
    assert_eq!(first_row(&top), 17);
    assert!(first_row(&bottom) > 200);
}
#[test]
fn barcode_width_safeguard_and_four_supported_symbologies() {
    let mut value = draft();
    for (format, code) in [
        ("code128", "SKU-0042"),
        ("ean13", "590123412345"),
        ("ean8", "9638507"),
        ("upca", "03600029145"),
    ] {
        value["content"] = json!({"kind":"barcode","format":format,"code":code,"caption":"Stock"});
        let image = rendering::render(&value, fonts(), false).unwrap();
        assert_eq!(image.width(), 696);
        assert!(image.height() > 100);
    }
    value["content"] =
        json!({"kind":"barcode","format":"code128","code":"X".repeat(80),"caption":""});
    assert!(
        rendering::render(&value, fonts(), false)
            .unwrap_err()
            .to_string()
            .contains("too wide")
    );
}
#[test]
fn whitespace_only_text_and_empty_paragraph_render_safely() {
    let mut value = draft();
    value["content"]["text"] = "".into();
    assert!(
        rendering::render(&value, fonts(), true)
            .unwrap()
            .pixels()
            .all(|p| p.0 == [255; 3])
    );
    value["content"]["paragraphs"] = json!([{"runs":[]}]);
    assert!(rendering::render(&value, fonts(), true).unwrap().height() > 0);
}
