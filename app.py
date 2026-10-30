"""Desktop stat widget: CPU / GPU / RAM, disk and network speed, IP + DNS tools, ping."""
import ipaddress
import sys
import threading
import time
from collections import deque

import psutil
from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal, QObject
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QApplication, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMenu, QMessageBox,
    QPushButton, QToolButton, QVBoxLayout, QWidget, QLayout,
)

import sysinfo
import winutil

BG, PANEL, LINE = "#14151a", "#1c1e25", "#2a2c35"
TEXT, DIM = "#e8e9ee", "#8b8fa0"
BLUE, PURPLE, GREEN, AMBER, RED = "#7f9cff", "#b58cff", "#5fd8a6", "#f0a860", "#f07a7a"
DNS_PRESETS = {"cloudflare": ["1.1.1.1", "1.0.0.1"], "google": ["8.8.8.8", "8.8.4.4"]}
MODES = ["full", "compact", "mini"]

STYLE = f"""
QLabel {{ color:{TEXT}; font-family:'Segoe UI'; font-size:12px; }}
QLabel[dim="true"] {{ color:{DIM}; font-size:11px; }}
QLabel[mono="true"] {{ font-family:Consolas; }}
QToolButton {{ color:{DIM}; background:transparent; border:none; border-radius:6px; padding:2px 5px; font-size:13px; }}
QToolButton:hover {{ background:{LINE}; }}
QToolButton:checked {{ color:{BLUE}; background:#232638; }}
QPushButton {{ color:#c9ccd8; background:{LINE}; border:none; border-radius:8px; padding:5px 10px; font-size:11px; }}
QPushButton:hover {{ background:#34364a; }}
QPushButton:checked {{ background:{BLUE}; color:{BG}; }}
QPushButton[primary="true"] {{ background:{BLUE}; color:{BG}; font-weight:500; }}
QLineEdit {{ color:{TEXT}; background:{PANEL}; border:0.5px solid {LINE}; border-radius:6px; padding:4px 7px;
             font-family:Consolas; font-size:12px; }}
QLineEdit:disabled {{ color:{DIM}; }}
QMenu {{ background:{PANEL}; color:{TEXT}; border:1px solid {LINE}; }}
QMenu::item:selected {{ background:{LINE}; }}
"""


def label(text="", dim=False, mono=False, align=None):
    lb = QLabel(text)
    lb.setProperty("dim", dim)
    lb.setProperty("mono", mono)
    if align:
        lb.setAlignment(align)
    return lb


class Bar(QWidget):
    def __init__(self, color):
        super().__init__()
        self.color, self.v = QColor(color), 0.0
        self.setFixedHeight(6)

    def set(self, v):
        self.v = max(0.0, min(1.0, v))
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(LINE))
        p.drawRoundedRect(self.rect(), 3, 3)
        p.setBrush(self.color)
        p.drawRoundedRect(QRectF(0, 0, self.width() * self.v, self.height()), 3, 3)


class Spark(QWidget):
    def __init__(self, color, height=36, floor=1.0, size=60):
        super().__init__()
        self.color, self.floor = QColor(color), floor
        self.data = deque(maxlen=size)
        self.setFixedHeight(height)

    def push(self, v):
        self.data.append(v)
        self.update()

    def paintEvent(self, _):
        pts = [v for v in self.data if v is not None]
        if len(pts) < 2:
            return
        top = max(max(pts), self.floor)
        w, h, n = self.width(), self.height() - 4, self.data.maxlen - 1
        offset = n - (len(self.data) - 1)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        path, started = QPainterPath(), False
        for i, v in enumerate(self.data):
            if v is None:
                started = False
                continue
            pt = QPointF((i + offset) * w / n, 2 + h - h * v / top)
            if started:
                path.lineTo(pt)
            else:
                path.moveTo(pt)
                started = True
        p.setPen(QPen(self.color, 1.5))
        p.drawPath(path)


