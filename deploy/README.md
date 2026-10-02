# Raspberry Pi deployment

Build the Rust server and React bundle using [STUDIO.md](../STUDIO.md). The runtime needs FreeType, installed fonts, and Poppler for PDFs. It does not need Python, Node, or Cargo.

## Files and data

- `/opt/label-studio/releases/<version>` contains the server binary and `app/static/studio` bundle.
- `/opt/label-studio/current` points to the active release.
- `/etc/label-studio/application.json` holds host configuration.
- `/var/lib/label-studio/labels` contains saved labels.
- `/var/lib/label-studio/fonts` and `settings.json` contain installed fonts and shared defaults.
- `/var/lib/label-studio/printer.lock` coordinates printer access.

Copy [application.json.example](application.json.example) to the configuration path. Set the model, device, and data paths. Preserve any `classic-labels` directory as an archive; the server does not modify it.

Copy [label-studio.service](label-studio.service) to `/etc/systemd/system/`. Change `User=matt` and `Group=matt` to your service account. That account needs access to the printer through the `lp` group, read access to program/configuration files, and write access to its data directory. Place `label-studio-server` at the root of the release directory.

```sh
sudo systemctl daemon-reload
sudo systemctl enable --now label-studio
sudo systemctl status label-studio
```

Open `http://<pi-hostname>.local/`. The service grants permission to bind port 80 without running as root.

## Upgrades and rollback

Back up `/var/lib/label-studio`, `/etc/label-studio`, and the service definition. Build a new release in its own directory. Run it on a temporary port with a **copy** of the data and `PRINTER_PRINTER=simulation` before changing `current`. Check library previews, fonts, and the editor. Then switch `current` and restart the service.

When moving from Python, the existing saved-label JSON, font manifests, and shared defaults remain usable. Translate `application.py` into `application.json`; the Rust server does not execute Python configuration. Keep the previous release and service file for rollback. Do not print during the switch.

```sh
sudo journalctl -u label-studio -n 50 --no-pager
sudo systemctl restart label-studio
```

Use this service only on a trusted network. It has no user accounts; anyone who can reach it can print and change settings.
