# Raspberry Pi deployment

The tested host is a Raspberry Pi 3 running 32-bit Raspberry Pi OS 12. Follow [STUDIO.md](../STUDIO.md) to install system dependencies, extract the release archive, create a virtual environment, and test the simulator first. Use `requirements-server.txt` and `serve.py` for Waitress. Node is only required on a frontend build machine.

## Production layout

A suggested layout separates program files from persistent data:

- `/opt/label-studio/releases/<version>`: extracted release and its `.venv`.
- `/opt/label-studio/current`: symlink to the active release.
- `/etc/label-studio/application.py`: host configuration.
- `/var/lib/label-studio/labels`: modern label library.
- Older installations may have `/var/lib/label-studio/classic-labels`. Keep it as an archive; Studio does not use or modify it.
- `/var/lib/label-studio/fonts` and `settings.json`: installed fonts and defaults.
- `/var/lib/label-studio/printer.lock`: shared printer lock.

Create these directories with ownership appropriate to your service account. Copy [application.py.example](application.py.example) to `/etc/label-studio/application.py`, then review the printer model, USB device, and data paths. Create `instance/` inside the release and symlink `instance/application.py` to that configuration file. Set `STUDIO_DATA_DIR = '/var/lib/label-studio'` if using a different label-directory layout.

## Port 80 service

Copy [label-studio.service](label-studio.service) to `/etc/systemd/system/label-studio.service`. **Change `User=matt` and `Group=matt` to your service account**, and adjust paths if needed. The account needs read access to the release and configuration, write access to `/var/lib/label-studio`, and access to the printer device. The template grants supplementary `lp` membership and the capability to bind port 80 without running the application as root.

```sh
sudo systemctl daemon-reload
sudo systemctl enable --now label-studio
sudo systemctl status label-studio
```

Open `http://<pi-hostname>.local/studio/`, or use its IP address. `.local` discovery requires working mDNS on your network. If another web server already occupies port 80, choose another port or configure that server as a proxy.

## Operations and upgrades

```sh
sudo journalctl -u label-studio -n 50 --no-pager
sudo systemctl restart label-studio
```

Back up `/var/lib/label-studio` and `/etc/label-studio` before upgrades, including hidden sample-initialization files. Extract a new release into a new directory, create its virtual environment and configuration symlink, and validate it in simulation before switching `current` and restarting. Avoid printing during the switch. Keep the previous release so you can restore its symlink and restart if needed.

When migrating from an older Brother QL Web installation, retain its files, service definition, and label library until the new service is verified. Stop the old listener before starting the new port-80 service. The classic and Studio libraries are separate; see [migration tradeoffs](../docs/migration.md).

The app has no user accounts and is intended for a trusted local network. Do not forward its port to the public internet. The webhook endpoint is disabled unless explicitly configured.
