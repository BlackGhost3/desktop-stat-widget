"""Background helpers: speed test, top processes, connection monitor, alert rules, power info."""
import http.client
import subprocess
import threading
import time
import urllib.parse
import urllib.request
from collections import deque

import psutil

import sysinfo

UA = {"User-Agent": "desktop-stat-widget"}
DOWN_URL = "https://speed.cloudflare.com/__down?bytes=40000000"
UP_URL = "https://speed.cloudflare.com/__up"
PROTECTED = {"system", "registry", "smss.exe", "csrss.exe", "wininit.exe", "winlogon.exe", "services.exe",
             "lsass.exe", "svchost.exe", "dwm.exe", "explorer.exe", "fontdrvhost.exe", "memcompression"}


def run_speedtest(status, live):
    """Blocking test against Cloudflare. status(text) reports the stage, live(phase, mbps) the running speed."""
    status("Measuring ping…")
    live("ping", 0)
    ping = sysinfo.ping_once("1.1.1.1")
    status("Testing download…")
    start, got, last = time.time(), 0, 0.0
    with urllib.request.urlopen(urllib.request.Request(DOWN_URL, headers=UA), timeout=15) as resp:
        while time.time() - start < 8:
            chunk = resp.read(65536)
            if not chunk:
                break
            got += len(chunk)
            if time.time() - last > 0.15 and time.time() - start > 0.4:
                last = time.time()
                live("down", got * 8 / (last - start) / 1e6)
    down = got * 8 / max(time.time() - start, 0.001) / 1e6
    live("down", down)
    status("Testing upload…")
    total, chunk = 6_000_000, bytes(65536)
    conn = http.client.HTTPSConnection(urllib.parse.urlparse(UP_URL).netloc, timeout=30)
    try:
        conn.putrequest("POST", "/__up")
        conn.putheader("User-Agent", UA["User-Agent"])
        conn.putheader("Content-Type", "application/octet-stream")
        conn.putheader("Content-Length", str(total))
        conn.endheaders()
        t0, sent, last = time.time(), 0, 0.0
        while sent < total:
            piece = chunk[:min(len(chunk), total - sent)]
            conn.send(piece)
            sent += len(piece)
            if time.time() - last > 0.15 and time.time() - t0 > 0.4:
                last = time.time()
                live("up", sent * 8 / (last - t0) / 1e6)
        conn.getresponse().read()
        up = total * 8 / max(time.time() - t0, 0.001) / 1e6
    finally:
        conn.close()
    live("up", up)
    return {"ping": ping, "down": down, "up": up}


class ProcSampler:
    """Top processes grouped by name (so a browser's many processes show as one row)."""

    def __init__(self):
        self.cache, self.names = {}, {}
        self.ncpu = psutil.cpu_count() or 1

    def top(self, by="cpu", n=5):
        seen, groups = set(), {}
        for p in psutil.process_iter(["pid", "name"]):
            pid = p.info["pid"]
            seen.add(pid)
            proc = self.cache.get(pid)
            if proc is None:
                self.cache[pid] = p
                self.names[pid] = p.info["name"] or str(pid)
                try:
                    p.cpu_percent(None)
                except psutil.Error:
                    pass
                continue
            if pid == 0:
                continue
            try:
                cpu, mem = proc.cpu_percent(None) / self.ncpu, proc.memory_info().rss
            except psutil.Error:
                continue
            g = groups.setdefault(self.names[pid], {"name": self.names[pid], "cpu": 0.0, "mem": 0, "pids": []})
            g["cpu"] += cpu
            g["mem"] += mem
            g["pids"].append(pid)
        for pid in set(self.cache) - seen:
            self.cache.pop(pid, None)
            self.names.pop(pid, None)
        return sorted(groups.values(), key=lambda g: g[by], reverse=True)[:n]


def end_processes(pids):
    """Terminates the given pids. Returns how many couldn't be ended."""
    failed = 0
    for pid in pids:
        try:
            psutil.Process(pid).terminate()
        except psutil.NoSuchProcess:
            pass
        except psutil.Error:
            failed += 1
    return failed


class Pinger(threading.Thread):
    """Pings one target every few seconds and keeps the last hour of results."""

    def __init__(self, target="1.1.1.1", interval=5.0, size=720):
        super().__init__(daemon=True)
        self.target, self.interval = target, interval
        self.history = deque(maxlen=size)
        self._halt = threading.Event()

    def run(self):
        while not self._halt.is_set():
            t0 = time.time()
            self.history.append(sysinfo.ping_once(self.target))
            self._halt.wait(max(0.2, self.interval - (time.time() - t0)))

    def recent(self, n):
        return list(self.history)[-n:]

    def stop(self):
        self._halt.set()


class Alerts:
    """Turns readings into one-off notifications, each rate-limited by a cooldown."""

    COOLDOWN = 600

    def __init__(self):
        self.last, self.cpu_secs, self.ram_secs, self.ticks = {}, 0, 0, 0

    def _fire(self, key, title, msg, out, cooldown=None):
        now = time.time()
        if now - self.last.get(key, 0) > (cooldown or self.COOLDOWN):
            self.last[key] = now
            out.append((title, msg))

    def tick(self, cpu, ram_pct, samples, battery):
        out = []
        self.ticks += 1
        self.cpu_secs = self.cpu_secs + 1 if cpu >= 90 else 0
        self.ram_secs = self.ram_secs + 1 if ram_pct >= 90 else 0
        if self.cpu_secs >= 30:
            self._fire("cpu", "High CPU", f"CPU has been above 90% for {self.cpu_secs} seconds.", out)
        if self.ram_secs >= 30:
            self._fire("ram", "High memory", f"RAM has been above 90% for {self.ram_secs} seconds.", out)
        if len(samples) >= 3 and all(s is None for s in samples[-3:]):
            self._fire("net", "Connection lost", "Pings to 1.1.1.1 have stopped getting replies.", out, 120)
        elif len(samples) >= 12 and sum(s is None for s in samples) >= 5:
            self._fire("loss", "Packet loss", "Over 40% of recent pings to 1.1.1.1 were lost.", out)
        if battery and not battery.power_plugged and battery.percent <= 15:
            self._fire("batt", "Low battery", f"Battery is at {battery.percent:.0f}% and not charging.", out)
        if self.ticks % 60 == 1:
            for mount, total, free in fixed_drives():
                if total and free / total < 0.10:
                    self._fire(f"disk:{mount}", "Disk almost full", f"{mount} has {free / 2**30:.0f} GB free.", out, 3600)
        return out


def fixed_drives():
    """Yields (mountpoint, total, free) for fixed local drives."""
    for part in psutil.disk_partitions(all=False):
        if "fixed" not in part.opts.lower() and part.opts:
            continue
        try:
            usage = psutil.disk_usage(part.mountpoint)
        except OSError:
            continue
        yield part.mountpoint.rstrip("\\"), usage.total, usage.free


def power_plan():
    try:
        out = subprocess.run(["powercfg", "/getactivescheme"], capture_output=True, text=True, timeout=5,
                             creationflags=sysinfo.NO_WINDOW).stdout
    except (subprocess.SubprocessError, OSError):
        return ""
    start, end = out.rfind("("), out.rfind(")")
    return out[start + 1:end] if 0 <= start < end else ""
