//! QL-800 power setting protocol, based on Marc Schuetze's MIT-licensed brother-ql700-settings.
use crate::{config::Config, printer};
use anyhow::{Context, Result, bail};
use serde_json::{Value, json};
use std::{
    fs::File,
    time::{Duration, Instant},
};
fn query(file: &mut File, command: &[u8], kind: u8) -> Result<(u8, String)> {
    let deadline = Instant::now() + Duration::from_secs(3);
    printer::write_all(file, command, deadline)?;
    let packet = printer::read_packet(file, &mut vec![], deadline)?;
    if packet[..6] != [0x80, 0x20, 0x42, 0x34, 0x38, 0x30]
        || packet[18] != kind
        || packet[8] != 0
        || packet[9] != 0
        || packet[19] != 0
    {
        bail!("Expected an idle QL-800 settings reply");
    }
    if kind == 0xf0 && (packet[31] != 1 || packet[30] > 6) {
        bail!("Unrecognized auto power-off value or acknowledgement");
    }
    Ok((
        packet[30] * 10,
        packet.iter().map(|b| format!("{b:02x}")).collect(),
    ))
}
fn read(file: &mut File) -> Result<Value> {
    printer::drain(file);
    query(file, b"\x1biS", 0)?;
    let (minutes, reply) = query(file, b"\x1biUA\x01", 0xf0)?;
    Ok(json!({"minutes":minutes,"reply":reply}))
}
pub fn power(config: &Config, minutes: Option<u8>) -> Result<Value> {
    if minutes.is_some_and(|m| m > 60 || m % 10 != 0) {
        bail!("Minutes must be 0, 10, 20, 30, 40, 50, or 60");
    }
    let _lock = printer::acquire_lock(config)?;
    let mut file = printer::open_device(&config.printer)?;
    let before = read(&mut file)?;
    let Some(minutes) = minutes else {
        return Ok(before);
    };
    if before["minutes"] == minutes {
        return Ok(json!({"changed":false,"before":before,"after":before}));
    }
    printer::write_all(
        &mut file,
        &[0x1b, b'i', b'U', b'A', 0, minutes / 10],
        Instant::now() + Duration::from_secs(3),
    )?;
    std::thread::sleep(Duration::from_millis(500));
    let after = read(&mut file)
        .context("Setting was sent but verification failed; read it before retrying")?;
    if after["minutes"] != minutes {
        bail!("Auto power-off read-back mismatch; do not retry blindly");
    }
    Ok(json!({"changed":true,"before":before,"after":after}))
}
