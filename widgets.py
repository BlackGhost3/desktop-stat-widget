"""Small custom-painted widgets. Colors are read from the theme at paint time."""
from collections import deque

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
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
