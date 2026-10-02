# Raster compatibility fixtures

These PNG inputs and `.bin` expected outputs were generated with the existing
`brother_ql-inventree==1.3` driver before replacing it. `cases.json` records the
model, paper and conversion options. All cases use `cut=True`, `rotate=0` for
continuous media and `rotate='auto'` for die-cut media.

The inputs use black and red stripes (three dots each in a 17-dot repeat), or a
 grayscale ramp `(x * 17 + y * 29) % 256` for the dithering case. They cover
one- and two-plane raster packets, automatic die-cut rotation, 600 dpi, QL/PT
commands and printer-specific margins. The fixtures require no printer.

Printer/media/status definitions in `server/data` are transcribed from
brother_ql-inventree 1.3, retaining its GPL-3.0 license. The power-setting
protocol derives from Marc Schuetze's MIT-licensed brother-ql700-settings,
with QL-800 status validation observed on the physical printer.
