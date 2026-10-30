"""System-wide hotkey (Ctrl+Alt+W) through RegisterHotKey and a Qt native event filter."""
import ctypes
import ctypes.wintypes as wt

from PySide6.QtCore import QAbstractNativeEventFilter

WM_HOTKEY = 0x0312
MOD_ALT, MOD_CONTROL, MOD_NOREPEAT = 0x1, 0x2, 0x4000
HOTKEY_ID = 0xB10C
user32 = ctypes.windll.user32


class Hotkey(QAbstractNativeEventFilter):
    def __init__(self, callback, key="W"):
        super().__init__()
        self.callback = callback
        self.ok = bool(user32.RegisterHotKey(None, HOTKEY_ID, MOD_CONTROL | MOD_ALT | MOD_NOREPEAT, ord(key)))

    def nativeEventFilter(self, event_type, message):
        if bytes(event_type) == b"windows_generic_MSG":
            msg = wt.MSG.from_address(int(message))
            if msg.message == WM_HOTKEY and msg.wParam == HOTKEY_ID:
                self.callback()
        return False, 0

    def unregister(self):
        if self.ok:
            user32.UnregisterHotKey(None, HOTKEY_ID)
            self.ok = False
