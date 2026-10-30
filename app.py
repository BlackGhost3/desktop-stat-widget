"""Desktop stat widget: CPU / GPU / RAM, disk and network speed, IP + DNS tools, ping and more."""
import ipaddress
import os
import subprocess
import sys
import threading
import time
import webbrowser
from collections import deque

import psutil
from PySide6.QtCore import QObject, QPoint, QRect, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QCursor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication, QHBoxLayout, QInputDialog, QLayout, QLineEdit, QMenu, QMessageBox,
    QPushButton, QSystemTrayIcon, QToolTip, QVBoxLayout, QWidget,
)

import features
import hotkey
import localtest
import sysinfo
import theme
import updater
import winutil
from theme import P
from widgets import Bar, Gauge, IconBtn, Metric, QrView, Spark, label

DNS_PRESETS = {"cloudflare": ["1.1.1.1", "1.0.0.1"], "google": ["8.8.8.8", "8.8.4.4"]}
MODES = ["full", "compact", "mini"]
SHOW_KEYS = (("cpu", "CPU"), ("ram", "RAM"), ("net", "Network speed"), ("disk", "Disk speed"),
             ("ip", "Local IP and DNS"), ("public", "Public IP"), ("space", "Free disk space"))
PANELS = (("net", "Network settings"), ("ping", "Ping"), ("hist", "Connection history"),
          ("speed", "Speed test"), ("local", "Local speed test"), ("proc", "Top processes"))
SNAP = 14
FIREWALL_RULE = "Desktop Stat Widget"


def rate(mbps):
    return f"{mbps / 1000:.2f} Gb/s" if mbps >= 1000 else f"{mbps:.0f} Mb/s"


class Bridge(QObject):
    """Carries results from worker threads to the GUI thread."""
    result = Signal(object)
    netdone = Signal()
    update_checked = Signal(object, bool)  # release dict or error string, user-initiated
    update_installed = Signal(object)  # error string or None
    speed_status = Signal(str)
    link_changed = Signal()
    firewall_checked = Signal(bool)
    local_result = Signal(object)  # result dict from a device that ran the local test
    speed_live = Signal(str, float)  # phase, current Mb/s
    speed_done = Signal(object)  # result dict or error string


