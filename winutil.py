"""Windows helpers: start-with-Windows registry entry, elevated command runner, config file."""
import ctypes
import json
import os
import sys
import tempfile
import winreg

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
APP_NAME = "DesktopStatWidget"
CONFIG_DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "StatWidget")
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")


def _launch_command():
    exe = sys.executable
    if getattr(sys, "frozen", False):
        return f'"{exe}"'  # the packaged app is its own launcher
    if exe.lower().endswith("python.exe"):
        exe = exe[:-10] + "pythonw.exe"  # no console window at login
    script = os.path.abspath(os.path.join(os.path.dirname(__file__), "app.py"))
    return f'"{exe}" "{script}"'


def startup_enabled():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.QueryValueEx(key, APP_NAME)
            return True
    except FileNotFoundError:
        return False


def set_startup(enabled):
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        if enabled:
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, _launch_command())
        else:
            try:
                winreg.DeleteValue(key, APP_NAME)
            except FileNotFoundError:
                pass


def run_elevated(commands):
    """Runs cmd lines in one UAC-elevated batch. Returns False if the prompt couldn't open."""
    fd, path = tempfile.mkstemp(suffix=".bat")
    with os.fdopen(fd, "w") as f:
        f.write("@echo off\n" + "\n".join(commands) + "\ndel \"%~f0\"\n")
    rc = ctypes.windll.shell32.ShellExecuteW(None, "runas", "cmd.exe", f'/c "{path}"', None, 0)
    return rc > 32


def load_config():
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_config(cfg):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)
