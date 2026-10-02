# Install Label Studio

Label Studio uses a Rust server and a React interface. The server renders labels, stores your library, and talks directly to the Brother printer. Python and Node are not needed to run it; Node is needed only to build the interface.

## Build from source

On Raspberry Pi OS or Debian:

```sh
sudo apt update
sudo apt install build-essential pkg-config libfreetype6-dev fonts-dejavu-core poppler-utils ca-certificates
```

Install Rust 1.94 or newer using [rustup](https://rustup.rs/). Build the interface on a computer with Node 24 or newer, then build the server:

```sh
npm ci --prefix frontend
npm run build --prefix frontend
cargo build --manifest-path server/Cargo.toml --locked --release
```

On a Pi with limited memory, set `CARGO_BUILD_JOBS=1` for the Cargo command. The binary is built for the computer where Cargo runs. Copying a Mac binary onto a Pi will not work.

## Try the simulator

Run from the repository directory:

```sh
PRINTER_PRINTER=simulation FONT_FOLDER=.local-fonts \
  SERVER_HOST=127.0.0.1 SERVER_PORT=8013 \
  server/target/release/label-studio-server
```

`FONT_FOLDER` is optional; the server also discovers installed system fonts. Open `http://127.0.0.1:8013/studio/`. Simulated prints produce files without using a printer. Nine sample labels appear in a new library.

## Connect a printer

On Linux, the kernel's `usblp` driver exposes the printer at `/dev/usb/lp0`. Give the service account access through the `lp` group. Start the server with:

```sh
PRINTER_PRINTER=file:///dev/usb/lp0 PRINTER_MODEL=QL-800 \
  SERVER_HOST=0.0.0.0 SERVER_PORT=8013 \
  server/target/release/label-studio-server
```

Open `http://<printer-host>:8013/studio/`. Check the detected roll on the Printer page before printing. A `tcp://host:9100` connection is also supported; network printers cannot supply the same USB status checks.

For automatic startup on port 80, use the [service guide](deploy/README.md).

## Configuration and persistent data

Use `LABEL_STUDIO_CONFIG=/path/application.json` to load a JSON configuration. Start with [the example](deploy/application.json.example). Environment variables override the matching host settings:

| Variable | Purpose |
| --- | --- |
| `PRINTER_PRINTER` | `simulation`, `file:///dev/usb/lp0`, or a printer URI |
| `PRINTER_MODEL` | Brother model, such as `QL-800` |
| `SERVER_HOST`, `SERVER_PORT` | Listening address and port |
| `STUDIO_DATA_DIR` | Settings, fonts, printer lock, and job records |
| `STUDIO_LABELS_DIR` | Saved-label directory; defaults to `labels` under an explicit data directory |
| `STUDIO_STATIC_DIR` | Built frontend directory |
| `FONT_FOLDER` | Additional font directory |
| `WEBHOOK_PASSWORD` | Enables the authenticated image-printing webhook |

Set paper, typeface, orientation, and margin defaults in the app's Settings page. Those defaults persist in `settings.json`. Fonts remain in `fonts/`, and each saved label remains a JSON document. Back up the whole data directory, including hidden sample markers. Deleting an example does not cause it to reappear at the next startup.

The Rust server reads existing Studio label documents, installed font manifests, and `settings.json` directly. Host configuration has changed from executable Python to JSON; copy your printer model, device, and data paths into the example. Keep the previous service and a data backup until you have verified the replacement.

## Development checks

```sh
cargo test --manifest-path server/Cargo.toml --locked
cargo clippy --manifest-path server/Cargo.toml --all-targets -- -D warnings
node --experimental-strip-types frontend/rich-text-checks.mjs
node --experimental-strip-types frontend/title-checks.mjs
npm run build --prefix frontend
```

The migration's reference checks use Python as a development tool only. They do not form part of the running Rust service.
