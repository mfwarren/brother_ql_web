use anyhow::{Result, bail, ensure};
use base64::{Engine, engine::general_purpose::STANDARD};
use serde_json::{Value, json};
use std::{
    io::Read,
    net::{IpAddr, ToSocketAddrs},
    time::Duration,
};
use url::Url;
const LIMIT: usize = 5 * 1024 * 1024;
fn public(ip: IpAddr) -> bool {
    match ip {
        IpAddr::V4(ip) => {
            let [a, b, c, _] = ip.octets();
            !(a == 0
                || a == 10
                || a == 127
                || a >= 224
                || (a == 100 && (64..=127).contains(&b))
                || (a == 169 && b == 254)
                || (a == 172 && (16..=31).contains(&b))
                || (a == 192 && b == 168)
                || (a == 192 && b == 0)
                || (a == 192 && b == 88 && c == 99)
                || (a == 198 && (b == 18 || b == 19))
                || (a == 198 && b == 51 && c == 100)
                || (a == 203 && b == 0 && c == 113))
        }
        IpAddr::V6(ip) => {
            if let Some(ip) = ip.to_ipv4_mapped() {
                return public(ip.into());
            }
            let s = ip.segments();
            (s[0] & 0xe000) == 0x2000
                && !(s[0] == 0x2001 && (s[1] < 0x200 || s[1] == 0xdb8))
                && s[0] != 0x2002
                && !(s[0] == 0x3fff && s[1] < 0x1000)
        }
    }
}
pub fn fetch(value: &str) -> Result<Value> {
    ensure!(value.len() <= 2000, "Invalid image URL.");
    let mut url = Url::parse(value)?;
    for _ in 0..4 {
        ensure!(
            url.scheme() == "https"
                && url.username().is_empty()
                && url.password().is_none()
                && url.port_or_known_default() == Some(443),
            "Use a public HTTPS image URL without a login or custom port."
        );
        let host = url
            .host_str()
            .ok_or_else(|| anyhow::anyhow!("Invalid image host."))?;
        let addresses: Vec<_> = (host, 443).to_socket_addrs()?.collect();
        ensure!(
            !addresses.is_empty() && addresses.iter().all(|a| public(a.ip())),
            "Image URLs must point to a public internet address."
        );
        let client = reqwest::blocking::Client::builder()
            .no_proxy()
            .redirect(reqwest::redirect::Policy::none())
            .timeout(Duration::from_secs(8))
            .resolve(host, addresses[0])
            .build()?;
        let response = client
            .get(url.clone())
            .header("Accept", "image/png,image/jpeg")
            .send()?;
        if response.status().is_redirection() {
            let location = response
                .headers()
                .get("location")
                .ok_or_else(|| anyhow::anyhow!("Image redirect has no destination."))?
                .to_str()?;
            url = url.join(location)?;
            continue;
        }
        ensure!(
            response.status().as_u16() == 200,
            "Image server returned HTTP {}. Use a direct image link.",
            response.status()
        );
        let mut payload = Vec::new();
        response
            .take((LIMIT + 1) as u64)
            .read_to_end(&mut payload)?;
        ensure!(payload.len() <= LIMIT, "Image exceeds 5 MB.");
        let format = image::guess_format(&payload)?;
        ensure!(
            matches!(format, image::ImageFormat::Png | image::ImageFormat::Jpeg),
            "Image URLs must return PNG or JPEG files."
        );
        let reader = image::ImageReader::with_format(std::io::Cursor::new(&payload), format);
        let (w, h) = reader.into_dimensions()?;
        ensure!(
            u64::from(w) * u64::from(h) <= 16_000_000,
            "Image exceeds 16 megapixels."
        );
        image::load_from_memory_with_format(&payload, format)?;
        return Ok(
            json!({"name":if format==image::ImageFormat::Png{"downloaded.png"}else{"downloaded.jpg"},"mime":if format==image::ImageFormat::Png{"image/png"}else{"image/jpeg"},"base64":STANDARD.encode(payload)}),
        );
    }
    bail!("Too many image redirects.")
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn blocks_private_special_mapped() {
        for s in [
            "127.0.0.1",
            "10.0.0.1",
            "169.254.169.254",
            "100.64.0.1",
            "192.0.2.1",
            "224.0.0.1",
            "::1",
            "::ffff:127.0.0.1",
            "fc00::1",
            "2001:db8::1",
        ] {
            assert!(!public(s.parse().unwrap()), "{s}");
        }
        assert!(public("8.8.8.8".parse().unwrap()));
        assert!(public("2606:4700:4700::1111".parse().unwrap()));
    }
}
