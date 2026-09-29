# Raspberry Pi deployment

This installation uses prebuilt React assets and a native Python virtual environment on Raspberry Pi OS 12, armv7l. Node is only needed on the build machine. Install `requirements-server.txt` and use `serve.py` for the Waitress production server.

The provided service template uses the local `matt` user, supplementary `lp` group, and only the capability needed to bind port 80. Adjust the user for another machine. Configuration is kept in `/etc/label-studio/application.py`, symlinked from the release's `instance/application.py`.

## Installed layout

- `/opt/label-studio/current`: symlink to the active release.
- `/opt/label-studio/releases/20260929-8d15bb4`: initial deployed release, based on commit 8d15bb4 plus deployment changes. `DEPLOYED_COMMIT` records the final source commit.
- `/var/lib/label-studio/labels`: modern saved labels.
- `/var/lib/label-studio/classic-labels`: classic saved labels.
- `/var/lib/label-studio/printer.lock`: shared physical-printer lock.
- `/etc/systemd/system/label-studio.service`: production service.
- `/opt/brother_ql_web`: preserved original installation.

The listener is port 80 and the physical printer is `file:///dev/usb/lp0`. The webhook remains disabled. During preparation, the candidate server runs only on loopback port 8020 in simulation mode.

## Operations

```sh
sudo systemctl status label-studio
sudo journalctl -u label-studio -n 50 --no-pager
sudo systemctl restart label-studio
```

Back up `/var/lib/label-studio` and `/etc/label-studio` before upgrades. Build and validate a new release separately, then switch the `current` symlink and restart. Avoid printing during a release switch.

## Roll back to the original app

```sh
sudo systemctl disable --now label-studio.service
sudo systemctl enable --now brother_ql_web.service
```

This restores the original port-80 app. It does not delete modern labels or change the printer's Auto Power Off setting. To switch back:

```sh
sudo systemctl disable --now brother_ql_web.service
sudo systemctl enable --now label-studio.service
```

UI preferences and installed fonts persist alongside the label library in
`/var/lib/label-studio/settings.json` and `/var/lib/label-studio/fonts/`. Include
both in backups. No extra deployment configuration is needed. Set `STUDIO_DATA_DIR`
only when these should live somewhere other than the parent of `STUDIO_LABELS_DIR`.
