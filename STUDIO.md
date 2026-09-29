# Label Studio

This development branch adds a React and TypeScript interface to DL6ER's Brother QL Web. The original Python renderer and raster driver remain responsible for output. Flask serves the compiled frontend, so the Raspberry Pi does not need a Node process. The new interface uses custom CSS and Lucide icons. The advanced editor still uses upstream Bootstrap 5 and jQuery.

The local branch is `modern-interface`, based on upstream commit `6c88c0489eb47324371425eb0bb55be04425aed7`. The GitHub fork retains upstream history and uses `modern-interface` as its development branch. The recovered Pi application is preserved separately in the workspace.

## Run locally

From this directory, install the Python requirements into an isolated environment and build the frontend:

```sh
uv venv --python 3.11 .venv
uv pip install --python .venv/bin/python -r requirements.txt
npm ci --prefix frontend
npm run build --prefix frontend
```

Create `instance/application.py` for a local simulator:

```python
PRINTER_MODEL = 'QL-800'
PRINTER_PRINTER = 'simulation'
SERVER_HOST = '127.0.0.1'
SERVER_PORT = 8014
```

Use installed fonts, or set `FONT_FOLDER` to a directory containing TTF or OTF files. In this workspace, `.local-fonts/` contains a copy of the Pi's DejaVu fonts and the existing local configuration points to it. These files and machine-specific configuration are ignored by Git.

Start the server:

```sh
.venv/bin/python run.py
```

