# Evaluating this fork

Keep a backup of the existing app, configuration, fonts, label library, and service definition. Test this branch on a separate local port in simulation mode before replacing a working printer service. See [setup](../STUDIO.md).

## What you gain

- Compact desktop editor with saved labels in the sidebar and keyboard shortcuts.
- Touch controls and a persistent print bar on phones and tablets.
- Live Python-rendered previews for text, QR codes, PNG/JPEG, and the first page of a PDF.
- Named labels, duplication, and one-copy quick printing.
- USB status timeout, shared device locking, and roll-size validation.
- QR payloads without a leading byte-order mark and with a quiet zone.

## Reasons to keep the classic editor

The modern editor does not yet expose per-line text styling, general barcodes, arbitrary mixed objects, or template editing. Those remain in the classic editor at `/labeldesigner/`. Its saved labels are separate from modern version-1 documents in `instance/studio-labels/`. There is no automatic migration that discards unsupported formatting.

No user accounts are required. This is intended for a trusted local network; do not expose the unauthenticated print service directly to the internet.

## Deployment limits

The QL-800 answered a status query with 62 mm continuous media and no errors. That does not establish print quality, red-media compatibility, or prevention of automatic power-off. The full Python dependency set still needs validation on 32-bit ARM. The Dockerfile builds React assets, but its container build was not verified locally.

Desktop and mobile screenshots show simulation mode. No new physical print was made during development. Auto Power Off can now be changed using the experimental [Linux utility](linux-power-settings.md). Its read-back was verified on one QL-800, but long-idle behavior and power-cycle persistence remain unverified. Brother's own USB utility remains the documented vendor method.

The root route opens `/studio/`; existing advanced-editor URLs continue to work. Preserve both saved-label directories and installed fonts during upgrades. To roll back, restore the previous app and service configuration; the recovered original installation was left unchanged during development.
