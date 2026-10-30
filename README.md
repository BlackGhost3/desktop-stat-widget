# Desktop stat widget

A small always-on-top Windows widget (Python + PySide6) showing live system stats, with network tools built in.

![Full size](docs/full.png) ![Mini strip](docs/mini.png)

## Features

**Monitoring**
- CPU, GPU (any vendor, via Windows GPU counters) and RAM, with an optional GPU switch to save resources
- Disk read/write speed, free space per drive, network up/down speed with a Wi-Fi or Ethernet label
- Local and public IP (public IP is looked up through api.ipify.org every 5 minutes). Click either to copy it
- VPN badge when a VPN adapter (WireGuard, OpenVPN, Tailscale and similar) is up
- Battery and power plan on laptops
- Click CPU or RAM to see the top processes and end one

**Network tools** (grid icon)
- Network settings: switch the active adapter between DHCP and static IP, DNS presets (Cloudflare, Google, Auto, Custom), saved profiles
- Ping with a live latency graph, average, max and loss
- Connection history: a graph of the last hour of pings to 1.1.1.1
- Speed test against Cloudflare with a live Speedtest-style gauge for download and upload (about 45 MB of data per run)

**Alerts** (Windows notifications from a tray icon)
- CPU or RAM above 90% for 30 seconds, a drive under 10% free, connection lost, packet loss, low battery
- A saved network profile matches the network you're on (you review and apply it yourself)

**Appearance and behavior**
- Three sizes: full, compact, mini strip
- Dark, light or follow-Windows theme, five accent colors
- Always-on-top toggle, opacity, fade when the cursor is away, snap to screen edges
- Choose which stats are shown, including in the mini strip
- Show or hide with Ctrl+Alt+W
- Start with Windows
- Update check and one-click install from GitHub releases

## Run

```bash
pip install -r requirements.txt
python app.py
```

Or double-click `run.bat`.

## Use

- Drag anywhere to move. Double-click, or press the resize icon, to cycle full, compact and mini.
- The pin icon toggles always on top. The grid icon opens the tools list, one panel at a time.
- Right-click, or use the dots icon, for Appearance, Show, Behavior, updates and quit.
- Applying IP or DNS changes asks for admin approval through a UAC prompt. The widget itself never runs elevated.

Settings and profiles are stored in `%APPDATA%\StatWidget\config.json`.

![Network settings](docs/network.png) ![Light theme with processes](docs/light-processes.png)

## Publishing an update

Bump `VERSION` in `updater.py`, push, then create a release whose tag is the new version:

```bash
gh release create v1.1.0 --title "v1.1.0" --notes "What changed"
```

The widget checks on launch and from the menu. Installing downloads the release source, replaces the `.py`, `.txt`, `.bat` and `.md` files, and restarts. A git checkout is never overwritten; the widget opens the release page instead.

## Notes

- Windows 10/11 only. Temperatures aren't shown because Windows has no built-in API for them.
- IP/DNS detection and changes use PowerShell and `netsh`.
- Outside requests: api.ipify.org (public IP), ping to 1.1.1.1 (connection monitor, can be turned off), GitHub (updates), Cloudflare (speed test, only when you run it).
- The screenshots use placeholder IP addresses.
