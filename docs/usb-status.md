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

The decoder recognizes the positive two-color flag as `media_color=black-red`.
A controlled QL-800 roll swap also verified `0x01` as black-only and `0x81` as
black/red. Only the QL-800 uses this verified black-only value; other models and
unrecognized values remain unknown. Unknown stock retains manual confirmation.
The app rejects a job whose selected color mode conflicts with detected stock.

## Roll-change verification

Read-only USB captures with the owner identifying each loaded roll:

| Roll | Status frame (hex) | Dimensions |
| --- | --- | --- |
| 29 × 90 mm die-cut | `802042343830000000001d0b00000100005a0000000000000001000000000000` | 29 × 90 mm |
| 62 mm black-only continuous | `802042343830000000003e0a0000150000000000000000000001000000000000` | 62 mm, continuous |
| 62 mm black/red continuous | `802042343830000000003e0a0000230000000000000000000081000000000000` | 62 mm, continuous |

New labels follow a uniquely detected roll when `autoDetectRoll` is enabled in
shared settings. The UI checks every five seconds without overlapping requests.
Saved labels and explicit manual roll choices retain their size. Detection does
not overwrite saved records or the fallback size. The loaded dimensions include
the length for die-cut stock; continuous stock has no fixed length.

## Print preflight

The editor shows a paper-mismatch warning and disables Print when the detected
width, die-cut length, or ink-color mode differs from the selected label. The
saved-label library marks incompatible labels and disables their quick-print
buttons. Unknown color still uses the existing explicit red-stock confirmation.

Every physical print first refreshes status in the browser. The server then
queries the printer again under its shared device lock, before rendering or
sending the job. A roll swap after the browser's last status update is rejected
without sending print data. The checks apply to library printing and keyboard
shortcuts as well as the editor button.
