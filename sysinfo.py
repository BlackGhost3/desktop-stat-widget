"""System data collectors: CPU/RAM/disk/network speeds, GPU load, adapter config, ping."""
import json
import re
import subprocess
import threading
import time

import psutil

NO_WINDOW = 0x08000000  # CREATE_NO_WINDOW


def _ps(script, timeout=20):
    out = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True, text=True, timeout=timeout, creationflags=NO_WINDOW,
    )
    return out.stdout.strip()


class GpuReader(threading.Thread):
    """Persistent PowerShell loop reading Windows GPU engine counters (any vendor)."""

    SCRIPT = (
        "while($true){try{"
        "$s=(Get-Counter '\\GPU Engine(*)\\Utilization Percentage' -ErrorAction Stop).CounterSamples;"
        "$g=$s|Group-Object {$_.InstanceName -replace '^pid_\\d+_',''};"
        "$m=($g|ForEach-Object{($_.Group|Measure-Object CookedValue -Sum).Sum}|Measure-Object -Maximum).Maximum;"
        "[int][math]::Min(100,$m)}catch{-1};Start-Sleep -Milliseconds 500}"
    )

    def __init__(self):
        super().__init__(daemon=True)
        self.value = -1
        self._proc = None

    def run(self):
        try:
            self._proc = subprocess.Popen(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", self.SCRIPT],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
                creationflags=NO_WINDOW,
            )
            for line in self._proc.stdout:
                try:
                    self.value = int(line.strip())
                except ValueError:
                    pass
        except OSError:
            self.value = -1

    def stop(self):
        if self._proc:
            self._proc.kill()


class Rates:
    """Turns cumulative byte counters into per-second rates."""

    def __init__(self):
        self.last = None

    def update(self, disk, net):
        now = time.time()
        cur = (disk.read_bytes, disk.write_bytes, net.bytes_recv, net.bytes_sent)
        if self.last is None:
            self.last = (now, cur)
            return 0, 0, 0, 0
        t0, prev = self.last
        dt = max(now - t0, 0.001)
        self.last = (now, cur)
        return tuple(max(0, (c - p) / dt) for c, p in zip(cur, prev))


NET_SCRIPT = r"""
$r = Get-NetRoute -DestinationPrefix 0.0.0.0/0 -ErrorAction SilentlyContinue | Sort-Object RouteMetric | Select-Object -First 1
if (-not $r) { '{}'; exit }
$i = $r.InterfaceIndex
$ip = Get-NetIPAddress -InterfaceIndex $i -AddressFamily IPv4 | Select-Object -First 1
$dhcp = (Get-NetIPInterface -InterfaceIndex $i -AddressFamily IPv4).Dhcp
$dns = (Get-DnsClientServerAddress -InterfaceIndex $i -AddressFamily IPv4).ServerAddresses
$a = Get-NetAdapter -InterfaceIndex $i
[pscustomobject]@{alias=$a.Name; media=[string]$a.PhysicalMediaType; ip=$ip.IPAddress; prefix=$ip.PrefixLength; gateway=$r.NextHop; dhcp=("$dhcp" -eq 'Enabled'); dns=@($dns)} | ConvertTo-Json -Compress
"""


def read_net_config():
    try:
        return json.loads(_ps(NET_SCRIPT) or "{}")
    except (ValueError, subprocess.SubprocessError, OSError):
        return {}


def link_kind(cfg):
    text = f"{cfg.get('media', '')} {cfg.get('alias', '')}".lower()
    return "Wi-Fi" if ("802.11" in text or "wi-fi" in text or "wireless" in text) else "Ethernet"


def ping_once(target, timeout_ms=1000):
    """Returns latency in ms, or None on timeout/failure."""
    try:
        out = subprocess.run(
            ["ping", "-n", "1", "-w", str(timeout_ms), target],
            capture_output=True, text=True, timeout=timeout_ms / 1000 + 3,
            creationflags=NO_WINDOW,
        ).stdout
    except (subprocess.SubprocessError, OSError):
        return None
    m = re.search(r"time[=<]\s*(\d+)\s*ms", out)
    return float(m.group(1)) if m else None
