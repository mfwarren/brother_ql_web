# Formatted text and native fonts

Text labels support inline fonts, bold, italic, and sizes from 8–200 printer pixels. Select text and use the compact toolbar. The default size applies to runs without an explicit size. Font and numeric pixel size live in the text toolbar and apply to the selection or subsequent typing. Alignment, ink, paper, orientation, and margins apply to the entire label. The preview viewport keeps a fixed height while rendering. The server preview shows the final layout; the browser editor is an editing surface, not a paper-sized canvas.

Saved text retains its plain `text` field and optionally adds `paragraphs`, an array of `{runs: [{text, font?, size?, bold?, italic?}]}`. The server validates both representations agree. Existing plain-text labels keep their original rendering path until edited. Formatted labels wrap to printable width and report overflow instead of silently clipping. Pillow renders the runs into an image, which uses the existing Brother raster, rotation, media-check, and print pipeline.

Google Fonts installs retain the original variable TTF files. A small `faces.json` manifest maps weights and italics to FreeType variation coordinates. No static-font conversion is needed. Regular (400) is selected after installation. Available weights and italic faces appear in the typeface selector. Families lacking an actual bold or italic face report a preview error when that style is requested.

Reinstalling a legacy Google family upgrades it once. `aliases.json` maps misleading old family names (such as Montserrat Thin,Regular) to the proper Regular face so existing defaults and saved labels continue to resolve. Original files are preserved. Subsequent installs use the cached manifest. Uploaded variable TTFs use the same native renderer; separate italic files must be supplied if the font has no italic axis.

Measured on the Raspberry Pi 3: the old Montserrat conversion took about 72 seconds; native installation took 1.2 seconds, including normal and italic files. Source Sans 3 and Roboto took about 1.3 seconds each. Network conditions and family size can change download times.

Verification covers unchanged downloaded bytes, variation axes and actual ink changes, restart persistence, legacy-name migration, formatting serialization, saved-label preview equality, simulated printing, wrapping, malformed content, and overflow. Physical output still needs user evaluation with the loaded roll.
