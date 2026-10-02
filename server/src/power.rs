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
        if kind == 0xf0 { packet[30] * 10 } else { 0 },
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

#[cfg(test)]
mod tests {
    use super::*;
    use std::{
        io::{Read, Write},
        os::{fd::OwnedFd, unix::net::UnixStream},
    };
    fn response(value: u8) -> Vec<u8> {
        let mut p = vec![0; 32];
        p[..6].copy_from_slice(&[0x80, 0x20, 0x42, 0x34, 0x38, 0x30]);
        p[18] = 0xf0;
        p[30] = value;
        p[31] = 1;
        p
    }
    fn exchange(packet: Vec<u8>, kind: u8) -> Result<(u8, String)> {
        let (client, mut fake) = UnixStream::pair().unwrap();
        client.set_nonblocking(true).unwrap();
        fake.set_read_timeout(Some(Duration::from_secs(1))).unwrap();
        let worker = std::thread::spawn(move || {
            let mut command = [0; 5];
            fake.read_exact(&mut command).unwrap();
            assert_eq!(&command, b"\x1biUA\x01");
            fake.write_all(&packet).unwrap();
        });
        let result = query(&mut File::from(OwnedFd::from(client)), b"\x1biUA\x01", kind);
        worker.join().unwrap();
        result
    }
    #[test]
    fn settings_accept_only_known_ql800_idle_acknowledgements() {
        for value in 0..=6 {
            assert_eq!(exchange(response(value), 0xf0).unwrap().0, value * 10);
        }
        for (index, value) in [
            (4, 0x39),
            (8, 1),
            (9, 1),
            (18, 0),
            (19, 1),
            (30, 7),
            (31, 0),
        ] {
            let mut p = response(3);
            p[index] = value;
            assert!(exchange(p, 0xf0).is_err(), "index {index}");
        }
        let mut p = response(255);
        p[18] = 0;
        assert_eq!(exchange(p, 0).unwrap().0, 0);
    }
    #[test]
    fn invalid_minutes_never_open_a_device() {
        let cfg = Config {
            printer: "file:///does-not-exist".into(),
            ..Config::default()
        };
        for minutes in [1, 9, 11, 61, 255] {
            assert!(
                power(&cfg, Some(minutes))
                    .unwrap_err()
                    .to_string()
                    .starts_with("Minutes must be")
            );
        }
    }
}
