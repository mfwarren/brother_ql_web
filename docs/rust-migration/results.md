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

Deployed commit `7e8b7668088fa8b295ef4143bd2668b3bf826a2a` as a native ARMv7 release on the Raspberry Pi, using the existing port 80 systemd service. The release is `/opt/label-studio/releases/20261002-rust-7e8b766`.

Verification first ran on port 8016 against a copy of the data in simulation mode. [84 HTTP checks](evidence/pi-http-checks.txt), [PDF webhook checks](evidence/pi-webhook-checks.txt), and [request admission checks](evidence/pi-admission-checks.txt) passed on the Pi itself. All [104 font identifiers and defaults](evidence/pi-font-comparison.json) match Python. Of nine saved-label previews, [eight are pixel-identical and one QR has an equivalent decoded mask](evidence/pi-render-comparison.json). The same preview comparison passed after cutover on port 80.

[Live deployment checks](evidence/pi-deployment.json) confirm all nine saved documents remain unchanged and the QL-800 reports ready with a black-only 29 × 90 mm die-cut roll. A read-only power query returned zero minutes, meaning automatic power-off is disabled. The browser displayed a ready preview and the detected roll. Physical printing remains untested.

The old Python release, original service file, and a private data/configuration backup remain available for rollback. Temporary simulation and hardware-check servers were stopped after verification.

The Pi build exposed damaged GCC development archives and C header files. Reinstalling the GCC development packages repaired the archives; the build used a private extraction of clean C headers rather than replacing the live C runtime. The affected system headers still need repair. This is an existing host maintenance issue, not a Rust runtime requirement, and the cause was not established.

## Independent review

A separate GPT-5.6-sol review checked the implementation and evidence. Its findings led to bounded batch memory, reused rendering for repeated copies, high-resolution PDF checks, legacy webhook error compatibility, request admission before body buffering, upload inactivity timeouts, and bounded CSV expansion. The final review found no remaining blocking or high-impact code issues. Deployment gates were completed afterward as documented above. [Linux CI](https://github.com/mfwarren/brother_ql_web/actions/runs/37022563772) passed the native, frontend, and HTTP checks at the deployed code revision.
