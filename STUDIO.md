# Install and run Label Studio

Label Studio is a React/TypeScript interface served by Flask and Waitress. Python renders the preview and sends Brother raster commands. Node is only needed when building from Git; it is not a running service on the printer host.

## Quick start: simulator

Use Python 3.11 or newer. On Debian/Raspberry Pi OS, install the system dependencies:

```sh
sudo apt update
sudo apt install python3-venv python3-dev build-essential fonts-dejavu-core libusb-1.0-0 poppler-utils
```

Download and extract `label-studio-v0.1.0.tar.gz` from the [release page](https://github.com/mfwarren/brother_ql_web/releases). This archive includes the built frontend. GitHub's automatic source archives require the frontend build below.

From the extracted directory:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-server.txt
mkdir -p instance
```

Create `instance/application.py`:

```python
PRINTER_MODEL = 'QL-800'
PRINTER_PRINTER = 'simulation'
SERVER_HOST = '127.0.0.1'
SERVER_PORT = 8014
```

Start the server:

```sh
.venv/bin/python serve.py
```

Open <http://127.0.0.1:8014/studio/>. **Test print** creates a raster job and PNG under `simulated_labels/`; it uses no paper. Old `/labeldesigner/` bookmarks redirect to Studio.

## Build from Git

Use Node 24 and npm 11.19.0 (the CI toolchain):

```sh
git clone --branch master https://github.com/mfwarren/brother_ql_web.git
cd brother_ql_web
npx --yes npm@11.19.0 ci --prefix frontend
npm run build --prefix frontend
```

Then follow the Python setup above. For frontend development, run the Python server on port 8014 and `npm run dev --prefix frontend`; Vite proxies API calls to that server.

## Connect a printer

For a Linux USB QL-800 exposed through `usblp`, change the configuration:

```python
PRINTER_MODEL = 'QL-800'
PRINTER_PRINTER = 'file:///dev/usb/lp0'
SERVER_HOST = '0.0.0.0'
```

Restart the server. The service account needs access to the USB device (commonly the `lp` group). Check the Printer page before printing. See [Raspberry Pi deployment](deploy/README.md) for a port-80 systemd service.

This is a shared-printer app without user accounts. Run it on a trusted local network; do not expose its printing and settings endpoints directly to the internet. Publishing this repository does not publish your printer or saved labels.

## Editing and storage

- Select words to change font family, style, pixel size, or underline. Fixed-size text labels offer Top, Center, and Bottom alignment.
- Preview updates keep the existing image visible until the replacement is ready. The server preview is the printed layout; the text editor is an editing surface.
- Save, duplicate, and reprint labels with their paper settings. New libraries include nine samples, including a black/red Fragile label.
- Settings controls defaults and local font installation. Google Fonts are downloaded from the official repository with their licenses. Original variable fonts render directly; weights and italics need no slow conversion. TTF/OTF uploads are supported.
- New labels can follow detected media. Saved labels retain their roll settings, and mismatches are checked again before printing.

Modern labels use versioned JSON in `instance/studio-labels/`, or `STUDIO_LABELS_DIR`. Settings and installed fonts live beside that directory, or under `STUDIO_DATA_DIR`. Back up the complete data directory, including hidden files. Existing classic label files are preserved on disk; Studio does not import them.

Samples are seeded once; deleted samples stay deleted. Set `STUDIO_SEED_SAMPLES = False` to disable seeding. To add missing samples to an existing library, preserving existing sample IDs and edits:

```sh
.venv/bin/python -c 'from app import create_app; from app.studio import seed_starter_labels; app = create_app(); ctx = app.app_context(); ctx.push(); seed_starter_labels(add_to_existing=True)'
```

## Compatibility and limits

The primary tested setup is a QL-800 attached by USB to a Raspberry Pi 3 running 32-bit Raspberry Pi OS 12. Physical printing and roll swaps were exercised with 62 mm black-only, 62 mm black/red, and 29 × 90 mm die-cut stock. Other models are inherited from the driver and need community testing. Container deployment is not verified for this release.

The [Linux Auto Power Off utility](docs/linux-power-settings.md) changed a real QL-800 from 60 minutes to disabled and verified the read-back. Long idle periods and persistence after a power cycle remain unverified. The app cannot wake a physically powered-off printer.

Hardware density adjustment is not implemented. See [QL-800 notes](docs/ql800.md), [media detection](docs/usb-status.md), [roll catalog](docs/label-roll-catalog.md), and [font/rendering details](docs/rich-text-and-fonts.md).

## Verification

```sh
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pytest tests/test_studio.py tests/test_studio_qr.py tests/test_studio_barcodes.py tests/test_bulk_labels.py tests/test_remote_images.py tests/test_printer_settings.py tests/test_studio_samples.py tests/test_studio_preferences.py tests/test_usb_transport.py tests/test_rich_text.py tests/test_webhook.py -q
node --experimental-strip-types frontend/title-checks.mjs
node --experimental-strip-types frontend/rich-text-checks.mjs
npm run build --prefix frontend
```

Tests cover rendering, QR decoding, persistence, font weights, formatting, alignment, stock checks, and USB transport. Browser checks cover desktop, tablet, and phone viewports; these are not physical iOS-device tests. Legacy PNG snapshot tests remain a separate manual workflow because their original routes and exact artwork differ from Studio.

## Text spacing and margins

Use **Spacing** in the text toolbar to set line spacing from 100% to 300%. In **Label settings**, margins are linked by default; turn off **Link sides** to adjust each side. Margins reduce the text area and affect wrapping. **Show margin guides** overlays the usable area in the preview only, including rotated labels. Saved labels and bulk templates retain spacing and margins.