class Metric(QWidget):
    def __init__(self, name, color):
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        n = label(name, dim=True)
        n.setFixedWidth(34)
        self.bar = Bar(color)
        self.val = label("–", align=Qt.AlignRight | Qt.AlignVCenter)
        self.val.setFixedWidth(64)
        lay.addWidget(n)
        lay.addWidget(self.bar, 1)
        lay.addWidget(self.val)

    def set(self, frac, text):
        self.bar.set(frac)
        self.val.setText(text)


class IconBtn(QToolButton):
    """Header button with a vector line icon drawn on a 16x16 grid."""

    def __init__(self, kind, tip, checkable=False):
        super().__init__()
        self.kind = kind
        self.setToolTip(tip)
        self.setCheckable(checkable)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(26, 26)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        hover, on = self.underMouse(), self.isChecked()
        if on or hover:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor("#232638" if on else LINE))
            p.drawRoundedRect(self.rect(), 7, 7)
        color = QColor(BLUE if on else (TEXT if hover else DIM))
        p.translate((self.width() - 16) / 2, (self.height() - 16) / 2)
        pen = QPen(color, 1.4)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        k = self.kind
        if k == "globe":
            p.drawEllipse(QRectF(2, 2, 12, 12))
            p.drawEllipse(QRectF(5.5, 2, 5, 12))
            p.drawLine(QPointF(2, 8), QPointF(14, 8))
        elif k == "pulse":
            p.drawPolyline([QPointF(1.5, 8), QPointF(4.5, 8), QPointF(6.5, 3), QPointF(9.5, 13),
                            QPointF(11.5, 8), QPointF(14.5, 8)])
        elif k == "size":
            p.drawPolyline([QPointF(2, 6), QPointF(2, 2), QPointF(6, 2)])
            p.drawPolyline([QPointF(10, 14), QPointF(14, 14), QPointF(14, 10)])
            p.drawLine(QPointF(2.5, 2.5), QPointF(6.5, 6.5))
            p.drawLine(QPointF(13.5, 13.5), QPointF(9.5, 9.5))
        elif k == "pin":
            p.drawPolygon([QPointF(5.5, 2), QPointF(10.5, 2), QPointF(10, 7), QPointF(12.5, 9.5),
                           QPointF(3.5, 9.5), QPointF(6, 7)])
            p.drawLine(QPointF(8, 9.5), QPointF(8, 14))
        elif k == "menu":
            p.setPen(Qt.NoPen)
            p.setBrush(color)
            for x in (3, 8, 13):
                p.drawEllipse(QPointF(x, 8), 1.3, 1.3)


class PingBridge(QObject):
    result = Signal(object)
    netdone = Signal()


