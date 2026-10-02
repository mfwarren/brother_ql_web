# Code structure

The frontend keeps the current draft and navigation in `frontend/src/App.tsx`. Content, paper settings, and the preview are separate components under `frontend/src/editor/`. `useLabelPreview.ts` owns debouncing, cancellation, image decoding, and object-URL cleanup; it retains the last image while a new render loads. Bulk editing uses the same content panel and preview.

Backend responsibilities:

- `studio.py`: HTTP endpoints and response formatting.
- `studio_api.py`: shared blueprint, JSON request limits, and input-error responses.
- `validation.py`: label and field validation.
- `label_store.py`: saved labels, atomic JSON writes, and sample seeding.
- `rendering.py`: validated drafts to printable labels, without converting them through form fields.
- `label_geometry.py`: printable dimensions, orientation, and margins.
- `text_rendering.py`: one entry point for text normalization and rendering. A small compatibility path preserves the original spacing and placement of older plain labels without rewriting stored files.
- `rich_text.py`: formatted text layout and rasterization.
- `printer_service.py`: device selection, printer locking, and status interpretation.
- `printing.py`: media checks, queue submission, and bulk-job duplicate protection.
- `labeldesigner/`: the shared raster/USB backend and the authenticated image webhook.

The printer lock covers media checks and submission. Bulk jobs validate every raster before sending anything, and write a submission record before the first send. A failed or interrupted submitted job cannot be silently retried with the same job ID.

For rendering refactors, capture a baseline with `python tools/render_reference.py capture /tmp/render.json`, make the change, then run `python tools/render_reference.py compare /tmp/render.json`. Use the same host and installed fonts for both runs. The tool compares PNG hashes across paper, orientation, resolution, and content variants; it never sends labels to a printer.
