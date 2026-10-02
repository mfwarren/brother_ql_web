# QL-800 auto power-off from Linux

The QL-800 tested on 2026-09-28 accepted a Linux-only change from 60 minutes to disabled. No Mac or Windows utility, firmware replacement, or kernel driver modification was used. This is an experimental device-setting utility, not a general Brother settings editor.

## Run

The Rust server binary includes a settings command for `/dev/usb/lp0`. The printer must be powered on, idle, and in normal USB printer mode.

Stop any printing service that does not share the Studio lock before running it. Restore services afterward, including if the utility fails. Do not run this concurrently with CUPS, another driver, or another printer-settings utility.

```sh
LABEL_STUDIO_CONFIG=/etc/label-studio/application.json label-studio-server power-get
LABEL_STUDIO_CONFIG=/etc/label-studio/application.json label-studio-server power-set 0
```

`0` disables automatic shutdown. Values 10, 20, 30, 40, 50, and 60 select minutes. Only 60 and 0 were observed on this QL-800; other values follow the QL-700 encoding and are not yet hardware-tested here. The command validates the QL-800 status header, idle/error state, setting acknowledgement, and range before any setting write. A value already set is not rewritten. Every write is followed by a read-back; failed verification is reported as uncertain, not success.

The lock is `printer.lock` in the configured data directory. Use the same `LABEL_STUDIO_CONFIG` as the service so both commands share the device and lock. Set `PRINTER_PRINTER` and `STUDIO_DATA_DIR` together when using environment overrides. Advisory locking only coordinates software using the same lock. The utility does not detach the kernel driver, reset the printer, print a label, or enumerate unknown commands.

## Evidence and protocol

Marc Schütze independently reverse-engineered this command family from the QL-700 Windows utility and published [a Linux implementation](https://github.com/marc-schuetze/brother-ql700-settings) and [research notes](https://marc.schuetze.io/blog/brother-ql700-auto-power-off/). His code is MIT licensed. This utility implements the specific protocol independently through Linux usblp and credits that discovery.

We tested only the auto-power-off selector on a QL-800 with USB ID `04f9:209b`:

| Operation | Bytes |
| --- | --- |
| Ordinary status request | `1b 69 53` |
| Read auto power-off | `1b 69 55 41 01` |
| Set disabled | `1b 69 55 41 00 00` |

The settings reply is 32 bytes, starts `80 20 42 34 38 30`, has status type `f0` at offset 18, value at offset 30, and acknowledgement `01` at offset 31. Values encode ten-minute units: `06` is 60 minutes and `00` disables automatic shutdown.

A first attempt exposed empty nonblocking reads and stale queued responses. The final transport tolerates transient empty reads, drains queued bytes before a transaction, and bounds all reads and writes. Pseudo-terminal tests cover fragmented replies, stale replies, timeout, and the precise setting write sequence.

## What remains unverified

Read-back establishes that the device reports the new value. An idle interval longer than 60 minutes without printing or polling, and a subsequent physical power cycle, must establish behavioral effect and persistence on this QL-800. No automatic keep-alive is used as a substitute. Other models and other power settings are not supported. The utility cannot wake a printer that is already powered off.

Do not scan the undocumented command namespace: the original researcher observed unexpected setting changes during such scans. The implemented tool permits only the known auto-power-off selector.
