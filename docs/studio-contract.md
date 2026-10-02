# Studio HTTP API

The Rust server serves the React app at `/studio/` and its API at `/studio/api`. `/` and `/labeldesigner/` redirect to Studio. Printer selection and simulation mode are server configuration, not client overrides.

## Endpoints

Paths below are relative to `/studio/api`. JSON errors contain `message` and an appropriate HTTP error status. Preview success returns `image/png` with `Cache-Control: no-store`.

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/config` | Printer model, mode, installed font faces, supported paper profiles, and shared defaults |
| GET | `/status` | Printer state, detected media, color, and matching paper profile IDs when available |
| POST | `/preview` | Render a label draft |
| POST | `/print` | Print `{draft, copies, cut, confirmRedMedia?}`; copies 1–100, cut `each` or `end` |
| GET / POST | `/labels` | List saved labels or save `{name, draft}` with a new UUID |
| GET / PUT / DELETE | `/labels/{id}` | Read, replace with `{name, draft}`, or delete one saved label |
| PUT | `/settings` | Save shared font, sizeId, orientation, margin, fontSize, and autoDetectRoll defaults |
| POST | `/bulk/prepare` | Expand `{template, csv?, count?, timezone?}` into ready/error rows and a job ID |
| POST | `/bulk/print` | Print `{jobId, drafts, cut}`; 1–100 drafts using the same paper and resolution |
| POST | `/bulk/image` | Fetch an image from a bounded public HTTPS URL |
| GET | `/fonts/catalog` | List installable Google Fonts families |
| GET | `/fonts/file?font=...` | Retrieve an installed font file |
| POST | `/fonts/install` | Install the catalog family identified by `{id}` |
| POST | `/fonts/upload` | Install a font supplied as a multipart file |

Bulk substitution and error reporting are described in [bulk printing](bulk-printing.md). The compatibility image webhook remains at `/labeldesigner/api/webhook/print`, accepts JSON or multipart images, and requires the configured webhook password. It is disabled when no password is configured. Its processing failures retain HTTP 400 for existing integrations.

## Drafts and persistence

A draft contains `content`, `sizeId`, `orientation`, `font`, `fontSize`, `align`, `color`, `margin`, and `highRes`. Optional `verticalAlign`, `lineSpacing`, and four-sided `margins` refine text layout. Content is one of text, QR code, barcode, or image. Text can contain formatted paragraphs and runs; see [rich text and fonts](rich-text-and-fonts.md).

Fonts must resolve to installed faces. Paper must be supported by the configured printer model. Font size is 8–200 printer pixels, margins are 0–100 pixels, and line spacing is 100–300 percent. Red ink requires `62red` media, which cannot use high resolution. Uploaded label images support PNG, JPEG, and PDF with a 5 MiB file limit and decoded-image bounds. Barcodes support Code 128, EAN-13, EAN-8, and UPC-A.

Saved labels are versioned JSON documents containing `id`, `name`, `updatedAt`, and `draft`. Writes use an atomic replacement. The configured data directory holds settings and installed fonts; `labelsDir` can select a separate label directory. Existing plain-text labels retain their original layout, and font aliases keep saved labels usable after font upgrades. These compatibility paths support current saved data.

## Resource and print safeguards

Dynamic routes admit four simultaneous requests before buffering bodies; excess requests receive HTTP 503 and `Retry-After: 1`. Upload bodies time out after 30 seconds without incoming data. Two background workers bound CPU-heavy operations. Prepared CSV output is limited to 7 MiB and placeholder expansion is bounded before allocation.

Printing checks the loaded media under the shared printer lock. Bulk jobs validate all pages before sending, and record submission before the first printer write. Reusing a submitted job ID is rejected so an uncertain result cannot silently print twice. The simulation mode renders and saves output without touching the printer.

Run the external HTTP checks in [STUDIO.md](../STUDIO.md) to verify rendering, validation, saved-document round trips, fonts, CSV batches, and print safeguards against a disposable simulation server.
