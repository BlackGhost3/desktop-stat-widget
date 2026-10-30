"""Small custom-painted widgets. Colors are read from the theme at paint time."""
import math
from collections import deque

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QHBoxLayout, QLabel, QToolButton, QWidget

from theme import P


def label(text="", dim=False, mono=False, align=None):
    lb = QLabel(text)
    lb.setProperty("dim", dim)
    lb.setProperty("mono", mono)
    lb.setAttribute(Qt.WA_TransparentForMouseEvents)
    if align:
        lb.setAlignment(align)
    return lb


class Bar(QWidget):
    def __init__(self, key):
        super().__init__()
        self.key, self.v = key, 0.0
        self.setFixedHeight(6)

    def set(self, v):
        self.v = max(0.0, min(1.0, v))
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(P.LINE))
        p.drawRoundedRect(self.rect(), 3, 3)
        p.setBrush(QColor(getattr(P, self.key)))
        p.drawRoundedRect(QRectF(0, 0, self.width() * self.v, self.height()), 3, 3)


class Spark(QWidget):
    def __init__(self, key, height=36, floor=1.0, size=60):
        super().__init__()
        self.key, self.floor = key, floor
        self.data = deque(maxlen=size)
        self.setFixedHeight(height)

    def push(self, v):
        self.data.append(v)
        self.update()

    def load(self, values):
        self.data = deque(values, maxlen=self.data.maxlen)
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
        p.setPen(QPen(QColor(getattr(P, self.key)), 1.5))
        p.drawPath(path)


class Gauge(QWidget):
    """Speedtest-style 270 degree dial with a non-linear scale, a needle and an eased value."""

    MARKS = (0, 5, 10, 50, 100, 250, 500, 750, 1000)
    START, SWEEP = 225.0, 270.0

    def __init__(self, height=170):
        super().__init__()
        self.setFixedHeight(height)
        self.shown = self.target = 0.0
        self.phase, self.key, self.done = "", "ACCENT", False
        self.timer = QTimer(self, interval=25, timeout=self.ease)

    def frac(self, v):
        v = max(0.0, min(self.MARKS[-1], v))
        for i in range(len(self.MARKS) - 1):
            lo, hi = self.MARKS[i], self.MARKS[i + 1]
            if v <= hi:
                return (i + (v - lo) / (hi - lo)) / (len(self.MARKS) - 1)
        return 1.0

    def set_value(self, mbps, phase=None, key=None):
        self.target = mbps
        if phase is not None:
            self.done = False
        if phase is not None:
            self.phase = phase
        if key:
            self.key = key
        if not self.timer.isActive():
            self.timer.start()

    def reset(self):
        self.shown = self.target = 0.0
        self.phase, self.done = "", False
        self.update()

    def finish(self):
        """Test over: the needle falls back to zero and the dial says so, leaving the results to the tiles."""
        self.done = True
        self.set_value(0.0)

    def ease(self):
        self.shown += (self.target - self.shown) * 0.25
        if abs(self.target - self.shown) < 0.05:
            self.shown = self.target
            self.timer.stop()
        self.update()

    def point(self, f, radius, cx, cy):
        ang = math.radians(self.START - self.SWEEP * f)
        return QPointF(cx + radius * math.cos(ang), cy - radius * math.sin(ang))

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        cx, cy = self.width() / 2, self.height() / 2 + 2
        r = min(self.width(), self.height()) / 2 - 14
        box = QRectF(cx - r, cy - r, 2 * r, 2 * r)
        pen = QPen(QColor(P.LINE), 9)
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        p.drawArc(box, int(self.START * 16), int(-self.SWEEP * 16))
        f = self.frac(self.shown)
        color = QColor(getattr(P, self.key))
        if f > 0:
            pen.setColor(color)
            p.setPen(pen)
            p.drawArc(box, int(self.START * 16), int(-self.SWEEP * f * 16))
        font = QFont("Segoe UI", 7)
        p.setFont(font)
        p.setPen(QColor(P.DIM))
        for i, mark in enumerate(self.MARKS):
            pt = self.point(i / (len(self.MARKS) - 1), r - 19, cx, cy)
            p.drawText(QRectF(pt.x() - 16, pt.y() - 7, 32, 14), Qt.AlignCenter, str(mark))
        tip = self.point(f, r - 28, cx, cy)
        p.setPen(QPen(QColor(P.TEXT), 2, Qt.SolidLine, Qt.RoundCap))
        if not self.done:
            p.drawLine(QPointF(cx, cy), tip)
        p.setBrush(QColor(P.TEXT))
        p.drawEllipse(QPointF(cx, cy), 4, 4)
        p.setPen(QColor(P.TEXT))
        big = QFont("Segoe UI", 17)
        big.setWeight(QFont.Medium)
        p.setFont(big)
        number = "Done" if self.done else (f"{self.shown:.1f}" if self.shown < 100 else f"{self.shown:.0f}")
        p.drawText(QRectF(cx - 60, cy + r * 0.32, 120, 28), Qt.AlignCenter, number)
        p.setFont(QFont("Segoe UI", 8))
        p.setPen(QColor(P.DIM))
        caption = "Results below" if self.done else (f"{self.phase} · Mb/s" if self.phase else "Mb/s")
        p.drawText(QRectF(cx - 90, cy + r * 0.32 + 26, 180, 14), Qt.AlignCenter, caption)


class QrView(QWidget):
    """Draws a QR code (always dark on white so phones can scan it in any theme)."""

    def __init__(self, size=150):
        super().__init__()
        self.rows = []
        self.setFixedSize(size, size)

    def set_data(self, text):
        import segno
        self.rows = [list(r) for r in segno.make(text, error="m").matrix]
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, False)
        p.fillRect(self.rect(), QColor("#ffffff"))
        n = len(self.rows)
        if not n:
            return
        cell = (self.width() - 16) / n
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#14151a"))
        for y, row in enumerate(self.rows):
            for x, bit in enumerate(row):
                if bit:
                    p.drawRect(QRectF(8 + x * cell, 8 + y * cell, cell + 0.5, cell + 0.5))


class Metric(QWidget):
    def __init__(self, name, key):
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        n = label(name, dim=True)
        n.setFixedWidth(34)
        self.bar = Bar(key)
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
            p.setBrush(QColor(P.SOFT if on else P.LINE))
            p.drawRoundedRect(self.rect(), 7, 7)
        color = QColor(P.ACCENT if on else (P.TEXT if hover else P.DIM))
        p.translate((self.width() - 16) / 2, (self.height() - 16) / 2)
        pen = QPen(color, 1.4)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        k = self.kind
        if k == "tools":
            for x, y in ((2, 2), (9, 2), (2, 9), (9, 9)):
                p.drawRoundedRect(QRectF(x, y, 5, 5), 1.5, 1.5)
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
