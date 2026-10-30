"""Color palette (dark/light/auto) and the Qt stylesheet built from it."""
import winreg


class _Palette:
    pass


P = _Palette()

DARK = dict(BG="#14151a", PANEL="#1c1e25", LINE="#2a2c35", HOVER="#34364a", BORDER="#3a3d4c",
            TEXT="#e8e9ee", DIM="#8b8fa0", BTN="#c9ccd8", SOFT="#232638",
            PURPLE="#b58cff", GREEN="#5fd8a6", AMBER="#f0a860", RED="#f07a7a")
LIGHT = dict(BG="#f6f7f9", PANEL="#ffffff", LINE="#e1e3ea", HOVER="#d2d5df", BORDER="#cdd0da",
             TEXT="#1b1d24", DIM="#6b7080", BTN="#3a3e4c", SOFT="#e4e9fb",
             PURPLE="#8a5ce0", GREEN="#1f9d70", AMBER="#c9791f", RED="#d94f4f")
ACCENTS = {"Blue": "#7f9cff", "Purple": "#b58cff", "Green": "#5fd8a6", "Amber": "#f0a860", "Pink": "#f27aa8"}
THEMES = ("auto", "dark", "light")


def system_prefers_light():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as key:
            return winreg.QueryValueEx(key, "AppsUseLightTheme")[0] == 1
    except OSError:
        return False


def resolve(name):
    return "light" if name == "light" or (name == "auto" and system_prefers_light()) else "dark"


def _darken(hex_color, factor):
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (1, 3, 5))
    return "#%02x%02x%02x" % (int(r * factor), int(g * factor), int(b * factor))


def apply(name, accent):
    """Loads the palette into P. Returns the resolved theme ('dark' or 'light')."""
    resolved = resolve(name)
    for key, value in (LIGHT if resolved == "light" else DARK).items():
        setattr(P, key, value)
    base = ACCENTS.get(accent, ACCENTS["Blue"])
    P.ACCENT = _darken(base, 0.78) if resolved == "light" else base
    P.ON_ACCENT = "#14151a" if resolved == "dark" else "#ffffff"
    P.RESOLVED = resolved
    return resolved


def stylesheet():
    return f"""
QLabel {{ color:{P.TEXT}; font-family:'Segoe UI'; font-size:12px; }}
QLabel[dim="true"] {{ color:{P.DIM}; font-size:11px; }}
QLabel[mono="true"] {{ font-family:Consolas; }}
QPushButton {{ color:{P.BTN}; background:{P.LINE}; border:none; border-radius:8px; padding:5px 10px; font-size:11px; }}
QPushButton:hover {{ background:{P.HOVER}; }}
QPushButton:checked {{ background:{P.ACCENT}; color:{P.ON_ACCENT}; }}
QPushButton[primary="true"] {{ background:{P.ACCENT}; color:{P.ON_ACCENT}; font-weight:500; }}
QPushButton[small="true"] {{ padding:2px 8px; border-radius:6px; }}
QLineEdit {{ color:{P.TEXT}; background:{P.PANEL}; border:0.5px solid {P.LINE}; border-radius:6px; padding:4px 7px;
             font-family:Consolas; font-size:12px; }}
QLineEdit:disabled {{ color:{P.DIM}; }}
QMenu {{ background:{P.PANEL}; color:{P.TEXT}; border:1px solid {P.LINE}; padding:4px; }}
QMenu::item {{ padding:5px 22px 5px 14px; border-radius:5px; }}
QMenu::item:selected {{ background:{P.LINE}; }}
QMenu::item:disabled {{ color:{P.DIM}; }}
QMenu::separator {{ height:1px; background:{P.LINE}; margin:4px 6px; }}
QToolTip {{ background:{P.PANEL}; color:{P.TEXT}; border:1px solid {P.LINE}; padding:3px; }}
QDialog, QMessageBox, QInputDialog {{ background:{P.PANEL}; }}
"""
