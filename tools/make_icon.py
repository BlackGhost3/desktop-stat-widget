"""Draws assets/icon.ico (the tray icon design, at 256 px) for the packaged exe."""
import os
import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPixmap

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    app = QGuiApplication(sys.argv)
    size = 256
    pix = QPixmap(size, size)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor("#14151a"))
    p.drawRoundedRect(8, 8, 240, 240, 60, 60)
    for i, (h, color) in enumerate(((96, "#7f9cff"), (160, "#5fd8a6"), (64, "#f0a860"))):
        p.setBrush(QColor(color))
        p.drawRoundedRect(48 + i * 64, 208 - h, 40, h, 16, 16)
    p.end()
    os.makedirs(os.path.join(ROOT, "assets"), exist_ok=True)
    out = os.path.join(ROOT, "assets", "icon.ico")
    print("saved" if pix.save(out, "ICO") else "failed", out)
    del app


if __name__ == "__main__":
    main()
