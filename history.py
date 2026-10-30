"""Separate window listing past local speed tests, so the main widget stays small."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QMenu, QPushButton, QScrollArea, QVBoxLayout, QWidget

import theme
from theme import P


def rate(mbps):
    return f"{mbps / 1000:.2f} Gb/s" if mbps >= 1000 else f"{mbps:.0f} Mb/s"


class HistoryWindow(QWidget):
    def __init__(self, results, name_of, rename, clear):
        super().__init__(None, Qt.Window | Qt.WindowStaysOnTopHint)
        self.results, self.name_of, self.rename, self.clear = results, name_of, rename, clear
        self.setWindowTitle("Local speed test history")
        self.resize(400, 520)
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(10)
        self.title = QLabel()
        root.addWidget(self.title)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.rows = QWidget()
        self.rows.setObjectName("rows")
        self.rows_layout = QVBoxLayout(self.rows)
        self.rows_layout.setContentsMargins(0, 0, 4, 0)
        self.rows_layout.setSpacing(8)
        self.scroll.setWidget(self.rows)
        root.addWidget(self.scroll, 1)
        foot = QHBoxLayout()
        self.b_clear = QPushButton("Clear history")
        self.b_clear.clicked.connect(self.on_clear)
        b_close = QPushButton("Close")
        b_close.clicked.connect(self.close)
        foot.addWidget(self.b_clear)
        foot.addStretch(1)
        foot.addWidget(b_close)
        root.addLayout(foot)
        self.refresh()

    def on_clear(self):
        self.clear()
        self.refresh()

    def refresh(self):
        self.setStyleSheet(theme.stylesheet() + f"HistoryWindow {{ background:{P.BG}; }}"
                           f"QScrollArea {{ background:transparent; border:none; }}"
                           f"#rows {{ background:transparent; }}"
                           f"QFrame#entry {{ background:{P.PANEL}; border-radius:10px; }}")
        items = list(self.results())
        self.title.setText(f"<b>Local speed test history</b> <span style='color:{P.DIM}'>· {len(items)} "
                           f"result{'s' if len(items) != 1 else ''}. Right-click an entry to rename the device.</span>")
        self.b_clear.setEnabled(bool(items))
        while self.rows_layout.count():
            item = self.rows_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        if not items:
            empty = QLabel("No tests yet. Run the local speed test from a phone and the results will appear here.")
            empty.setWordWrap(True)
            empty.setStyleSheet(f"color:{P.DIM};")
            self.rows_layout.addWidget(empty)
        for r in items:
            self.rows_layout.addWidget(self.entry(r))
        self.rows_layout.addStretch(1)

    def entry(self, r):
        frame = QFrame()
        frame.setObjectName("entry")
        frame.setContextMenuPolicy(Qt.CustomContextMenu)
        frame.customContextMenuRequested.connect(lambda _p, ip=r["ip"]: self.menu(ip))
        frame.setToolTip("Right-click to rename this device")
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(12, 9, 12, 9)
        lay.setSpacing(3)
        head = QLabel(f"<b>{self.name_of(r)}</b> <span style='color:{P.DIM}'>· {r['ip']}</span>")
        when = QLabel(r["time"])
        when.setStyleSheet(f"color:{P.DIM}; font-size:11px;")
        top = QHBoxLayout()
        top.addWidget(head, 1)
        top.addWidget(when)
        lay.addLayout(top)
        speeds = QLabel(f"<span style='color:{P.ACCENT}; font-size:16px'><b>↓ {rate(r['down'])}</b></span>"
                        f"&nbsp;&nbsp;&nbsp;<span style='color:{P.PURPLE}; font-size:16px'><b>↑ {rate(r['up'])}</b></span>"
                        f"&nbsp;&nbsp;&nbsp;<span style='color:{P.DIM}'>{r['ping']:.0f} ms</span>")
        lay.addWidget(speeds)
        return frame

    def menu(self, ip):
        menu = QMenu(self)
        menu.addAction(f"Rename {ip}…", lambda: self.rename(ip))
        menu.exec(QCursor.pos())
