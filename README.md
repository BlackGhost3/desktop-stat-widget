# Desktop stat widget

A small always-on-top Windows widget (Python + PySide6) showing live system stats and network tools.

- CPU, GPU (any vendor, via Windows GPU counters) and RAM
- Disk read/write speed, network up/down speed with Wi-Fi or Ethernet label
- Switch the active adapter between DHCP and static IP, plus DNS presets (Cloudflare, Google, Auto, Custom) and saved profiles
- Ping tool with live latency graph, average, max and loss
- Three sizes (full, compact, mini), always-on-top toggle, adjustable opacity with optional fade when the cursor is away
- Update check and one-click install from GitHub releases (the menu shows "Update to vX.Y.Z" when one is available)
- Start with Windows (menu button or right-click)

## Run

```bash
pip install -r requirements.txt
python app.py
```

Or double-click `run.bat`.

## Use

- Drag anywhere to move. Double-click, or press the resize icon, to cycle full, compact and mini.
- The pin icon toggles always on top. The grid icon opens a list to show the network settings and ping panels (full and compact sizes).
- Right-click, or use the dots icon, for startup, opacity, fade when the cursor is away, and quit.
- Applying IP or DNS changes asks for admin approval through a UAC prompt. The widget itself never runs elevated.

## Publishing an update

Bump `VERSION` in `updater.py`, push, then create a release whose tag is the new version:

```bash
gh release create v1.1.0 --title "v1.1.0" --notes "What changed"
```

The widget checks on launch and from the menu. Installing downloads the release source, replaces the `.py`, `.txt`, `.bat` and `.md` files, and restarts. A git checkout is never overwritten; the widget opens the release page instead.

Settings and profiles are stored in `%APPDATA%\StatWidget\config.json`.

## Notes

- Windows 10/11 only. Temperatures aren't shown because Windows has no built-in API for them.
- IP/DNS detection and changes use PowerShell and `netsh`.
