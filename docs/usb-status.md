# Linux USB status and completion

The QL-800 can remain in the printing phase after an interrupted job. On
2026-09-29 its status reply was `80 20 42 34 38 30 00 00 00 00 3e 0a 00 00 15 00
00 00 00 01 00 00 00 00 00 01 00 00 00 00 00 00`: no application lock and no
printer errors, but phase byte 19 was 1. Logs showed a print-completion timeout
and subsequent cover-open events. It later returned to receiving phase 0.
The evidence does not identify which event originally interrupted the job.

The upstream Linux sender used one unchecked `os.write` and a 10-second completion
window. The application now uses nonblocking writes until every byte is accepted,
reassembles partial status frames, skips unsolicited notifications when requesting
fresh status, closes the descriptor on all outcomes, and tracks completion and
ready acknowledgements for every job in the batch. The deadline is 90 seconds per
job. An uncertain result is never automatically reprinted. If the printer remains
busy after the paper has stopped moving, power-cycle it before retrying.

## Tape color

Brother's public [QL-800 raster reference](https://download.brother.com/welcome/docp100278/cv_ql800_eng_raster_101.pdf)
marks status bytes 24–31 reserved. The independent
[thermal-label QL protocol implementation](https://thermal-label.github.io/brother-ql/protocol/ql)
reports bit 7 of byte 25 as the two-color-roll flag on QL-800/810W/820NWB.

The decoder now exposes this positive flag as `media_color=black-red`. This makes
the UI identify `62red`, offers the exact detected roll in Settings, rejects a
black-only job configuration for detected red stock, and removes the manual
red-media confirmation when detected. A clear flag remains **unknown**, not an
assertion that monochrome stock is loaded. The captured printer response above
has byte 25 = 01, so it does not positively report red stock. A controlled capture
with a known black/red roll is still needed to verify the flag on this printer's
firmware. Unknown stock retains the manual confirmation.
