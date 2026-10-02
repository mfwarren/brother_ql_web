# Rust migration verification

Local verification on October 2, 2026 used Rust 1.94 and the server on the `rust-backend` branch. The browser UI and saved-document schema remain unchanged. The production server has no Python runtime dependency. Python scripts in `tools/` are development utilities.

## Reproducible checks

```sh
cargo test --manifest-path server/Cargo.toml --locked
cargo clippy --manifest-path server/Cargo.toml --all-targets --locked -- -D warnings
cargo fmt --manifest-path server/Cargo.toml --check
cargo build --manifest-path server/Cargo.toml --locked --release
```

[Native test output](evidence/native-tests.txt) records 46 passing tests. The default suite skips one network-dependent Google Fonts download, which was also [run explicitly](evidence/google-font-check.txt). The checked-in fixtures include 14 exact rendered images and 9 exact Brother raster command streams. The render fixtures cover 8 text layouts and 6 image layouts.

The local HTTP checks ran against `server/target/release/label-studio-server` with disposable data, `FONT_FOLDER=.local-fonts`, `PRINTER_PRINTER=simulation`, port 8016, and a test webhook password:

```sh
.venv/bin/python tools/check_rust_api.py --url http://127.0.0.1:8016 \
  --require-decode --compare /tmp/label-python-http-reference --allow-qr-mask
.venv/bin/python tools/check_webhook.py --url http://127.0.0.1:8016 \
  --password label-test-webhook --data-dir /tmp/label-rust-http-data
```

[HTTP output](evidence/http-checks.txt) records 134 successful requests covering saved-label round trips, settings, CSV substitution and errors, fonts, previews, simulation printing, duplicate-job suppression, and unsafe image URL rejection. [Webhook output](evidence/webhook-checks.txt) covers authentication, multipart/JSON images, rotation, high-resolution Letter PDFs on fixed and continuous media, and legacy HTTP 400 responses when the printer lock is held.

The baseline previews were captured from Python commit `6897ed1`. [Comparison results](evidence/render-comparison.json) show 40 pixel-identical images and 10 QR images whose different masks decode to the same contents at the same dimensions. PNG compression differs between implementations. All [294 discovered font identifiers](evidence/font-comparison.json) match. The baseline previews remain local; committed rendering fixtures provide a portable regression check.

[Admission checks](evidence/admission-checks.txt) hold four incomplete 8 MiB uploads, verify excess API requests receive HTTP 503 with `Retry-After`, confirm the static interface stays available, and verify stalled uploads release their slots after 30 seconds. Bulk substitution also rejects excessive expansion before allocating it, and prepared batches stay below 7 MiB so they fit the print API.

CI runs the same native and HTTP checks against a debug binary, plus the React build and editor checks. It does not require a printer. No physical label was printed during this migration.

## Raspberry Pi

Deployment verification is pending. The Python service remains available until the ARM binary, saved-label previews, fonts, and read-only printer status have passed on the Pi.