Open [Label Studio](http://127.0.0.1:8014/studio/). **Test print** generates a raster job and saves PNG output under `simulated_labels/`. It does not send paper through a physical printer. The classic editor remains at `/labeldesigner/`.

For frontend development, start Flask first, then run `npm run dev --prefix frontend`. Vite proxies `/studio/api` to the local Flask server on port 8014. Rebuild before using Flask's compiled frontend again.

## Current capabilities

- Text labels with multiline text, font selection, alignment, ink color, margins, and orientation.
- QR content with a separate caption.
- PNG, JPEG, and first-page PDF labels with fit-to-label and image treatment controls.
- Named labels with save, edit, duplicate, delete, and one-copy reprint actions.
- Server-rendered PNG previews with a 300 ms debounce and stale-response cancellation.
- A printer page that distinguishes simulator, ready, busy, offline, and error states.
- Server-side limits for request size, image bytes, copies, fonts, label size, and print options.
- Cross-process USB access locking, plus loaded width and length checks before physical printing.

Modern saved documents use version 1 JSON in `instance/studio-labels/`, configurable with `STUDIO_LABELS_DIR`. Saves use atomic replacement. They are separate from upstream `labels/` because this initial editor does not expose every upstream per-line style, barcode, or template option. The advanced editor retains those features and its original library. No silent conversion discards those options.

## Printer power

An experimental [Linux-only QL-800 utility](docs/linux-power-settings.md) now reads and changes Auto Power Off. On the test printer it changed 60 minutes to disabled and verified the read-back. Idle-period behavior and persistence after a power cycle remain unverified.

Brother documents disabling **Auto Power Off (AC/DC)** by setting it to **None** in the Printer Setting Tool while the QL-800 is connected by USB to a Mac or Windows computer. [Brother's instructions](https://support.brother.com/g/b/faqend.aspx?c=us_ot&faqid=faqp00001613_001&lang=en&prod=lpql800eus).

The Pi successfully queried the powered-on QL-800. It reported 62 mm continuous tape, waiting to receive, and no errors. That query did not read or change the auto-off setting, identify black/red media, or print a label. The app does not claim to wake a powered-off USB printer.

## Verify

```sh
uv pip install --python .venv/bin/python -r requirements-dev.txt
.venv/bin/python -m pytest tests/test_studio.py tests/test_studio_qr.py tests/test_printer_settings.py tests/test_studio_samples.py -q
npm run build --prefix frontend
git diff --check
```

The Studio suite passes 25 tests and uses the real Python renderer and raster simulator. QR regression tests decode rendered images to verify the exact payload, including Unicode and Wi-Fi data. It covers text, QR, images, multiline rendering, high resolution, persistence, rejection of invalid input, offline printing, lock contention, roll mismatch, first-page PDF conversion, and bounded printer status reads through a pseudo-terminal. A browser pass verified editing, saved-image restoration, simulated printing, and the phone layout at 390 pixels wide.

The upstream repository suite has pre-existing failures on this Mac because some fixture fonts are absent and rendered PNG bytes differ from its reference environment. The Studio suite does not depend on those platform-specific byte snapshots.

## Raspberry Pi deployment

The native application is deployed on the Raspberry Pi 3 running 32-bit Raspberry Pi OS 12. Waitress serves the compiled frontend and Python API on port 80 at `http://labels.local/`. The physical QL-800 reports ready with 62 mm continuous media. A real HTTP preview succeeded on the Pi, and 37 renderer/storage/USB tests passed there. The three QR decoder tests run on the development machine and CI, where the optional decoder is installed. All 40 local tests pass.

The service runs as `matt` with supplementary `lp` access and the capability to bind port 80. Saved labels and configuration live outside the release directory. The original installation at `/opt/brother_ql_web` is preserved and its service is disabled. See [deployment paths and rollback commands](deploy/README.md).

The full production dependency set installed successfully on armv7l. Container builds remain unverified; this deployment uses a native virtual environment. Physical print quality, red media, and high-resolution output still require user validation. Power-off configuration read-back succeeded, but no controlled idle/power-cycle persistence test has been completed.

## Compact interface

The interface follows the [mockup](docs/design/app-mockup.png) with a desktop saved-label sidebar, a label inspector, and persistent print controls. Tablets use a narrow navigation rail and touch controls. Phones put the preview first and keep Editor, Labels, and Printer navigation at the bottom. Font sizes in mobile inputs avoid automatic iOS zoom; safe-area insets accommodate home indicators.

Save with Command/Control+S and print with Command/Control+Enter. These shortcuts are disabled while a dialog is open. Browser checks cover 1440×900, 834×1112, and 390×844 viewports. These are responsive browser checks, not tests on physical iOS hardware.

## Starter labels

A new modern library receives three editable samples on its first visit: Storage bin, Asset tag · QR, and This way up · Image. They use installed fonts and standard 62 mm black tape. The QR contains `ASSET-0042`; scanning it displays that identifier. The image is original monochrome artwork included in the project.

Samples are added once, under a filesystem lock, with fixed IDs and an initialization marker. Deleting them does not recreate them; saved edits are preserved. Libraries that already contain user labels are left alone. Set `STUDIO_SEED_SAMPLES = False` to disable initialization. Include hidden files when backing up the library so the initialization marker is retained.

To explicitly add samples to an existing library without overwriting its labels, run this from the app directory using the service account and its configuration:

```sh
.venv/bin/python -c 'from app import create_app; from app.studio import seed_starter_labels; app = create_app(); ctx = app.app_context(); ctx.push(); seed_starter_labels(add_to_existing=True)'
```

Explicit addition restores missing sample IDs but preserves existing samples, including edits.

### Shared defaults and fonts

Open **Settings** to set the default typeface, text size, orientation, roll, and margin.
The settings apply to new labels; existing saved documents retain their formatting.
New-label actions fetch the current settings so other devices pick up changes too.
The printer reports roll width and die-cut length. On the QL-800, black-only and
black/red detection was verified using physical roll swaps. New labels follow a
uniquely detected roll by default, with a five-second status refresh. Turn off
**Follow loaded roll for new labels** to use a fixed default. Saved labels and
manual choices retain their own settings; mismatched stock is rejected before
printing. See [USB status evidence](docs/usb-status.md).

Settings live in `settings.json` and downloaded/uploaded fonts in `fonts/`, next to
`STUDIO_LABELS_DIR`, or under `STUDIO_DATA_DIR` if set. With the included Pi deployment,
these are `/var/lib/label-studio/settings.json` and `/var/lib/label-studio/fonts`.
Back up the entire data directory to preserve settings, fonts, licenses, and labels.
The legacy editor keeps its own configuration defaults.

The bundled Google Fonts catalog lists 2,046 families at its recorded repository
revision. Installing a family downloads one upright regular face when available,
plus its license, directly from the official `google/fonts` repository. Variable
fonts are instantiated at normal weight for predictable rendering. Nothing is
fetched from Google by the browser. Font files remain local for offline printing.
Uploads accept TTF/OTF files up to 8 MiB and validate them with fontTools and Pillow.
Administrators can regenerate the catalog with `python tools/update_font_catalog.py`.
No Google API key is required. On macOS, Python needs a working CA certificate store;
`SSL_CERT_FILE=/etc/ssl/cert.pem` can be used with Apple's system certificates.

Brother documents black/red density adjustments from -6 to +6 in its Printer
Setting Tool, but does not describe a density command in the QL-800 raster reference.
This app does not send guessed hardware-density commands. See
[Brother's density instructions](https://support.brother.ca/app/answers/detail/a_id/159086/kw/guide).
