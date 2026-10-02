# Rust backend migration

- [x] Read workflow principles and inventory existing behavior.
- [ ] Capture API/render reference fixtures before implementation.
- [ ] Port rendering, font management, printer transport, and HTTP services across separate modules.
- [ ] Verify each module with behavior tests, then compare end-to-end API output.
- [ ] Update production packaging and deployment configuration.
- [ ] Verify on Raspberry Pi before replacing the Python service.

Done means the React application uses a Rust process for every server endpoint, existing saved labels/fonts/settings load, text/QR/barcode/image and bulk workflows pass compatibility checks, and printer status/raster output pass checks without an unsolicited physical print. Preserve the legacy text layout. Python remains a reference until those checks pass.

The migration covers roughly 25 backend modules and 20 HTTP routes. The highest risks are font metrics, raster commands, and ARM deployment. Work stays on a feature branch until integrated verification succeeds.
