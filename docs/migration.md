# Upgrading to Label Studio

Back up the existing configuration, fonts, label library, and service definition before replacing an older installation. See [installation](../STUDIO.md) and [Raspberry Pi deployment](../deploy/README.md).

Studio is the only editor. It supports rich text, line spacing, individual margins, QR codes, barcodes, images, and CSV templates. The root URL and old `/labeldesigner/` bookmarks open Studio.

The classic editor's repository, preview, print, barcode-list, and printer-discovery APIs have been removed. Integrations using those routes must switch to the Studio API. The authenticated image-printing webhook remains at `/labeldesigner/api/webhook/print` with its existing request format.

Studio labels are stored in `STUDIO_LABELS_DIR`; preferences and fonts live under `STUDIO_DATA_DIR`. Existing classic label files are not deleted or imported. Keep an older installation and its backup if you need to access that format. Studio labels and bulk templates retain their own paper and formatting settings.

Production installations use the Rust server binary and built React files. See [the installation guide](../STUDIO.md).
