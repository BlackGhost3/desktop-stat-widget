# Desktop stat widget

A small always-on-top Windows widget (Python + PySide6) showing live system stats and network tools.

- CPU, GPU (any vendor, via Windows GPU counters) and RAM
- Disk read/write speed, network up/down speed with Wi-Fi or Ethernet label
- Switch the active adapter between DHCP and static IP, plus DNS presets (Cloudflare, Google, Auto, Custom) and saved profiles
- Ping tool with live latency graph, average, max and loss
- Three sizes (full, compact, mini), always-on-top toggle, adjustable opacity
- Start with Windows (menu, `⋯` button or right-click)

## Run

```bash
pip install -r requirements.txt
python app.py
```

Or double-click `run.bat`.

## Use

- Drag anywhere to move. Double-click, or press `⇱`, to cycle full, compact and mini.
- `📌` toggles always on top. `🌐` and `⚡` open the network settings and ping panels (full size only).
- Right-click for startup, opacity and quit.
- Applying IP or DNS changes asks for admin approval through a UAC prompt. The widget itself never runs elevated.

Settings and profiles are stored in `%APPDATA%\StatWidget\config.json`.

## Notes

- Windows 10/11 only. Temperatures aren't shown because Windows has no built-in API for them.
- IP/DNS detection and changes use PowerShell and `netsh`.