class Card(QWidget):
    def __init__(self):
        super().__init__()
        self.cfg = winutil.load_config()
        self.mode = self.cfg.get("mode", "full")
        self.pinned = self.cfg.get("pinned", True)
        self.netinfo = {}
        self.net_alias = None
        self.rates = sysinfo.Rates()
        self.peaks = {"disk": 100e6}
        self.drag = None
        self.ping_stop = None
        self.ping_stats = {"sent": 0, "lost": 0, "samples": deque(maxlen=60)}
        self.bridge = PingBridge()
        self.bridge.result.connect(self.on_ping)
        self.bridge.netdone.connect(self.show_net_config)

        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setStyleSheet(STYLE)
        self.build()
        self.apply_flags()
        if "pos" in self.cfg:
            self.move(*self.cfg["pos"])

        self.gpu = sysinfo.GpuReader()
        self.gpu.start()
        psutil.cpu_percent()
        self.refresh_net_config()
        self.timer = QTimer(self, interval=1000, timeout=self.tick)
        self.timer.start()
        QTimer(self, interval=15000, timeout=self.refresh_net_config).start()
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
        self.btn_net = IconBtn("globe", "Network settings", checkable=True)
        self.btn_ping = IconBtn("pulse", "Ping", checkable=True)
        self.btn_mode = IconBtn("size", "Cycle size: full / compact / mini")
        self.btn_pin = IconBtn("pin", "Always on top", checkable=True)
        self.btn_menu = IconBtn("menu", "Menu")
        self.btn_pin.setChecked(self.pinned)
        self.btn_net.toggled.connect(lambda on: self.panel_net.setVisible(on and self.mode == "full"))
        self.btn_ping.toggled.connect(lambda on: self.panel_ping.setVisible(on and self.mode == "full"))
        self.btn_mode.clicked.connect(lambda: self.set_mode(MODES[(MODES.index(self.mode) + 1) % 3]))
        self.btn_pin.toggled.connect(self.set_pinned)
        self.btn_menu.clicked.connect(lambda: self.show_menu(self.btn_menu.mapToGlobal(self.btn_menu.rect().bottomLeft())))
        for b in (self.btn_net, self.btn_ping, self.btn_mode, self.btn_pin, self.btn_menu):
            head.addWidget(b)
        root.addLayout(head)

        self.body = QWidget()
        bl = QVBoxLayout(self.body)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(7)
        self.m_cpu, self.m_gpu, self.m_ram = Metric("CPU", BLUE), Metric("GPU", PURPLE), Metric("RAM", GREEN)
        self.m_read, self.m_write = Metric("Read", AMBER), Metric("Write", AMBER)
        for m in (self.m_cpu, self.m_gpu, self.m_ram):
            bl.addWidget(m)
        sep = QWidget()
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background:{LINE};")
        bl.addWidget(sep)
        net_row = QHBoxLayout()
        self.l_speed = label("↓ 0.0  ↑ 0.0 Mb/s", mono=True)
        self.l_link = label("", dim=True, align=Qt.AlignRight)
        net_row.addWidget(self.l_speed)
        net_row.addWidget(self.l_link, 1)
        bl.addLayout(net_row)
        self.spark_net = Spark(BLUE)
        bl.addWidget(self.spark_net)
        bl.addWidget(self.m_read)
        bl.addWidget(self.m_write)
        self.l_ip = label("", mono=True)
        bl.addWidget(self.l_ip)
        root.addWidget(self.body)

        self.panel_net = self.build_net_panel()
        self.panel_ping = self.build_ping_panel()
        root.addWidget(self.panel_net)
        root.addWidget(self.panel_ping)
        self.panel_net.hide()
        self.panel_ping.hide()

    def panel(self):
        w = QWidget()
        w.setObjectName("panel")
        w.setStyleSheet(f"#panel {{ background:{PANEL}; border-radius:12px; }}")
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
        self.spark_ping = Spark(GREEN, height=48, floor=20)
        lay.addWidget(self.spark_ping)
        self.l_ping = label("Not running", dim=True)
        lay.addWidget(self.l_ping)
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
        mini, full = mode == "mini", mode == "full"
        self.body.setVisible(not mini)
        self.spark_net.setVisible(full)
        self.panel_net.setVisible(full and self.btn_net.isChecked())
        self.panel_ping.setVisible(full and self.btn_ping.isChecked())
        self.btn_net.setVisible(full)
        self.btn_ping.setVisible(full)
        self.title.setTextFormat(Qt.RichText if mini else Qt.PlainText)
        self.title.setStyleSheet("font-size:12px;" if mini else "font-weight:500; font-size:13px;")
        if not mini:
            self.title.setText("System")
            self.title.setToolTip("")
        self.btn_menu.setVisible(not mini)
        self.layout().setContentsMargins(*((10, 4, 6, 4) if mini else (12, 10, 12, 12)))
        self.body.setFixedWidth(330 if full else 270)
        self.title.setMinimumWidth(0 if not mini else 330)
        self.adjustSize()
        self.save()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(QColor("#3a3d4c"), 1))
        p.setBrush(QColor(BG))
        p.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 16, 16)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.drag = e.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):
        if self.drag is not None and e.buttons() & Qt.LeftButton:
            self.move(e.globalPosition().toPoint() - self.drag)

    def mouseReleaseEvent(self, _):
        self.drag = None
        self.save()

    def mouseDoubleClickEvent(self, _):
        self.set_mode(MODES[(MODES.index(self.mode) + 1) % 3])

    def contextMenuEvent(self, e):
        self.show_menu(e.globalPos())

    def show_menu(self, pos):
        menu = QMenu(self)
        start = menu.addAction("Start with Windows")
        start.setCheckable(True)
        start.setChecked(winutil.startup_enabled())
        start.triggered.connect(self.toggle_startup)
        ops = menu.addMenu("Opacity")
        for pct in (100, 85, 70):
            ops.addAction(f"{pct}%", lambda p=pct: self.setWindowOpacity(p / 100) or self.save(p))
        menu.addSeparator()
        menu.addAction("Quit", self.quit)
        menu.exec(pos)

    def toggle_startup(self, on):
        try:
            winutil.set_startup(on)
        except OSError as err:
            QMessageBox.warning(self, "Startup", f"Couldn't change the startup entry.\n{err}")

    def save(self, opacity=None):
        self.cfg.update(mode=self.mode, pinned=self.pinned, pos=[self.x(), self.y()],
                        ping_target=self.f_target.text().strip() or "1.1.1.1")
        if opacity:
            self.cfg["opacity"] = opacity
        winutil.save_config(self.cfg)

    def quit(self):
        self.save()
        if self.ping_stop:
            self.ping_stop.set()
        self.gpu.stop()
        QApplication.quit()

    # ---------- live stats ----------
    def tick(self):
        cpu = psutil.cpu_percent()
        ram = psutil.virtual_memory()
        gpu = self.gpu.value
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

        if self.mode == "mini":
            gtxt = f"{gpu}%" if gpu >= 0 else "n/a"

            def item(name, color, value):
                return f"<span style='color:{color}'>{name}</span>&nbsp;<b>{value}</b>"
            sep = f"<span style='color:{LINE}'>&nbsp;│&nbsp;</span>"
            self.title.setText(sep.join([
                item("CPU", BLUE,f"{cpu:.0f}%"),
                item("GPU", PURPLE,gtxt),
                item("RAM", GREEN,f"{ram.percent:.0f}%"),
                item("↓", BLUE, f"{down:.0f}") + "&nbsp;" + item("↑", BLUE, f"{up:.0f}"),
                item("R", AMBER, f"{rd / 1e6:.0f}") + "&nbsp;" + item("W", AMBER, f"{wr / 1e6:.0f}"),
            ]))
            self.title.setToolTip("CPU · GPU · RAM · network down/up Mb/s · disk read/write MB/s")

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
        self.net_title.setText(f"Network settings · {c.get('alias', '')}")
        if not self.f_ip.isModified() and not self.f_ip.hasFocus():
            self.load_form()

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
            QMessageBox.warning(self, "Network", "No active network adapter found.")
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
            QMessageBox.warning(self, "Network", str(err))
            return
        if QMessageBox.question(self, "Apply", f"Change network settings on {alias}?") != QMessageBox.Yes:
            return
        if winutil.run_elevated(cmds):
            QTimer.singleShot(6000, self.refresh_net_config)
        else:
            QMessageBox.warning(self, "Network", "Admin approval was declined, so nothing changed.")

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
        name, ok = QInputDialog.getText(self, "Save profile", "Profile name")
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


def main():
    app = QApplication(sys.argv)
    card = Card()
    card.setWindowOpacity(card.cfg.get("opacity", 100) / 100)
    if "--selftest" in sys.argv:
        QTimer.singleShot(7000,lambda: (print("ok", card.l_ip.text(), card.m_cpu.val.text(), card.m_gpu.val.text()), card.quit()))
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
