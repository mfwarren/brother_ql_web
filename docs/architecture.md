# Code structure

The React frontend keeps the current draft and navigation in `frontend/src/App.tsx`. Content, paper settings, and preview components live under `frontend/src/editor/`. `useLabelPreview.ts` owns debouncing, cancellation, image decoding, and object-URL cleanup. Bulk editing uses the same editor and preview.

The Rust server lives in `server/`:

- `api.rs` handles HTTP requests, response formats, and background work.
- `validation.rs` checks drafts and formatting at the API boundary.
- `storage.rs` saves JSON atomically and seeds the sample library once.
- `rendering.rs` lays out text, QR codes, barcodes, images, and PDFs. Its legacy text path preserves older labels' ink-based spacing.
- `fonts.rs` discovers fonts and manages downloaded/uploaded variable fonts without converting their outlines.
- `bulk.rs` parses CSV and substitutes literal fields while preserving text styles.
- `remote_images.rs` fetches bounded public HTTPS images, validates every redirect, and pins the resolved destination.
- `media.rs` contains printer and roll profiles.
- `printer.rs` generates Brother raster commands, decodes status, checks media, and sends jobs over USB or TCP.
- `power.rs` implements the QL-800 power-setting utility.
- `webhook.rs` handles the optional authenticated image webhook.
- `config.rs` loads JSON host configuration and environment overrides.

The printer lock covers media checks and submission. Bulk jobs validate every raster before sending anything, and write a submission record before the first send. A failed or interrupted submitted job cannot be retried with the same job ID.

Rendering and driver fixtures test output against the Python implementation. Rust unit tests also cover variable fonts, media detection, USB framing, deadlines, CSV substitution, remote-image address restrictions, and locking. The previous Python implementation is available in Git history. Python is used only by optional development verification and asset-generation tools; it is not invoked by the Rust process.
