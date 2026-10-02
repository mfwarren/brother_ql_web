//! Native Brother raster protocol and bounded Linux usblp transport.
use crate::{
    config::Config,
    media::{self},
};
use anyhow::{Context, Result, bail};
use image::{RgbImage, imageops};
use serde_json::{Value, json};
use std::{
    fs::{self, File, OpenOptions},
    io::{Read, Write},
    net::TcpStream,
    os::unix::{fs::OpenOptionsExt, io::AsRawFd},
    time::{Duration, Instant},
};
#[derive(Debug)]
pub struct PrintError {
    pub status: u16,
    pub message: String,
}
impl std::fmt::Display for PrintError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}
impl std::error::Error for PrintError {}
fn failure(status: u16, message: impl Into<String>) -> anyhow::Error {
    PrintError {
        status,
        message: message.into(),
    }
    .into()
}
pub fn acquire_lock(config: &Config) -> Result<File> {
    fs::create_dir_all(&config.data_dir)?;
    let file = OpenOptions::new()
        .create(true)
        .truncate(false)
        .read(true)
        .write(true)
        .open(config.data_dir.join("printer.lock"))?;
    fs2::FileExt::try_lock_exclusive(&file).map_err(|_| failure(409, "Printer busy"))?;
    Ok(file)
}
fn device(config: &Config) -> String {
    if config.printer == "?" {
        (0..=10)
            .map(|n| format!("/dev/usb/lp{n}"))
            .find(|p| std::path::Path::new(p).exists())
            .map(|p| format!("file://{p}"))
            .unwrap_or_default()
    } else {
        config.printer.clone()
    }
}
#[derive(Debug, Clone)]
pub struct RawStatus {
    pub model: String,
    pub width: u32,
    pub length: u32,
    pub media_type: String,
    pub color: String,
    pub code: u8,
    pub phase: u8,
    pub errors: Vec<String>,
}
pub fn decode_status(packet: &[u8]) -> Result<RawStatus> {
    if packet.len() != 32 || !packet.starts_with(&[0x80, 0x20, 0x42]) {
        bail!("Invalid printer status packet");
    }
    let defs: Value = serde_json::from_str(include_str!("../data/status.json"))?;
    let mut errors = vec![];
    for (index, key) in [
        (8, "RESP_ERROR_INFORMATION_1_DEF"),
        (9, "RESP_ERROR_INFORMATION_2_DEF"),
    ] {
        for bit in 0..8 {
            if packet[index] & (1 << bit) != 0 {
                errors.push(
                    defs[key][bit.to_string()]
                        .as_str()
                        .unwrap_or("Unknown printer error")
                        .to_owned(),
                );
            }
        }
    }
    let model = media::model_code(packet[3], packet[4]);
    let color =
        if ["QL-800", "QL-810W", "QL-820NWB"].contains(&model.as_str()) && packet[25] & 0x80 != 0 {
            "black-red"
        } else if model == "QL-800" && packet[25] == 1 {
            "black"
        } else {
            "unknown"
        };
    Ok(RawStatus {
        model,
        width: packet[10] as u32,
        length: packet[17] as u32,
        media_type: defs["RESP_MEDIA_TYPES"][packet[11].to_string()]
            .as_str()
            .unwrap_or("Unknown")
            .into(),
        color: color.into(),
        code: packet[18],
        phase: packet[19],
        errors,
    })
}
pub fn status_from_raw(raw: &RawStatus, model: &str, expected: Option<&str>) -> Result<Value> {
    let media = if raw.width > 0 {
        let dimensions = if raw.length > 0 {
            format!("{} × {}", raw.width, raw.length)
        } else {
            raw.width.to_string()
        };
        Some(format!(
            "{dimensions} mm {}{}",
            raw.media_type,
            match raw.color.as_str() {
                "black" => " (black only)",
                "black-red" => " (black/red)",
                _ => "",
            }
        ))
    } else {
        None
    };
    let (state, message) = if !raw.errors.is_empty() {
        ("error", raw.errors.join(", "))
    } else if raw.phase == 1 {
        ("busy", "Printer busy".into())
    } else if raw.model != model {
        (
            "error",
            "Connected printer model does not match configuration".into(),
        )
    } else if raw.width == 0
        || ["No media", "Incompatible tape", "Unknown"].contains(&raw.media_type.as_str())
    {
        ("error", "No compatible label roll loaded".into())
    } else if raw.code != 0 || raw.phase != 0 {
        ("unknown", "Printer readiness is unknown".into())
    } else if let Some(size) = expected {
        let label = media::lookup(size)?;
        if raw.color == "black-red" && size != "62red" {
            (
                "error",
                "Black/red tape is loaded. Choose 62 mm black/red for this label.".into(),
            )
        } else if raw.color == "black" && size == "62red" {
            (
                "error",
                "Black-only tape is loaded. Choose a black-only label roll.".into(),
            )
        } else if label.tape_size != (raw.width, raw.length) {
            ("error", "Loaded roll does not match label size".into())
        } else {
            ("ready", "Printer ready".into())
        }
    } else {
        ("ready", "Printer ready".into())
    };
    let matches: Vec<_> = media::all()
        .iter()
        .filter(|m| {
            m.tape_size == (raw.width, raw.length)
                && media::model(model).is_ok_and(|x| media::supported(m, &x))
                && (raw.color != "black-red" || m.identifier == "62red")
                && (raw.color != "black" || m.identifier != "62red")
        })
        .map(|m| &m.identifier)
        .collect();
    Ok(
        json!({"state":state,"model":raw.model,"message":message,"media":media,"matchingSizes":matches,"mediaColor":raw.color}),
    )
}
pub fn status(config: &Config) -> Result<Value> {
    let _lock = match acquire_lock(config) {
        Ok(x) => x,
        Err(_) => {
            return Ok(
                json!({"state":"busy","model":config.model,"message":"Printer busy","media":null}),
            );
        }
    };
    status_locked(config, None)
}
fn status_locked(config: &Config, expected: Option<&str>) -> Result<Value> {
    let dev = device(config);
    let simple =
        |state, message| json!({"state":state,"model":config.model,"message":message,"media":null});
    if dev == "simulation" {
        return Ok(simple("simulation", "Test print to file"));
    }
    if dev.starts_with("tcp://") {
        return Ok(simple("unknown", "Network printer status unavailable"));
    }
    match query_status(&dev) {
        Ok(raw) => status_from_raw(&raw, &config.model, expected),
        Err(_) => Ok(simple("offline", "Printer unavailable")),
    }
}
pub fn open_device(device: &str) -> Result<File> {
    let path = device
        .strip_prefix("file://")
        .context("Use a file:///dev/usb/lpN printer device")?;
    Ok(OpenOptions::new()
        .read(true)
        .write(true)
        .custom_flags(libc::O_NONBLOCK)
        .open(path)?)
}
fn poll(file: &File, event: i16, deadline: Instant) -> Result<()> {
    let remaining = deadline.saturating_duration_since(Instant::now());
    if remaining.is_zero() {
        bail!("Printer response timed out");
    }
    let mut fd = libc::pollfd {
        fd: file.as_raw_fd(),
        events: event,
        revents: 0,
    };
    let result = unsafe { libc::poll(&mut fd, 1, remaining.as_millis().min(50) as i32) };
    if result < 0 {
        let e = std::io::Error::last_os_error();
        if e.kind() != std::io::ErrorKind::Interrupted {
            return Err(e.into());
        }
    }
    if fd.revents & (libc::POLLERR | libc::POLLNVAL) != 0 {
        bail!("USB device disconnected");
    }
    Ok(())
}
pub fn write_all(file: &mut File, data: &[u8], deadline: Instant) -> Result<()> {
    let mut offset = 0;
    while offset < data.len() {
        if Instant::now() >= deadline {
            bail!("USB write timed out; the job may be incomplete. Do not automatically reprint.");
        }
        match file.write(&data[offset..(offset + 16384).min(data.len())]) {
            Ok(0) => poll(file, libc::POLLOUT, deadline)?,
            Ok(n) => offset += n,
            Err(e)
                if matches!(
                    e.kind(),
                    std::io::ErrorKind::WouldBlock | std::io::ErrorKind::Interrupted
                ) =>
            {
                poll(file, libc::POLLOUT, deadline)?
            }
            Err(e) => return Err(e.into()),
        }
    }
    Ok(())
}
pub fn read_packet(file: &mut File, buffer: &mut Vec<u8>, deadline: Instant) -> Result<Vec<u8>> {
    loop {
        if Instant::now() >= deadline {
            bail!("Printer response timed out");
        }
        if let Some(start) = buffer.windows(3).position(|x| x == [0x80, 0x20, 0x42]) {
            buffer.drain(..start);
            if buffer.len() >= 32 {
                return Ok(buffer.drain(..32).collect());
            }
        } else if buffer.len() > 2 {
            buffer.drain(..buffer.len() - 2);
        }
        poll(file, libc::POLLIN, deadline)?;
        let mut bytes = [0; 4096];
        match file.read(&mut bytes) {
            Ok(0) => std::thread::sleep(Duration::from_millis(5)),
            Ok(n) => buffer.extend_from_slice(&bytes[..n]),
            Err(e)
                if matches!(
                    e.kind(),
                    std::io::ErrorKind::WouldBlock | std::io::ErrorKind::Interrupted
                ) => {}
            Err(e) => return Err(e.into()),
        }
    }
}
pub fn drain(file: &mut File) {
    let until = Instant::now() + Duration::from_millis(100);
    let mut buf = [0; 4096];
    while Instant::now() < until {
        let _ = file.read(&mut buf);
        std::thread::sleep(Duration::from_millis(5));
    }
}
pub fn query_status(device: &str) -> Result<RawStatus> {
    if device.starts_with("usb://") {
        let usb = UsbDevice::open(device)?;
        usb.drain();
        let deadline = Instant::now() + Duration::from_secs(3);
        usb.write(b"\x1biS", deadline)?;
        let mut buffer = vec![];
        loop {
            let status = usb.packet(&mut buffer, deadline)?;
            if status.code == 0 {
                return Ok(status);
            }
        }
    }
    let mut file = open_device(device)?;
    drain(&mut file);
    let deadline = Instant::now() + Duration::from_secs(3);
    write_all(&mut file, b"\x1biS", deadline)?;
    let mut buffer = vec![];
    loop {
        let raw = decode_status(&read_packet(&mut file, &mut buffer, deadline)?)?;
        if raw.code == 0 {
            return Ok(raw);
        }
    }
}
pub fn send_raster(device: &str, data: &[u8], jobs: usize) -> Result<()> {
    if device.starts_with("usb://") {
        let usb = UsbDevice::open(device)?;
        usb.drain();
        let deadline = Instant::now() + Duration::from_secs(90 * jobs as u64);
        usb.write(data, deadline)?;
        let (mut completed, mut ready) = (0, 0);
        let mut buffer = vec![];
        while completed < jobs || ready < jobs {
            let state = usb.packet(&mut buffer, deadline)?;
            if !state.errors.is_empty() {
                bail!("{}", state.errors.join(", "));
            }
            if state.code == 1 {
                completed += 1;
            }
            if state.code == 6 && state.phase == 0 {
                ready += 1;
            }
        }
        return Ok(());
    }
    if let Some(address) = device.strip_prefix("tcp://") {
        let address = if address.contains(':') {
            address.to_owned()
        } else {
            format!("{address}:9100")
        };
        let addresses = std::net::ToSocketAddrs::to_socket_addrs(&address)?;
        let mut connected = None;
        for address in addresses {
            if let Ok(stream) = TcpStream::connect_timeout(&address, Duration::from_secs(5)) {
                connected = Some(stream);
                break;
            }
        }
        let mut stream = connected.context("Network printer unavailable")?;
        stream.set_write_timeout(Some(Duration::from_secs(90)))?;
        stream.write_all(data)?;
        return Ok(());
    }
    let mut file = open_device(device)?;
    drain(&mut file);
    let deadline = Instant::now() + Duration::from_secs(90 * jobs as u64);
    write_all(&mut file, data, deadline)?;
    let (mut complete, mut ready) = (0, 0);
    let mut buffer = vec![];
    while complete < jobs || ready < jobs {
        let packet=read_packet(&mut file,&mut buffer,deadline).context("Print completion was not confirmed. Check the label before retrying; power-cycle the printer if it remains busy.")?;
        let state = decode_status(&packet)?;
        if !state.errors.is_empty() {
            bail!("{}", state.errors.join(", "));
        }
        if state.code == 1 {
            complete += 1;
        }
        if state.code == 6 && state.phase == 0 {
            ready += 1;
        }
    }
    Ok(())
}
/// Rasterizes one page. Commands and media offsets mirror brother_ql-inventree 1.3.
pub fn rasterize(
    model_id: &str,
    size: &str,
    image: &RgbImage,
    rotated: bool,
    high_res: bool,
    cut: bool,
    dither: bool,
) -> Result<Vec<u8>> {
    let model = media::model(model_id)?;
    let paper = media::validate(size, model_id)?;
    let red = paper.color == 1;
    if red && high_res {
        bail!("High resolution is unavailable on black/red tape");
    }
    let scale = if high_res { 2 } else { 1 };
    let (expected_w, expected_h) = (
        paper.dots_printable.0 * scale,
        paper.dots_printable.1 * scale,
    );
    let mut img = if (!paper.fixed_size() && rotated)
        || (paper.fixed_size() && image.dimensions() == (expected_h, expected_w))
    {
        imageops::rotate270(image)
    } else {
        image.clone()
    };
    if paper.fixed_size() && img.dimensions() != (expected_w, expected_h) {
        bail!(
            "Bad image dimensions: {:?}. Expecting: {:?}",
            img.dimensions(),
            (expected_w, expected_h)
        );
    }
    if high_res {
        img = imageops::resize(
            &img,
            img.width() / 2,
            img.height(),
            imageops::FilterType::CatmullRom,
        );
    }
    if img.width() != paper.dots_printable.0 {
        let h = (paper.dots_printable.0 as u64 * img.height() as u64 / img.width() as u64) as u32;
        img = imageops::resize(
            &img,
            paper.dots_printable.0,
            h.max(1),
            imageops::FilterType::Lanczos3,
        );
    }
    let width = (model.number_bytes_per_row * 8) as u32;
    let offset = width as i32 - img.width() as i32 - paper.offset_r - model.additional_offset_r;
    let mut page = RgbImage::from_pixel(width, img.height(), image::Rgb([255; 3]));
    imageops::overlay(&mut page, &img, offset as i64, 0);
    let mut data = vec![];
    if model.mode_setting {
        data.extend(b"\x1bia\x01");
    }
    data.resize(data.len() + model.num_invalidate_bytes, 0);
    data.extend(b"\x1b@");
    if model.mode_setting {
        data.extend(b"\x1bia\x01");
    }
    data.extend(b"\x1biS\x1biz\xce");
    data.push(if paper.fixed_size() {
        11
    } else if paper.form_factor == 4 {
        0
    } else {
        10
    });
    data.push(paper.tape_size.0 as u8);
    data.push(paper.tape_size.1 as u8);
    data.extend(page.height().to_le_bytes());
    data.extend([0, 0]);
    if cut && model.cutting {
        data.extend(b"\x1biM\x40");
        if !model_id.starts_with("PT") {
            data.extend(b"\x1biA\x01");
        }
    }
    if model.expanded_mode {
        data.extend(b"\x1biK");
        data.push(if model_id.starts_with("PT") {
            12 | ((high_res as u8) << 5)
        } else {
            ((cut as u8) << 3) | ((high_res as u8) << 6) | (red as u8)
        });
    }
    data.extend(b"\x1bid");
    data.extend(paper.feed_margin.to_le_bytes());
    if model.compression_support {
        data.extend(b"M\x00");
    }
    let mut errors = vec![0i32; width as usize + 2];
    for y in 0..page.height() {
        let mut black = vec![0; model.number_bytes_per_row];
        let mut reds = vec![0; model.number_bytes_per_row];
        let mut carry = 0;
        let mut next = vec![0i32; width as usize + 2];
        for x in 0..width {
            let pixel = page.get_pixel(x, y).0;
            let [r, g, b] = pixel;
            let l = ((r as u32 * 19595 + g as u32 * 38470 + b as u32 * 7471 + 32768) >> 16) as i32;
            let ink = 255 - l;
            let (black_ink, red_ink) = if red {
                let max = r.max(g).max(b);
                let min = r.min(g).min(b);
                let saturation = if max == 0 {
                    0.0
                } else {
                    (max - min) as f64 / max as f64 * 255.0
                };
                let hue = if max == min {
                    0.0
                } else {
                    let delta = (max - min) as f64;
                    let h = if max == r {
                        (g as f64 - b as f64) / delta
                    } else if max == g {
                        2.0 + (b as f64 - r as f64) / delta
                    } else {
                        4.0 + (r as f64 - g as f64) / delta
                    };
                    (h / 6.0).rem_euclid(1.0) * 255.0
                };
                let hue = hue as u8;
                let saturation = saturation as u8;
                let ri = !(40..=210).contains(&hue) && saturation > 100 && max > 80 && ink >= 76;
                (max < 80 && ink >= 76 && !ri, ri)
            } else if dither {
                let value = (ink + (errors[x as usize + 1] + carry) / 16).clamp(0, 255);
                let on = value > 128;
                let error = value - if on { 255 } else { 0 };
                carry = error * 7;
                next[x as usize] += error * 3;
                next[x as usize + 1] += error * 5;
                next[x as usize + 2] += error;
                (on, false)
            } else {
                (ink >= 76, false)
            };
            let bitx = width - 1 - x;
            if black_ink {
                black[bitx as usize / 8] |= 0x80 >> (bitx % 8);
            }
            if red_ink {
                reds[bitx as usize / 8] |= 0x80 >> (bitx % 8);
            }
        }
        errors = next;
        for (plane, row) in if red {
            vec![(1, black), (2, reds)]
        } else {
            vec![(0, black)]
        } {
            if model_id.starts_with("PT") {
                data.push(0x47);
                data.extend((row.len() as u16).to_le_bytes());
            } else {
                data.extend([if red { 0x77 } else { 0x67 }, plane, row.len() as u8]);
            }
            data.extend(row);
        }
    }
    data.push(0x1a);
    Ok(data)
}
fn check_media(config: &Config, size: &str, batch: bool, confirm_red: bool) -> Result<()> {
    if device(config) == "simulation" {
        return Ok(());
    }
    let state = status_locked(config, Some(size))?;
    if state["state"] != "ready" {
        return Err(failure(
            503,
            state["message"].as_str().unwrap_or("Printer unavailable"),
        ));
    }
    if size == "62red" && state["mediaColor"] != "black-red" {
        if batch {
            bail!("Load detected black/red tape before bulk printing.");
        }
        if !confirm_red {
            bail!("Confirm that 62 mm black/red tape is loaded before printing.");
        }
    }
    Ok(())
}
fn record(path: &std::path::Path, value: Value) -> Result<()> {
    let mut tmp = tempfile::NamedTempFile::new_in(path.parent().unwrap())?;
    serde_json::to_writer(&mut tmp, &value)?;
    tmp.as_file().sync_all()?;
    tmp.persist(path)?;
    Ok(())
}
pub fn print_drafts(
    config: &Config,
    fonts: &crate::fonts::Fonts,
    drafts: &[Value],
    cut: &str,
    job_id: Option<&str>,
    confirm_red: bool,
) -> Result<Value> {
    let first = drafts.first().context("Print queue is empty")?;
    let size = first["sizeId"].as_str().context("Missing paper size")?;
    let high = first["highRes"].as_bool().unwrap_or(false);
    if drafts
        .iter()
        .any(|d| d["sizeId"] != first["sizeId"] || d["highRes"] != first["highRes"])
    {
        bail!("All labels in a batch must use the same paper and resolution.");
    }
    let _lock = acquire_lock(config)?;
    let job = if let Some(id) = job_id {
        uuid::Uuid::parse_str(id).context("Invalid job ID")?;
        let dir = config
            .labels_dir
            .parent()
            .unwrap_or(&config.data_dir)
            .join("bulk-jobs");
        fs::create_dir_all(&dir)?;
        let path = dir.join(format!("{id}.json"));
        if path.exists() {
            return Err(failure(
                409,
                "This batch was already submitted. Check the printed labels before starting another batch.",
            ));
        }
        Some(path)
    } else {
        None
    };
    check_media(config, size, job.is_some(), confirm_red)?;
    let mut pixels = 0u64;
    let mut pages = vec![];
    for (index, draft) in drafts.iter().enumerate() {
        let img = crate::rendering::render(draft, fonts, false).with_context(|| {
            format!(
                "Label {}: rendering failed. No labels were sent.",
                index + 1
            )
        })?;
        pixels += img.width() as u64 * img.height() as u64;
        if pixels > 64_000_000 {
            bail!("Batch images are too large. Select fewer labels.");
        }
        let raster = rasterize(
            &config.model,
            size,
            &img,
            draft["orientation"] == "rotated",
            high,
            cut == "each" || index + 1 == drafts.len(),
            draft["content"]["mode"] != "bw",
        )?;
        pages.push((img, raster));
    }
    if let Some(path) = &job {
        record(path, json!({"state":"submitted","count":drafts.len()}))?;
    }
    submit(config, &pages).map_err(|e| {
        failure(
            502,
            format!("Printing stopped: {e}. Check the printer before starting another batch."),
        )
    })?;
    if let Some(path) = job {
        record(&path, json!({"state":"complete","count":drafts.len()}))?;
    }
    let simulated = device(config) == "simulation";
    Ok(
        json!({"kind":if simulated{"simulated"}else{"printed"},"copies":drafts.len(),"message":if job_id.is_some(){"Batch complete"}else if simulated{"Test image saved"}else{"Printed"}}),
    )
}
fn submit(config: &Config, pages: &[(RgbImage, Vec<u8>)]) -> Result<()> {
    let dev = device(config);
    if dev == "simulation" {
        let dir = config.data_dir.join("simulated_labels");
        fs::create_dir_all(&dir)?;
        for (img, raster) in pages {
            let id = uuid::Uuid::new_v4();
            img.save(dir.join(format!("{id}.png")))?;
            fs::write(dir.join(format!("{id}.bin")), raster)?;
        }
        return Ok(());
    }
    let batch = std::env::var("PRINT_BATCH_SIZE")
        .ok()
        .and_then(|s| s.parse::<usize>().ok())
        .filter(|n| *n > 0)
        .unwrap_or(5);
    for group in pages.chunks(batch) {
        let data: Vec<_> = group.iter().flat_map(|(_, r)| r.iter().copied()).collect();
        send_raster(&dev, &data, group.len())?;
    }
    Ok(())
}
/// Images are already laid out to their printable geometry by the webhook adapter.
pub fn print_images(
    config: &Config,
    images: &[RgbImage],
    size: &str,
    rotated: bool,
    high_res: bool,
    dither: bool,
) -> Result<()> {
    let _lock = acquire_lock(config)?;
    if !device(config).starts_with("tcp://") {
        check_media(config, size, false, false)?;
    }
    let pages = images
        .iter()
        .map(|im| {
            Ok((
                im.clone(),
                rasterize(&config.model, size, im, rotated, high_res, true, dither)?,
            ))
        })
        .collect::<Result<Vec<_>>>()?;
    submit(config, &pages)
}
struct UsbDevice {
    handle: rusb::DeviceHandle<rusb::GlobalContext>,
    input: u8,
    output: u8,
    interface: u8,
    detached: bool,
}
impl Drop for UsbDevice {
    fn drop(&mut self) {
        let _ = self.handle.release_interface(self.interface);
        if self.detached {
            let _ = self.handle.attach_kernel_driver(self.interface);
        }
    }
}
impl UsbDevice {
    fn open(spec: &str) -> Result<Self> {
        let address = spec
            .strip_prefix("usb://")
            .context("Invalid USB identifier")?;
        let (ids, serial) = address.split_once('/').unwrap_or((address, ""));
        let (v, p) = ids
            .split_once(':')
            .context("USB identifier must contain vendor:product")?;
        let vendor = u16::from_str_radix(v.trim_start_matches("0x"), 16)?;
        let product = u16::from_str_radix(p.trim_start_matches("0x"), 16)?;
        for dev in rusb::devices()?.iter() {
            let descriptor = dev.device_descriptor()?;
            if descriptor.vendor_id() != vendor || descriptor.product_id() != product {
                continue;
            }
            let handle = dev.open()?;
            if !serial.is_empty()
                && handle
                    .read_serial_number_string_ascii(&descriptor)
                    .unwrap_or_default()
                    != serial
            {
                continue;
            }
            let cfg = dev
                .active_config_descriptor()
                .or_else(|_| dev.config_descriptor(0))?;
            for interface in cfg.interfaces() {
                for desc in interface.descriptors() {
                    if desc.class_code() != 7 {
                        continue;
                    }
                    let input = desc
                        .endpoint_descriptors()
                        .find(|e| {
                            e.direction() == rusb::Direction::In
                                && e.transfer_type() == rusb::TransferType::Bulk
                        })
                        .map(|e| e.address());
                    let output = desc
                        .endpoint_descriptors()
                        .find(|e| {
                            e.direction() == rusb::Direction::Out
                                && e.transfer_type() == rusb::TransferType::Bulk
                        })
                        .map(|e| e.address());
                    if let (Some(input), Some(output)) = (input, output) {
                        let interface = desc.interface_number();
                        let detached = handle.kernel_driver_active(interface).unwrap_or(false);
                        if detached {
                            handle.detach_kernel_driver(interface)?;
                        }
                        if let Err(error) = handle.claim_interface(interface) {
                            if detached {
                                let _ = handle.attach_kernel_driver(interface);
                            }
                            return Err(error.into());
                        }
                        return Ok(Self {
                            handle,
                            input,
                            output,
                            interface,
                            detached,
                        });
                    }
                }
            }
        }
        bail!("USB printer not found")
    }
    fn write(&self, bytes: &[u8], deadline: Instant) -> Result<()> {
        let mut offset = 0;
        while offset < bytes.len() {
            let remaining = deadline.saturating_duration_since(Instant::now());
            if remaining.is_zero() {
                bail!("USB write timed out; check printer before retrying");
            }
            let n = self.handle.write_bulk(
                self.output,
                &bytes[offset..(offset + 16384).min(bytes.len())],
                remaining.min(Duration::from_secs(15)),
            )?;
            if n == 0 {
                bail!("USB connection closed");
            }
            offset += n;
        }
        Ok(())
    }
    fn packet(&self, buffer: &mut Vec<u8>, deadline: Instant) -> Result<RawStatus> {
        loop {
            let remaining = deadline.saturating_duration_since(Instant::now());
            if remaining.is_zero() {
                bail!("Printer response timed out; check printer before retrying");
            }
            if let Some(start) = buffer.windows(3).position(|x| x == [0x80, 0x20, 0x42]) {
                buffer.drain(..start);
                if buffer.len() >= 32 {
                    return decode_status(&buffer.drain(..32).collect::<Vec<_>>());
                }
            } else if buffer.len() > 2 {
                buffer.drain(..buffer.len() - 2);
            }
            let mut bytes = [0; 4096];
            match self.handle.read_bulk(
                self.input,
                &mut bytes,
                remaining.min(Duration::from_millis(50)),
            ) {
                Ok(n) => buffer.extend_from_slice(&bytes[..n]),
                Err(rusb::Error::Timeout) => {}
                Err(e) => return Err(e.into()),
            }
        }
    }
    fn drain(&self) {
        let until = Instant::now() + Duration::from_millis(100);
        let mut bytes = [0; 4096];
        while Instant::now() < until {
            let _ = self
                .handle
                .read_bulk(self.input, &mut bytes, Duration::from_millis(10));
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn raster_matches_python_driver() {
        let cases: Value =
            serde_json::from_str(include_str!("../tests/fixtures/cases.json")).unwrap();
        for (i, c) in cases.as_array().unwrap().iter().enumerate() {
            let base = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("tests/fixtures");
            let img = image::open(base.join(format!("{i}.png")))
                .unwrap()
                .into_rgb8();
            let actual = rasterize(
                c["model"].as_str().unwrap(),
                c["size"].as_str().unwrap(),
                &img,
                false,
                c["hi"].as_bool().unwrap(),
                true,
                c["dither"].as_bool().unwrap(),
            )
            .unwrap();
            let expected = fs::read(base.join(format!("{i}.bin"))).unwrap();
            assert_eq!(actual.len(), expected.len(), "case {i} length");
            if let Some(pos) = actual.iter().zip(&expected).position(|(a, b)| a != b) {
                panic!(
                    "case {i} byte {pos}: actual {} expected {}",
                    actual[pos], expected[pos]
                );
            }
        }
    }
    fn packet(width: u8, length: u8, color: u8) -> Vec<u8> {
        let mut p = vec![0; 32];
        p[..6].copy_from_slice(&[0x80, 0x20, 0x42, 0x34, 0x38, 0x30]);
        p[10] = width;
        p[11] = if length > 0 { 11 } else { 10 };
        p[17] = length;
        p[25] = color;
        p
    }
    #[test]
    fn known_rolls_and_mismatch() {
        for (width, length, color, size) in [
            (29, 90, 1, "29x90"),
            (62, 0, 1, "62"),
            (62, 0, 0x81, "62red"),
        ] {
            let raw = decode_status(&packet(width, length, color)).unwrap();
            let s = status_from_raw(&raw, "QL-800", Some(size)).unwrap();
            assert_eq!(s["state"], "ready");
            assert!(
                s["matchingSizes"]
                    .as_array()
                    .unwrap()
                    .contains(&json!(size))
            );
        }
        let raw = decode_status(&packet(62, 0, 1)).unwrap();
        assert_eq!(
            status_from_raw(&raw, "QL-800", Some("62red")).unwrap()["state"],
            "error"
        );
    }
    #[test]
    fn readiness_requires_fresh_reply() {
        let mut p = packet(62, 0, 1);
        p[18] = 1;
        assert_eq!(
            status_from_raw(&decode_status(&p).unwrap(), "QL-800", None).unwrap()["state"],
            "unknown"
        );
        p[18] = 0;
        p[19] = 1;
        assert_eq!(
            status_from_raw(&decode_status(&p).unwrap(), "QL-800", None).unwrap()["state"],
            "busy"
        );
    }
    #[test]
    fn fragmented_status_resynchronizes() {
        use std::os::unix::net::UnixStream;
        let (mut writer, reader) = UnixStream::pair().unwrap();
        reader.set_nonblocking(true).unwrap();
        let mut file = File::from(std::os::fd::OwnedFd::from(reader));
        let expected = packet(29, 90, 1);
        let send = expected.clone();
        let worker = std::thread::spawn(move || {
            writer.write_all(b"noise\x80").unwrap();
            writer.write_all(&send[..7]).unwrap();
            std::thread::sleep(Duration::from_millis(15));
            writer.write_all(&send[7..]).unwrap();
        });
        let got = read_packet(
            &mut file,
            &mut vec![],
            Instant::now() + Duration::from_secs(1),
        )
        .unwrap();
        assert_eq!(got, expected);
        worker.join().unwrap();
    }
    #[test]
    fn read_timeout_is_bounded() {
        use std::os::unix::net::UnixStream;
        let (_writer, reader) = UnixStream::pair().unwrap();
        reader.set_nonblocking(true).unwrap();
        let mut file = File::from(std::os::fd::OwnedFd::from(reader));
        let start = Instant::now();
        assert!(read_packet(&mut file, &mut vec![], start + Duration::from_millis(30)).is_err());
        assert!(start.elapsed() < Duration::from_millis(250));
    }
    #[test]
    fn tcp_sends_all_without_waiting_for_status() {
        let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
        let addr = listener.local_addr().unwrap();
        let worker = std::thread::spawn(move || {
            let (mut stream, _) = listener.accept().unwrap();
            let mut bytes = vec![];
            stream.read_to_end(&mut bytes).unwrap();
            bytes
        });
        let bytes = vec![42u8; 40000];
        send_raster(&format!("tcp://{addr}"), &bytes, 1).unwrap();
        assert_eq!(worker.join().unwrap(), bytes);
    }
    #[test]
    fn exclusive_lock() {
        let dir = tempfile::tempdir().unwrap();
        let c = Config {
            data_dir: dir.path().into(),
            ..Config::default()
        };
        let first = acquire_lock(&c).unwrap();
        assert!(acquire_lock(&c).is_err());
        drop(first);
        assert!(acquire_lock(&c).is_ok());
    }
}

#[cfg(test)]
#[path = "printer_risk_tests.rs"]
mod risk_tests;