class Card(QWidget):
    def __init__(self):
        super().__init__()
        self.cfg = winutil.load_config()
        self.mode = self.cfg.get("mode", "full")
        self.pinned = self.cfg.get("pinned", True)
        self.theme_name = self.cfg.get("theme", "auto")
        self.accent_name = self.cfg.get("accent", "Blue")
        theme.apply(self.theme_name, self.accent_name)
        self.show_cfg = {**dict.fromkeys((k for k, _ in SHOW_KEYS), True), **self.cfg.get("show", {})}
        self.alerts_on = self.cfg.get("alerts", True)
        self.monitor_on = self.cfg.get("monitor", True)
        self.hotkey_on = self.cfg.get("hotkey", True)
        self.opacity = self.cfg.get("opacity", 100)
        self.fade = self.cfg.get("fade", True)
        self.idle = self.cfg.get("idle_opacity", 70)
        self.gpu_on = self.cfg.get("gpu", True)

        self.netinfo, self.net_alias = {}, None
        self.public_ip, self.power_plan, self.space_text = None, "", ""
        self.update_info = None
        self.open_panel = None
        self.proc_sort, self.proc_pids, self.proc_names = "cpu", [], []
        self.speed_running = False
        self.wifi, self.link_html, self.link_plain = {}, "", ""
        self.local = None
        self.local_results = deque(self.cfg.get("local_results", []), maxlen=5)
        self.last_gateway, self.suggested = None, None
        self.pending_click = None
        self.rates = sysinfo.Rates()
        self.peaks = {"disk": 100e6}
        self.drag = self.press_global = None
        self.ticks = 0
        self.ping_stop = None
        self.ping_stats = {"sent": 0, "lost": 0, "samples": deque(maxlen=60)}
        self.sampler = features.ProcSampler()
        self.alert_engine = features.Alerts()
        try:
            self.has_battery = psutil.sensors_battery() is not None
        except (AttributeError, OSError):
            self.has_battery = False

        self.bridge = Bridge()
        self.bridge.result.connect(self.on_ping)
        self.bridge.netdone.connect(self.show_net_config)
        self.bridge.update_checked.connect(self.on_update_checked)
        self.bridge.update_installed.connect(self.on_update_installed)
        self.bridge.speed_status.connect(lambda t: self.l_speed_status.setText(t))
        self.bridge.link_changed.connect(self.update_link)
        self.bridge.firewall_checked.connect(self.on_firewall)
        self.fw_polls = 0
        self.bridge.local_result.connect(self.on_local_result)
        self.bridge.speed_live.connect(self.on_speed_live)
        self.bridge.speed_done.connect(self.on_speed_done)

        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setStyleSheet(theme.stylesheet())
        self.build()
        self.apply_flags()
        if "pos" in self.cfg:
            self.move(*self.cfg["pos"])

        self.gpu = self.pinger = self.hotkey_filter = None
        if self.gpu_on:
            self.start_gpu()
        if self.monitor_on:
            self.start_pinger()
        self.make_tray()
        self.set_hotkey(self.hotkey_on)
        psutil.cpu_percent()
        self.refresh_net_config()
        self.refresh_public_ip()
        self.refresh_power_plan()
        self.timer = QTimer(self, interval=1000, timeout=self.tick)
        self.timer.start()
        QTimer(self, interval=15000, timeout=self.refresh_net_config).start()
        QTimer(self, interval=60000, timeout=self.refresh_power_plan).start()
        QTimer(self, interval=300000, timeout=self.refresh_public_ip).start()
        QTimer(self, interval=120, timeout=self.hover_check).start()
        QTimer(self, interval=10000, timeout=self.follow_system_theme).start()
        QTimer(self, interval=2000, timeout=self.refresh_procs).start()
        QTimer(self, interval=5000, timeout=self.refresh_wifi).start()
        QTimer.singleShot(8000, lambda: self.check_updates(manual=False))
        self.set_mode(self.mode)

    # ---------- layout ----------
    def build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 12)
        root.setSpacing(8)
        root.setSizeConstraint(QLayout.SetFixedSize)

        head = QHBoxLayout()
        head.setSpacing(2)
        self.title = label("System")
        self.title.setStyleSheet("font-weight:500; font-size:13px;")
        head.addWidget(self.title, 1)
        self.l_vpn = label("VPN")
        self.l_vpn.setStyleSheet(f"color:{P.GREEN}; font-size:10px; font-weight:500; padding:0 6px;")
        self.l_vpn.hide()
        head.addWidget(self.l_vpn)
        self.btn_tools = IconBtn("tools", "Tools")
        self.btn_mode = IconBtn("size", "Cycle size: full / compact / mini")
        self.btn_pin = IconBtn("pin", "Always on top", checkable=True)
        self.btn_menu = IconBtn("menu", "Menu")
        self.btn_pin.setChecked(self.pinned)
        self.btn_tools.clicked.connect(lambda: self.show_tools(self.btn_tools.mapToGlobal(self.btn_tools.rect().bottomLeft())))
        self.btn_mode.clicked.connect(lambda: self.set_mode(MODES[(MODES.index(self.mode) + 1) % 3]))
        self.btn_pin.toggled.connect(self.set_pinned)
        self.btn_menu.clicked.connect(lambda: self.show_menu(self.btn_menu.mapToGlobal(self.btn_menu.rect().bottomLeft())))
        for b in (self.btn_tools, self.btn_mode, self.btn_pin, self.btn_menu):
            head.addWidget(b)
        root.addLayout(head)

        self.body = QWidget()
        bl = QVBoxLayout(self.body)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(7)
        self.m_cpu, self.m_gpu, self.m_ram = Metric("CPU", "ACCENT"), Metric("GPU", "PURPLE"), Metric("RAM", "GREEN")
        self.m_cpu.setToolTip("Click for top processes")
        self.m_ram.setToolTip("Click for top processes")
        self.m_read, self.m_write = Metric("Read", "AMBER"), Metric("Write", "AMBER")
        for m in (self.m_cpu, self.m_gpu, self.m_ram):
            bl.addWidget(m)
        self.sep = QWidget()
        self.sep.setFixedHeight(1)
        bl.addWidget(self.sep)
        self.net_w = QWidget()
        nl = QHBoxLayout(self.net_w)
        nl.setContentsMargins(0, 0, 0, 0)
        self.l_speed = label("↓ 0.0  ↑ 0.0 Mb/s", mono=True)
        self.l_link = label("", dim=True, align=Qt.AlignRight)
        nl.addWidget(self.l_speed)
        nl.addWidget(self.l_link, 1)
        bl.addWidget(self.net_w)
        self.l_linkd = label("", dim=True)
        self.l_linkd.setTextFormat(Qt.RichText)
        bl.addWidget(self.l_linkd)
        self.spark_net = Spark("ACCENT")
        bl.addWidget(self.spark_net)
        bl.addWidget(self.m_read)
        bl.addWidget(self.m_write)
        self.l_disk = label("R 0 · W 0 MB/s", mono=True)
        self.l_space = label("", mono=True)
        self.l_ip = label("", mono=True)
        self.l_pub = label("Public –", mono=True)
        self.l_batt = label("", mono=True)
        for w in (self.l_disk, self.l_space, self.l_ip, self.l_pub, self.l_batt):
            bl.addWidget(w)
        root.addWidget(self.body)

        self.panels = {"net": self.build_net_panel(), "ping": self.build_ping_panel(),
                       "hist": self.build_hist_panel(), "speed": self.build_speed_panel(),
                       "local": self.build_local_panel(), "proc": self.build_proc_panel()}
        for pnl in self.panels.values():
            pnl.setMinimumWidth(330)
            pnl.hide()
            root.addWidget(pnl)
        self.restyle()

    def restyle(self):
        """Re-applies palette-dependent styles after a theme or accent change."""
        self.setStyleSheet(theme.stylesheet())
        self.sep.setStyleSheet(f"background:{P.LINE};")
        self.l_vpn.setStyleSheet(f"color:{P.GREEN}; font-size:10px; font-weight:500; padding:0 6px;")
        for pnl in self.panels.values():
            pnl.setStyleSheet(f"#panel {{ background:{P.PANEL}; border-radius:12px; }}")
        self.done_card.setStyleSheet(f"#done {{ background:{P.BG}; border-radius:10px; }}")
        self.update()
        for w in self.findChildren(QWidget):
            w.update()
        if hasattr(self, "gpu"):  # past construction: refresh text that has colors baked in
            self.update_space()

    def panel(self):
        w = QWidget()
        w.setObjectName("panel")
        lay = QVBoxLayout(w)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(7)
        return w, lay

    def build_net_panel(self):
        w, lay = self.panel()
        self.net_title = label("Network settings", dim=True)
        lay.addWidget(self.net_title)
        seg = QHBoxLayout()
        self.b_dhcp, self.b_static = QPushButton("DHCP"), QPushButton("Static")
        for b in (self.b_dhcp, self.b_static):
            b.setCheckable(True)
            seg.addWidget(b)
        self.b_dhcp.clicked.connect(lambda: self.set_static(False))
        self.b_static.clicked.connect(lambda: self.set_static(True))
        lay.addLayout(seg)
        self.f_ip, self.f_mask, self.f_gw = QLineEdit(), QLineEdit(), QLineEdit()
        for name, edit in (("IP", self.f_ip), ("Subnet", self.f_mask), ("Gateway", self.f_gw)):
            row = QHBoxLayout()
            n = label(name, dim=True)
            n.setFixedWidth(56)
            row.addWidget(n)
            row.addWidget(edit, 1)
            lay.addLayout(row)
        dns = QHBoxLayout()
        dns.addWidget(label("DNS", dim=True))
        self.dns_btns = {}
        for key, text in (("cloudflare", "Cloudflare"), ("google", "Google"), ("auto", "Auto"), ("custom", "Custom")):
            b = QPushButton(text)
            b.setCheckable(True)
            b.clicked.connect(lambda _=False, k=key: self.set_dns(k))
            self.dns_btns[key] = b
            dns.addWidget(b)
        lay.addLayout(dns)
        self.f_dns = QLineEdit()
        self.f_dns.setPlaceholderText("9.9.9.9, 149.112.112.112")
        lay.addWidget(self.f_dns)
        self.prof_row = QHBoxLayout()
        lay.addLayout(self.prof_row)
        act = QHBoxLayout()
        revert, save, apply_ = QPushButton("Revert"), QPushButton("Save profile"), QPushButton("Apply")
        apply_.setProperty("primary", True)
        revert.clicked.connect(self.load_form)
        save.clicked.connect(self.save_profile)
        apply_.clicked.connect(self.apply_net)
        for b in (revert, save, apply_):
            act.addWidget(b)
        lay.addLayout(act)
        lay.addWidget(label("Applying needs admin approval.", dim=True))
        self.static, self.dns_choice = False, "auto"
        self.rebuild_profiles()
        return w

    def build_ping_panel(self):
        w, lay = self.panel()
        top = QHBoxLayout()
        self.f_target = QLineEdit(self.cfg.get("ping_target", "1.1.1.1"))
        self.b_ping = QPushButton("Start")
        self.b_ping.setProperty("primary", True)
        self.b_ping.clicked.connect(self.toggle_ping)
        self.f_target.returnPressed.connect(self.toggle_ping)
        top.addWidget(self.f_target, 1)
        top.addWidget(self.b_ping)
        lay.addLayout(top)
        pre = QHBoxLayout()
        for text in ("Gateway", "1.1.1.1", "8.8.8.8", "google.com"):
            b = QPushButton(text)
            b.clicked.connect(lambda _=False, t=text: self.pick_target(t))
            pre.addWidget(b)
        lay.addLayout(pre)
        self.spark_ping = Spark("GREEN", height=48, floor=20)
        lay.addWidget(self.spark_ping)
        self.l_ping = label("Not running", dim=True)
        lay.addWidget(self.l_ping)
        return w

    def build_hist_panel(self):
        w, lay = self.panel()
        lay.addWidget(label("Connection history · pings to 1.1.1.1, last hour", dim=True))
        self.spark_hist = Spark("GREEN", height=56, floor=30, size=720)
        lay.addWidget(self.spark_hist)
        self.l_hist = label("Collecting…", dim=True)
        lay.addWidget(self.l_hist)
        return w

    def build_speed_panel(self):
        w, lay = self.panel()
        top = QHBoxLayout()
        top.addWidget(label("Speed test · Cloudflare", dim=True), 1)
        self.b_cache = QPushButton("+ Cached")
        self.b_cache.setCheckable(True)
        self.b_cache.setChecked(self.cfg.get("speed_cache", True))
        self.b_cache.setToolTip("Also download a CDN-cached file to compare with the pure download")
        self.b_cache.toggled.connect(lambda _: self.save())
        top.addWidget(self.b_cache)
        self.b_speed = QPushButton("Run test")
        self.b_speed.setProperty("primary", True)
        self.b_speed.clicked.connect(self.run_speed)
        top.addWidget(self.b_speed)
        lay.addLayout(top)
        self.gauge = Gauge()
        lay.addWidget(self.gauge)
        row = QHBoxLayout()
        self.speed_vals = {}
        for key, name in (("down", "Download"), ("up", "Upload"), ("cached", "Cached"), ("ping", "Ping")):
            col = QVBoxLayout()
            col.setSpacing(0)
            col.addWidget(label(name, dim=True))
            v = label("–")
            v.setStyleSheet("font-size:15px; font-weight:500;")
            col.addWidget(v)
            self.speed_vals[key] = v
            row.addLayout(col)
        lay.addLayout(row)
        self.l_speed_status = label("Uses about 70 MB per run, about 100 MB with the cached test.", dim=True)
        self.l_speed_status.setWordWrap(True)
        lay.addWidget(self.l_speed_status)
        return w

    def build_local_panel(self):
        w, lay = self.panel()
        top = QHBoxLayout()
        top.addWidget(label("Local speed test · device to this PC", dim=True), 1)
        self.b_fw = QPushButton("Allow in firewall")
        self.b_fw.setProperty("small", True)
        self.b_fw.setToolTip("Adds a Windows Firewall rule so other devices can reach the test page")
        self.b_fw.clicked.connect(self.allow_firewall)
        self.b_local = QPushButton("Start")
        self.b_local.setProperty("primary", True)
        self.b_local.clicked.connect(self.toggle_local)
        top.addWidget(self.b_fw)
        top.addWidget(self.b_local)
        lay.addLayout(top)
        self.done_card = QWidget()
        self.done_card.setObjectName("done")
        dc = QVBoxLayout(self.done_card)
        dc.setContentsMargins(12, 10, 12, 10)
        dc.setSpacing(6)
        self.l_done_title = label("")
        dc.addWidget(self.l_done_title)
        vals = QHBoxLayout()
        vals.setSpacing(20)
        self.done_vals = {}
        for key, name in (("down", "Download"), ("up", "Upload"), ("ping", "Ping")):
            col = QVBoxLayout()
            col.setSpacing(0)
            col.addWidget(label(name, dim=True))
            v = label("–")
            v.setStyleSheet("font-size:20px; font-weight:500;")
            col.addWidget(v)
            self.done_vals[key] = v
            vals.addLayout(col)
        dc.addLayout(vals)
        self.done_card.hide()
        lay.addWidget(self.done_card)
        self.l_local_link = label("", dim=True)
        lay.addWidget(self.l_local_link)
        urlrow = QHBoxLayout()
        self.f_url = QLineEdit()
        self.f_url.setReadOnly(True)
        b_copy = QPushButton("Copy")
        b_copy.setProperty("small", True)
        b_copy.clicked.connect(lambda: self.copy_text(self.f_url.text(), "link"))
        b_new = QPushButton("New link")
        b_new.setProperty("small", True)
        b_new.setToolTip("Creates a new link and QR code. The old ones stop working.")
        b_new.clicked.connect(self.refresh_link)
        urlrow.addWidget(self.f_url, 1)
        urlrow.addWidget(b_copy)
        urlrow.addWidget(b_new)
        self.url_box = QWidget()
        self.url_box.setLayout(urlrow)
        urlrow.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.url_box)
        self.qr = QrView()
        lay.addWidget(self.qr, 0, Qt.AlignHCenter)
        self.l_local_status = label("Start the server, then scan the code or open the link on a device on the "
                                    "same network.", dim=True)
        self.l_local_status.setWordWrap(True)
        lay.addWidget(self.l_local_status)
        self.local_rows = [label("", mono=True) for _ in range(5)]
        for row in self.local_rows:
            lay.addWidget(row)
        self.url_box.hide()
        self.qr.hide()
        self.render_local_results()
        return w

    def build_proc_panel(self):
        w, lay = self.panel()
        top = QHBoxLayout()
        top.addWidget(label("Top processes", dim=True), 1)
        self.b_sort = {}
        for key, text in (("cpu", "CPU"), ("mem", "RAM")):
            b = QPushButton(text)
            b.setCheckable(True)
            b.setProperty("small", True)
            b.clicked.connect(lambda _=False, k=key: self.set_proc_sort(k))
            self.b_sort[key] = b
            top.addWidget(b)
        lay.addLayout(top)
        self.proc_rows = []
        for i in range(5):
            row = QHBoxLayout()
            name, val = label("", mono=True), label("", mono=True, align=Qt.AlignRight | Qt.AlignVCenter)
            val.setFixedWidth(92)
            end = QPushButton("End")
            end.setProperty("small", True)
            end.clicked.connect(lambda _=False, i=i: self.end_proc(i))
            row.addWidget(name, 1)
            row.addWidget(val)
            row.addWidget(end)
            lay.addLayout(row)
            self.proc_rows.append((name, val, end))
        self.set_proc_sort("cpu")
        return w

    # ---------- window behaviour ----------
    def apply_flags(self):
        flags = Qt.FramelessWindowHint | Qt.Tool
        if self.pinned:
            flags |= Qt.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        self.show()

    def set_pinned(self, on):
        self.pinned = on
        pos = self.pos()
        self.apply_flags()
        self.move(pos)
        self.save()

    def set_mode(self, mode):
        self.mode = mode
        mini = mode == "mini"
        self.title.setTextFormat(Qt.RichText if mini else Qt.PlainText)
        self.title.setStyleSheet("font-size:12px;" if mini else "font-weight:500; font-size:13px;")
        if not mini:
            self.title.setText("System")
            self.setToolTip("")
        self.btn_menu.setVisible(not mini)
        self.layout().setContentsMargins(*((10, 4, 6, 4) if mini else (12, 10, 12, 12)))
        self.body.setFixedWidth(330 if mode == "full" else 270)
        self.title.setMinimumWidth(0 if not mini else 330)
        self.apply_visibility()
        self.save()

    def apply_visibility(self):
        s, mode = self.show_cfg, self.mode
        full, compact = mode == "full", mode == "compact"
        self.body.setVisible(mode != "mini")
        self.m_cpu.setVisible(s["cpu"])
        self.m_gpu.setVisible(self.gpu_on)
        self.m_ram.setVisible(s["ram"])
        self.sep.setVisible(s["cpu"] or s["ram"] or self.gpu_on)
        self.net_w.setVisible(s["net"])
        self.l_linkd.setVisible(s["net"] and bool(self.link_html))
        self.spark_net.setVisible(full and s["net"])
        for w in (self.m_read, self.m_write):
            w.setVisible(full and s["disk"])
        self.l_disk.setVisible(compact and s["disk"])
        self.l_ip.setVisible(s["ip"])
        self.l_pub.setVisible(s["public"])
        self.l_space.setVisible(s["space"] and bool(self.space_text))
        self.l_batt.setVisible(self.has_battery)
        self.l_vpn.setVisible(bool(self.netinfo.get("vpn")) and mode != "mini")
        for key, pnl in self.panels.items():
            pnl.setVisible(self.open_panel == key)
        self.adjustSize()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(QColor(P.BORDER), 1))
        p.setBrush(QColor(P.BG))
        p.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 16, 16)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.press_global = e.globalPosition().toPoint()
            self.drag = self.press_global - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):
        if self.drag is None or not e.buttons() & Qt.LeftButton:
            return
        pos = e.globalPosition().toPoint() - self.drag
        screen = QApplication.screenAt(e.globalPosition().toPoint()) or self.screen()
        area, w, h = screen.availableGeometry(), self.width(), self.height()
        x, y = pos.x(), pos.y()
        if abs(x - area.left()) < SNAP:
            x = area.left()
        elif abs(x + w - area.right() - 1) < SNAP:
            x = area.right() + 1 - w
        if abs(y - area.top()) < SNAP:
            y = area.top()
        elif abs(y + h - area.bottom() - 1) < SNAP:
            y = area.bottom() + 1 - h
        self.move(x, y)

    def mouseReleaseEvent(self, e):
        moved = (e.globalPosition().toPoint() - self.press_global).manhattanLength() if self.press_global else 99
        self.drag = self.press_global = None
        if moved < 4 and e.button() == Qt.LeftButton:
            self.handle_click(e.position().toPoint())
        self.save()

    def handle_click(self, pos):
        targets = ((self.l_ip, self.copy_local), (self.l_pub, self.copy_public),
                   (self.m_cpu, lambda: self.show_panel("proc", "cpu")),
                   (self.m_ram, lambda: self.show_panel("proc", "mem")))
        for widget, action in targets:
            if widget.isVisible() and QRect(widget.mapTo(self, QPoint(0, 0)), widget.size()).contains(pos):
                action()
                return

    def mouseDoubleClickEvent(self, _):
        self.set_mode(MODES[(MODES.index(self.mode) + 1) % 3])

    def contextMenuEvent(self, e):
        self.show_menu(e.globalPos())

    def tell(self, title, text):
        self._box(QMessageBox.Information, title, text, QMessageBox.Ok).exec()

    def ask(self, title, text):
        return self._box(QMessageBox.Question, title, text, QMessageBox.Yes | QMessageBox.No).exec() == QMessageBox.Yes

    def _box(self, icon, title, text, buttons):
        """Message box that stays above this always-on-top widget instead of opening behind it."""
        box = QMessageBox(icon, title, text, buttons, self)
        box.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        return box

    def copy_text(self, text, what):
        if text:
            QApplication.clipboard().setText(text)
            QToolTip.showText(QCursor.pos(), f"Copied {what} {text}", self)

    def copy_local(self):
        self.copy_text(self.netinfo.get("ip"), "local IP")

    def copy_public(self):
        self.copy_text(self.public_ip, "public IP")

    def hover_check(self, force=False):
        under = (self.drag is not None or self.frameGeometry().contains(QCursor.pos())
                 or QApplication.activePopupWidget() is not None
                 or QApplication.activeModalWidget() is not None)
        pct = self.opacity if (under or not self.fade) else min(self.opacity, self.idle)
        if force or abs(self.windowOpacity() - pct / 100) > 0.01:
            self.setWindowOpacity(pct / 100)

    # ---------- menus ----------
    def add_check(self, menu, text, on, fn):
        act = menu.addAction(text)
        act.setCheckable(True)
        act.setChecked(on)
        act.triggered.connect(fn)
        return act

    def show_menu(self, pos):
        menu = QMenu(self)
        look = menu.addMenu("Appearance")
        th = look.addMenu("Theme")
        for name in theme.THEMES:
            self.add_check(th, name.capitalize(), self.theme_name == name, lambda _=False, n=name: self.set_theme(mode=n))
        ac = look.addMenu("Accent color")
        for name in theme.ACCENTS:
            self.add_check(ac, name, self.accent_name == name, lambda _=False, n=name: self.set_theme(accent=n))
        look.addSeparator()
        ops = look.addMenu("Opacity")
        for pct in (100, 85, 70):
            self.add_check(ops, f"{pct}%", self.opacity == pct, lambda _=False, p=pct: self.set_opacity(opacity=p))
        self.add_check(look, "Fade when cursor is away", self.fade, lambda on: self.set_opacity(fade=on))
        idle = look.addMenu("Faded opacity")
        for pct in (30, 50, 70):
            self.add_check(idle, f"{pct}%", self.idle == pct, lambda _=False, p=pct: self.set_opacity(idle=p))

        shown = menu.addMenu("Show")
        for key, text in SHOW_KEYS:
            self.add_check(shown, text, self.show_cfg[key], lambda on, k=key: self.set_show(k, on))
        self.add_check(shown, "GPU (uses extra CPU and RAM)", self.gpu_on, self.set_gpu)

        beh = menu.addMenu("Behavior")
        self.add_check(beh, "Start with Windows", winutil.startup_enabled(), self.toggle_startup)
        self.add_check(beh, "Alerts (CPU, RAM, disk, connection)", self.alerts_on, self.set_alerts)
        self.add_check(beh, "Connection monitor (pings 1.1.1.1)", self.monitor_on, self.set_monitor)
        self.add_check(beh, "Show or hide with Ctrl+Alt+W", self.hotkey_on, self.set_hotkey_pref)

        menu.addSeparator()
        if self.update_info:
            menu.addAction(f"Update to {self.update_info['tag']}…", self.prompt_update)
        else:
            menu.addAction("Check for updates", lambda: self.check_updates(manual=True))
        menu.addAction(f"Version {updater.VERSION}").setEnabled(False)
        menu.addSeparator()
        menu.addAction("Quit", self.quit)
        menu.exec(pos)

    def show_tools(self, pos):
        menu = QMenu(self)
        for key, text in PANELS:
            self.add_check(menu, text, self.open_panel == key, lambda on, k=key: self.show_panel(k if on else None))
        menu.exec(pos)

    def show_panel(self, key, sort=None):
        self.open_panel = key
        if key != "local" and self.local:
            self.stop_local()
        if sort:
            self.set_proc_sort(sort)
        self.apply_visibility()
        if key == "local":
            self.check_firewall()
        if key == "proc":
            self.refresh_procs()
        elif key == "hist":
            self.refresh_hist()

    # ---------- settings ----------
    def set_theme(self, mode=None, accent=None):
        if mode:
            self.theme_name = mode
        if accent:
            self.accent_name = accent
        theme.apply(self.theme_name, self.accent_name)
        self.restyle()
        self.save()

    def follow_system_theme(self):
        if self.theme_name == "auto" and theme.resolve("auto") != P.RESOLVED:
            self.set_theme()

    def set_show(self, key, on):
        self.show_cfg[key] = on
        self.apply_visibility()
        self.save()

    def set_opacity(self, opacity=None, fade=None, idle=None):
        if opacity is not None:
            self.opacity = opacity
        if fade is not None:
            self.fade = fade
        if idle is not None:
            self.idle = idle
        self.hover_check(force=True)
        self.save()

    def start_gpu(self):
        self.gpu = sysinfo.GpuReader()
        self.gpu.start()

    def set_gpu(self, on):
        self.gpu_on = on
        if on:
            self.start_gpu()
        elif self.gpu:
            self.gpu.stop()
            self.gpu = None
        self.apply_visibility()
        self.save()

    def start_pinger(self):
        self.pinger = features.Pinger()
        self.pinger.start()

    def set_monitor(self, on):
        self.monitor_on = on
        if on and not self.pinger:
            self.start_pinger()
        elif not on and self.pinger:
            self.pinger.stop()
            self.pinger = None
        self.save()

    def set_alerts(self, on):
        self.alerts_on = on
        self.save()

    def set_hotkey(self, on):
        if self.hotkey_filter:
            QApplication.instance().removeNativeEventFilter(self.hotkey_filter)
            self.hotkey_filter.unregister()
            self.hotkey_filter = None
        if on:
            hk = hotkey.Hotkey(self.toggle_visible)
            if hk.ok:
                self.hotkey_filter = hk
                QApplication.instance().installNativeEventFilter(hk)

    def set_hotkey_pref(self, on):
        self.hotkey_on = on
        self.set_hotkey(on)
        if on and not self.hotkey_filter:
            self.tell("Hotkey", "Ctrl+Alt+W is already used by another app.")
        self.save()

    def toggle_visible(self):
        if self.isVisible():
            self.hide()
        else:
            self.show()
            self.raise_()

    def toggle_startup(self, on):
        try:
            winutil.set_startup(on)
        except OSError as err:
            self.tell("Startup", f"Couldn't change the startup entry.\n{err}")

    def save(self):
        self.cfg.update(mode=self.mode, pinned=self.pinned, pos=[self.x(), self.y()],
                        ping_target=self.f_target.text().strip() or "1.1.1.1",
                        opacity=self.opacity, fade=self.fade, idle_opacity=self.idle, gpu=self.gpu_on,
                        theme=self.theme_name, accent=self.accent_name, show=self.show_cfg,
                        alerts=self.alerts_on, monitor=self.monitor_on, hotkey=self.hotkey_on,
                        speed_cache=self.b_cache.isChecked())
        winutil.save_config(self.cfg)

    def quit(self):
        self.save()
        if self.ping_stop:
            self.ping_stop.set()
        if self.gpu:
            self.gpu.stop()
        if self.pinger:
            self.pinger.stop()
        if self.local:
            self.local.stop()
        if self.hotkey_filter:
            self.hotkey_filter.unregister()
        self.tray.hide()
        QApplication.quit()

    # ---------- tray and notifications ----------
    def make_tray(self):
        pix = QPixmap(32, 32)
        pix.fill(Qt.transparent)
        p = QPainter(pix)
        p.setRenderHint(QPainter.Antialiasing)
        p.setBrush(QColor("#14151a"))
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(1, 1, 30, 30, 8, 8)
        for i, (h, c) in enumerate(((12, "#7f9cff"), (20, "#5fd8a6"), (8, "#f0a860"))):
            p.setBrush(QColor(c))
            p.drawRoundedRect(6 + i * 8, 26 - h, 5, h, 2, 2)
        p.end()
        self.tray = QSystemTrayIcon(QIcon(pix), self)
        self.tray.setToolTip("Desktop stat widget")
        menu = QMenu()
        menu.addAction("Show or hide", self.toggle_visible)
        menu.addAction("Quit", self.quit)
        self.tray_menu = menu
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(lambda reason: self.toggle_visible() if reason == QSystemTrayIcon.Trigger else None)
        self.tray.messageClicked.connect(self.on_tray_clicked)
        self.tray.show()

    def notify(self, title, msg, on_click=None):
        self.pending_click = on_click
        self.tray.showMessage(title, msg, QSystemTrayIcon.Information, 8000)

    def on_tray_clicked(self):
        if self.pending_click:
            self.pending_click()
            self.pending_click = None

    # ---------- live stats ----------
    def tick(self):
        self.ticks += 1
        cpu = psutil.cpu_percent()
        ram = psutil.virtual_memory()
        gpu = self.gpu.value if self.gpu else -1
        disk = psutil.disk_io_counters()
        nics = psutil.net_io_counters(pernic=True)
        net = nics.get(self.net_alias) or psutil.net_io_counters()
        rd, wr, rx, tx = self.rates.update(disk, net)
        self.peaks["disk"] = max(self.peaks["disk"], rd, wr)

        self.m_cpu.set(cpu / 100, f"{cpu:.0f}%")
        self.m_gpu.set(max(gpu, 0) / 100, f"{gpu}%" if gpu >= 0 else "n/a")
        self.m_ram.set(ram.percent / 100, f"{ram.used / 2**30:.1f} GB")
        self.m_read.set(rd / self.peaks["disk"], f"{rd / 1e6:.0f} MB/s")
        self.m_write.set(wr / self.peaks["disk"], f"{wr / 1e6:.0f} MB/s")
        down, up = rx * 8 / 1e6, tx * 8 / 1e6
        self.l_speed.setText(f"↓ {down:.1f}  ↑ {up:.1f} Mb/s")
        self.spark_net.push(down)
        self.l_disk.setText(f"R {rd / 1e6:.0f} · W {wr / 1e6:.0f} MB/s")
        self.l_pub.setText(f"Public {self.public_ip or '–'}")
        if self.ticks % 30 == 1:
            self.update_space()
        battery = self.update_battery()

        if self.alerts_on:
            samples = self.pinger.recent(12) if self.pinger else []
            for title, msg in self.alert_engine.tick(cpu, ram.percent, samples, battery):
                self.notify(title, msg)
        if self.open_panel == "hist":
            self.refresh_hist()
        if self.mode == "mini":
            self.update_mini(cpu, gpu, ram.percent, down, up, rd, wr)

    def update_mini(self, cpu, gpu, ram_pct, down, up, rd, wr):
        def item(name, color, value):
            return f"<span style='color:{color}'>{name}</span>&nbsp;<b>{value}</b>"
        s = self.show_cfg
        parts = []
        if s["cpu"]:
            parts.append(item("CPU", P.ACCENT, f"{cpu:.0f}%"))
        if self.gpu_on:
            parts.append(item("GPU", P.PURPLE, f"{gpu}%" if gpu >= 0 else "n/a"))
        if s["ram"]:
            parts.append(item("RAM", P.GREEN, f"{ram_pct:.0f}%"))
        if s["net"]:
            parts.append(item("↓", P.ACCENT, f"{down:.0f}") + "&nbsp;" + item("↑", P.ACCENT, f"{up:.0f}"))
        if s["disk"]:
            parts.append(item("R", P.AMBER, f"{rd / 1e6:.0f}") + "&nbsp;" + item("W", P.AMBER, f"{wr / 1e6:.0f}"))
        if self.netinfo.get("vpn"):
            parts.append(f"<span style='color:{P.GREEN}'><b>VPN</b></span>")
        sep = f"<span style='color:{P.LINE}'>&nbsp;│&nbsp;</span>"
        self.title.setText(sep.join(parts) or "System")
        self.setToolTip("CPU · GPU · RAM · network down/up Mb/s · disk read/write MB/s")

    def update_space(self):
        drives = list(features.fixed_drives())[:3]
        parts = []
        for mount, total, free in drives:
            color = P.RED if total and free / total < 0.10 else P.TEXT
            parts.append(f"<span style='color:{color}'>{mount[:2]} {free / 2**30:.0f}G</span>")
        self.space_text = " · ".join(parts)
        self.l_space.setText(f"<span style='color:{P.DIM}'>Free</span>&nbsp;" + self.space_text if parts else "")
        self.l_space.setVisible(self.show_cfg["space"] and bool(parts) and self.mode != "mini")

    def update_battery(self):
        if not self.has_battery:
            return None
        try:
            b = psutil.sensors_battery()
        except (AttributeError, OSError):
            return None
        if b:
            state = "charging" if b.power_plugged else "on battery"
            plan = f" · {self.power_plan}" if self.power_plan else ""
            self.l_batt.setText(f"Battery {b.percent:.0f}% · {state}{plan}")
        return b

    def refresh_power_plan(self):
        if not self.has_battery:
            return

        def work():
            self.power_plan = features.power_plan()
        threading.Thread(target=work, daemon=True).start()

    def refresh_public_ip(self):
        def work():
            self.public_ip = sysinfo.public_ip()
        threading.Thread(target=work, daemon=True).start()

    def refresh_net_config(self):
        def work():
            cfg = sysinfo.read_net_config()
            if cfg:
                self.netinfo = cfg
                self.net_alias = cfg.get("alias")
            self.bridge.netdone.emit()
        threading.Thread(target=work, daemon=True).start()

    def show_net_config(self):
        c = self.netinfo
        if not c:
            self.l_ip.setText("No network")
            return
        self.l_link.setText(f"{sysinfo.link_kind(c)} · {'DHCP' if c.get('dhcp') else 'Static'}")
        dns = c.get("dns") or []
        self.l_ip.setText(f"{c.get('ip', '?')} · DNS {dns[0] if dns else '–'}")
        self.l_ip.setToolTip("Click to copy")
        self.l_pub.setToolTip("Click to copy")
        self.l_vpn.setVisible(bool(c.get("vpn")) and self.mode != "mini")
        self.l_vpn.setToolTip(f"VPN active: {c.get('vpn', '')}")
        self.net_title.setText(f"Network settings · {c.get('alias', '')}")
        self.update_link()
        if sysinfo.link_kind(c) == "Wi-Fi" and not self.wifi:
            self.refresh_wifi()
        if not self.f_ip.isModified() and not self.f_ip.hasFocus():
            self.load_form()
        self.suggest_profile()

    def suggest_profile(self):
        """Offers a saved profile when the gateway matches one. Never applies it (that needs admin)."""
        gw = self.netinfo.get("gateway")
        if not self.alerts_on or not gw or gw == self.last_gateway:
            return
        self.last_gateway = gw
        for name, d in self.cfg.get("profiles", {}).items():
            same_settings = d["static"] == (not self.netinfo.get("dhcp")) and d["ip"] == self.netinfo.get("ip")
            if d.get("gw") == gw and not same_settings and self.suggested != (gw, name):
                self.suggested = (gw, name)
                self.notify("Network profile", f"This network matches your profile '{name}'. Click to review it.",
                            lambda n=name: (self.show_panel("net"), self.load_profile(n)))
                return

    # ---------- top processes ----------
    def set_proc_sort(self, key):
        self.proc_sort = key
        for k, b in self.b_sort.items():
            b.setChecked(k == key)

    def refresh_procs(self):
        if self.open_panel != "proc":
            return
        rows = self.sampler.top(self.proc_sort)
        self.proc_pids = [g["pids"] for g in rows] + [[]] * 5
        self.proc_names = [g["name"] for g in rows] + [""] * 5
        for i, (name, val, end) in enumerate(self.proc_rows):
            if i < len(rows):
                g = rows[i]
                count = f" ×{len(g['pids'])}" if len(g["pids"]) > 1 else ""
                name.setText(f"{g['name'][:22]}{count}")
                val.setText(f"{g['cpu']:.0f}% · {g['mem'] / 2**20:.0f} MB")
            for w in (name, val, end):
                w.setVisible(i < len(rows))

    def end_proc(self, i):
        pids, name = self.proc_pids[i], self.proc_names[i]
        if not pids:
            return
        if name.lower() in features.PROTECTED:
            self.tell("Top processes", f"{name} is part of Windows, so it can't be ended here.")
            return
        count = f" ({len(pids)} processes)" if len(pids) > 1 else ""
        if not self.ask("End process", f"End {name}{count}? Unsaved work in it will be lost."):
            return
        failed = features.end_processes(pids)
        if failed:
            self.tell("End process", f"{failed} process(es) couldn't be ended. They may need admin rights.")

    # ---------- link speed ----------
    def refresh_wifi(self):
        if not self.netinfo or sysinfo.link_kind(self.netinfo) != "Wi-Fi":
            return

        def work():
            self.wifi = sysinfo.wifi_info()
            self.bridge.link_changed.emit()
        threading.Thread(target=work, daemon=True).start()

    def update_link(self):
        """Builds the link-speed line: negotiated Ethernet speed, or the live Wi-Fi rate, band and signal."""
        c, parts, warn = self.netinfo, [], False
        if c and not c.get("vpn_only"):
            if sysinfo.link_kind(c) == "Wi-Fi" and self.wifi:
                w = self.wifi
                if w.get("band"):
                    parts.append(w["band"] + (f" ch {w['channel']}" if w.get("channel") else ""))
                if w.get("rx") and w.get("tx"):
                    parts.append(f"↓{w['rx']:.0f} ↑{w['tx']:.0f} Mb/s")
                if w.get("signal") is not None:
                    parts.append(f"signal {w['signal']:.0f}%")
                    warn = w["signal"] < 40
            else:
                speed = int(c["speed"]) if str(c.get("speed", "")).isdigit() else 0
                if 0 < speed < 10**12:
                    parts.append(sysinfo.fmt_speed(speed))
                    half = c.get("duplex") is False
                    parts.append("half duplex" if half else "full duplex")
                    warn = speed <= 100_000_000 or half
        text = " · ".join(parts)
        self.link_plain = f"This PC: {sysinfo.link_kind(c)} {text}" if text else ""
        color = P.AMBER if warn else P.DIM
        self.link_html = f"<span style='color:{color}'>{text}</span>" if text else ""
        self.l_linkd.setText(self.link_html)
        self.l_linkd.setToolTip("Link speed is the ceiling of this connection. Real speed is lower."
                                + (" Amber means a slow link or weak signal." if warn else ""))
        self.l_local_link.setText(self.link_plain)
        self.apply_visibility()

    # ---------- local network speed test ----------
    def toggle_local(self):
        if self.local:
            self.stop_local()
            return
        server = localtest.LocalServer(self.bridge.local_result.emit)
        try:
            server.start()
        except OSError as err:
            self.l_local_status.setText(str(err))
            return
        self.local = server
        url = server.url(self.netinfo.get("ip") or localtest.lan_ip())
        self.f_url.setText(url)
        self.f_url.setCursorPosition(0)
        self.qr.set_data(url)
        self.url_box.show()
        self.qr.show()
        self.b_local.setText("Stop")
        self.l_local_status.setText("Waiting for a device. Scan the code or open the link on the same network. "
                                    "If it can't connect, press Allow in firewall.")
        self.adjustSize()

    def refresh_link(self):
        if not self.local:
            return
        self.local.refresh()
        url = self.local.url(self.netinfo.get("ip") or localtest.lan_ip())
        self.f_url.setText(url)
        self.f_url.setCursorPosition(0)
        self.qr.set_data(url)
        self.done_card.hide()
        self.l_local_status.setText("New link created. The old link and QR code no longer work.")
        self.adjustSize()

    def stop_local(self):
        if self.local:
            self.local.stop()
            self.local = None
        self.url_box.hide()
        self.qr.hide()
        self.b_local.setText("Start")
        self.l_local_status.setText("Server stopped. Start it again to test another device.")
        self.adjustSize()

    def on_local_result(self, r):
        who = f"{r['device']} ({r['ip']})"
        if r.get("event") == "start":
            self.done_card.hide()
            self.l_local_status.setText(f"Testing {who}…")
            self.adjustSize()
            return
        self.local_results.appendleft(r)
        self.cfg["local_results"] = list(self.local_results)
        self.render_local_results()
        self.l_done_title.setText(f"<span style='color:{P.GREEN}'><b>✓ Test complete</b></span> · {who}")
        self.done_vals["down"].setText(rate(r["down"]))
        self.done_vals["up"].setText(rate(r["up"]))
        self.done_vals["ping"].setText(f"{r['ping']:.0f} ms")
        self.done_card.show()
        self.l_local_status.setText("Run it again on the device, or scan the code with another one.")
        self.notify("Local speed test finished", f"{r['device']}: ↓{rate(r['down'])} ↑{rate(r['up'])}, "
                                                 f"ping {r['ping']:.0f} ms")
        self.adjustSize()
        self.save()

    def check_firewall(self):
        def work():
            try:
                rc = subprocess.run(["netsh", "advfirewall", "firewall", "show", "rule", f'name={FIREWALL_RULE}'],
                                    capture_output=True, timeout=8, creationflags=sysinfo.NO_WINDOW).returncode
            except (subprocess.SubprocessError, OSError):
                rc = 1
            self.bridge.firewall_checked.emit(rc == 0)
        threading.Thread(target=work, daemon=True).start()

    def on_firewall(self, allowed):
        self.b_fw.setVisible(not allowed)
        if allowed:
            self.fw_polls = 0
            self.adjustSize()
        elif self.fw_polls > 0:  # waiting for the admin prompt to be approved
            self.fw_polls -= 1
            QTimer.singleShot(3000, self.check_firewall)

    def render_local_results(self):
        for i, row in enumerate(self.local_rows):
            if i < len(self.local_results):
                r = self.local_results[i]
                row.setText(f"{r['time']} {r['device'][:10]:<10} ↓{rate(r['down'])} ↑{rate(r['up'])} {r['ping']:.0f}ms")
            row.setVisible(i < len(self.local_results))

    def allow_firewall(self):
        if not self.ask("Windows Firewall", "Allow incoming connections to this app on private networks so "
                        "phones and other PCs can open the test page? This needs admin approval."):
            return
        exe = sys.executable
        cmds = [f'netsh advfirewall firewall delete rule name="{FIREWALL_RULE}"',
                f'netsh advfirewall firewall add rule name="{FIREWALL_RULE}" dir=in action=allow program="{exe}" '
                "profile=private enable=yes"]
        if winutil.run_elevated(cmds):
            self.fw_polls = 10  # check every 3 s for the rule while the admin prompt is answered
            QTimer.singleShot(3000, self.check_firewall)
        else:
            self.tell("Windows Firewall", "Admin approval was declined, so nothing changed.")

    # ---------- connection history and speed test ----------
    def refresh_hist(self):
        if not self.pinger:
            self.l_hist.setText("Connection monitor is off. Turn it on in the menu under Behavior.")
            return
        hist = list(self.pinger.history)
        self.spark_hist.load(hist)
        ok = [h for h in hist if h is not None]
        if hist:
            loss = 100 * (len(hist) - len(ok)) / len(hist)
            avg = f"{sum(ok) / len(ok):.0f}" if ok else "–"
            peak = f"{max(ok):.0f}" if ok else "–"
            self.l_hist.setText(f"{len(hist) * 5 // 60} min · avg {avg} ms · max {peak} ms · loss {loss:.0f}%")

    def run_speed(self):
        if self.speed_running:
            return
        self.speed_running = True
        self.b_speed.setText("Running…")
        for v in self.speed_vals.values():
            v.setText("–")
        self.gauge.reset()
        with_cache = self.b_cache.isChecked()

        def work():
            try:
                self.bridge.speed_done.emit(features.run_speedtest(self.bridge.speed_status.emit,
                                                                   self.bridge.speed_live.emit, with_cache))
            except (OSError, ValueError) as err:
                self.bridge.speed_done.emit(f"Test failed. {err}")
        threading.Thread(target=work, daemon=True).start()

    def on_speed_live(self, phase, mbps):
        names = {"ping": ("Ping", "ACCENT", "ping"), "down": ("Download", "ACCENT", "down"),
                 "up": ("Upload", "PURPLE", "up"), "cache": ("Cached download", "GREEN", "cached")}
        name, key, tile = names[phase]
        self.gauge.set_value(mbps, name, key)
        if mbps:
            self.speed_vals[tile].setText(f"{mbps:.0f} Mb/s" if tile != "ping" else f"{mbps:.0f} ms")

    def on_speed_done(self, result):
        self.speed_running = False
        self.b_speed.setText("Run test")
        if isinstance(result, str):
            self.l_speed_status.setText(result)
            return
        self.speed_vals["down"].setText(f"{result['down']:.0f} Mb/s")
        self.speed_vals["up"].setText(f"{result['up']:.0f} Mb/s")
        self.speed_vals["ping"].setText(f"{result['ping']:.0f} ms" if result["ping"] is not None else "–")
        self.gauge.finish()
        if result["cached"] is not None:
            self.speed_vals["cached"].setText(f"{result['cached']:.0f} Mb/s")
            ratio = result["cached"] / result["down"] if result["down"] else 0
            self.l_speed_status.setText(f"Cached is {ratio:.1f}× the pure download ({result['cache_note']}). "
                                        "Upload can't be cached.")
        else:
            self.l_speed_status.setText("Done. Uses about 70 MB of data per run.")

    # ---------- IP / DNS settings ----------
    def load_form(self):
        c = self.netinfo
        if not c:
            return
        self.f_ip.setText(c.get("ip", ""))
        prefix = c.get("prefix", 24)
        self.f_mask.setText(str(ipaddress.IPv4Network(f"0.0.0.0/{prefix}").netmask))
        self.f_gw.setText(c.get("gateway", ""))
        self.set_static(not c.get("dhcp", True))
        dns = c.get("dns") or []
        match = next((k for k, v in DNS_PRESETS.items() if dns[:len(v)] == v), None)
        self.f_dns.setText(", ".join(dns))
        self.set_dns(match or ("auto" if c.get("dhcp") else "custom"))
        self.f_ip.setModified(False)

    def set_static(self, on):
        self.static = on
        self.b_static.setChecked(on)
        self.b_dhcp.setChecked(not on)
        for f in (self.f_ip, self.f_mask, self.f_gw):
            f.setEnabled(on)

    def set_dns(self, key):
        self.dns_choice = key
        for k, b in self.dns_btns.items():
            b.setChecked(k == key)
        self.f_dns.setVisible(key == "custom")

    def dns_servers(self):
        if self.dns_choice in DNS_PRESETS:
            return DNS_PRESETS[self.dns_choice]
        return [s.strip() for s in self.f_dns.text().replace(";", ",").split(",") if s.strip()]

    def form_data(self):
        return {"static": self.static, "ip": self.f_ip.text().strip(), "mask": self.f_mask.text().strip(),
                "gw": self.f_gw.text().strip(), "dns_choice": self.dns_choice, "dns": self.f_dns.text().strip()}

    def apply_net(self):
        alias = self.netinfo.get("alias")
        if not alias or '"' in alias:
            self.tell("Network", "No active network adapter found.")
            return
        cmds = []
        try:
            if self.static:
                ip, mask, gw = self.f_ip.text().strip(), self.f_mask.text().strip(), self.f_gw.text().strip()
                net = ipaddress.IPv4Network(f"{ip}/{mask}", strict=False)
                if ipaddress.IPv4Address(gw) not in net:
                    raise ValueError("Gateway isn't in the same subnet as the IP.")
                cmds.append(f'netsh interface ip set address name="{alias}" static {ip} {mask} {gw}')
            else:
                cmds.append(f'netsh interface ip set address name="{alias}" dhcp')
            if self.dns_choice == "auto":
                cmds.append(f'netsh interface ip set dns name="{alias}" dhcp')
            else:
                servers = [str(ipaddress.IPv4Address(s)) for s in self.dns_servers()]
                if not servers:
                    raise ValueError("Enter at least one DNS server.")
                cmds.append(f'netsh interface ip set dns name="{alias}" static {servers[0]}')
                cmds += [f'netsh interface ip add dns name="{alias}" {s} index={i}'
                         for i, s in enumerate(servers[1:], 2)]
        except ValueError as err:
            self.tell("Network", str(err))
            return
        if not self.ask("Apply", f"Change network settings on {alias}?"):
            return
        if winutil.run_elevated(cmds):
            QTimer.singleShot(6000, self.refresh_net_config)
            QTimer.singleShot(8000, self.refresh_public_ip)
        else:
            self.tell("Network", "Admin approval was declined, so nothing changed.")

    def rebuild_profiles(self):
        while self.prof_row.count():
            w = self.prof_row.takeAt(0).widget()
            if w:
                w.deleteLater()
        profiles = self.cfg.get("profiles", {})
        self.prof_row.addWidget(label("Profiles", dim=True))
        for name in profiles:
            b = QPushButton(name)
            b.clicked.connect(lambda _=False, n=name: self.load_profile(n))
            b.setContextMenuPolicy(Qt.CustomContextMenu)
            b.customContextMenuRequested.connect(lambda _pos, n=name: self.delete_profile(n))
            b.setToolTip("Click to load, right-click to delete")
            self.prof_row.addWidget(b)
        self.prof_row.addStretch(1)

    def save_profile(self):
        dialog = QInputDialog(self)
        dialog.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        dialog.setWindowTitle("Save profile")
        dialog.setLabelText("Profile name")
        ok = dialog.exec() == QInputDialog.Accepted
        name = dialog.textValue()
        if ok and name.strip():
            self.cfg.setdefault("profiles", {})[name.strip()] = self.form_data()
            self.save()
            self.rebuild_profiles()

    def load_profile(self, name):
        d = self.cfg.get("profiles", {}).get(name)
        if not d:
            return
        self.f_ip.setText(d["ip"])
        self.f_mask.setText(d["mask"])
        self.f_gw.setText(d["gw"])
        self.f_dns.setText(d["dns"])
        self.set_static(d["static"])
        self.set_dns(d["dns_choice"])

    def delete_profile(self, name):
        self.cfg.get("profiles", {}).pop(name, None)
        self.save()
        self.rebuild_profiles()

    # ---------- ping ----------
    def pick_target(self, text):
        self.f_target.setText(self.netinfo.get("gateway", "") if text == "Gateway" else text)
        if not self.ping_stop:
            self.toggle_ping()

    def toggle_ping(self):
        if self.ping_stop:
            self.ping_stop.set()
            self.ping_stop = None
            self.b_ping.setText("Start")
            self.l_ping.setText("Stopped")
            return
        target = self.f_target.text().strip()
        if not target or any(c in target for c in ' "&|<>^%'):
            self.l_ping.setText("Enter a valid IP or hostname")
            return
        self.ping_stats = {"sent": 0, "lost": 0, "samples": deque(maxlen=60)}
        self.spark_ping.data.clear()
        stop = threading.Event()
        self.ping_stop = stop
        self.b_ping.setText("Stop")

        def loop():
            while not stop.is_set():
                t0 = time.time()
                ms = sysinfo.ping_once(target)
                if stop.is_set():
                    break
                self.bridge.result.emit(ms)
                stop.wait(max(0.0, 1.0 - (time.time() - t0)))
        threading.Thread(target=loop, daemon=True).start()

    def on_ping(self, ms):
        if not self.ping_stop:
            return
        s = self.ping_stats
        s["sent"] += 1
        if ms is None:
            s["lost"] += 1
        else:
            s["samples"].append(ms)
        self.spark_ping.push(ms)
        ok = list(s["samples"])
        now = f"{ms:.0f} ms" if ms is not None else "timeout"
        avg = f"{sum(ok) / len(ok):.0f}" if ok else "–"
        peak = f"{max(ok):.0f}" if ok else "–"
        loss = 100 * s["lost"] / s["sent"]
        self.l_ping.setText(f"Now {now} · avg {avg} · max {peak} · loss {loss:.0f}%")

    # ---------- updates ----------
    def check_updates(self, manual):
        def work():
            try:
                self.bridge.update_checked.emit(updater.latest_release(), manual)
            except (updater.UpdateError, ValueError) as err:
                self.bridge.update_checked.emit(str(err) or "Couldn't read the release info.", manual)
        threading.Thread(target=work, daemon=True).start()

    def on_update_checked(self, result, manual):
        if isinstance(result, str):  # error
            if manual:
                self.tell("Updates", result)
            return
        if updater.is_newer(result["tag"]):
            self.update_info = result
            if manual:
                self.prompt_update()
        else:
            self.update_info = None
            if manual:
                self.tell("Updates", f"You're up to date (version {updater.VERSION}).")

    def prompt_update(self):
        info = self.update_info
        if not info:
            return
        if updater.in_git_checkout():
            if self.ask("Update available", f"{info['tag']} is available. This copy is a git "
                        "checkout, so update it with git pull. Open the release page?"):
                webbrowser.open(info["page"])
            return
        notes = info["notes"].strip()[:400]
        if not self.ask("Update available", f"Version {info['tag']} is available "
                        f"(you have {updater.VERSION}).\n\n{notes}\n\nInstall it and restart?"):
            return

        def work():
            try:
                updater.install(info["zip"])
                self.bridge.update_installed.emit(None)
            except (updater.UpdateError, OSError) as err:
                self.bridge.update_installed.emit(str(err))
        threading.Thread(target=work, daemon=True).start()

    def on_update_installed(self, err):
        if err:
            self.tell("Updates", f"Update failed. {err}")
            return
        self.save()
        subprocess.Popen([sys.executable, os.path.join(updater.APP_DIR, "app.py")], cwd=updater.APP_DIR)
        self.quit()


def main():
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    card = Card()
    if "--selftest" in sys.argv:
        QTimer.singleShot(7000, lambda: (print("ok", card.l_ip.text(), card.m_cpu.val.text(), card.m_gpu.val.text()), card.quit()))
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
