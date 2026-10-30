"""Update check and install from the project's GitHub releases."""
import io
import json
import os
import re
import shutil
import sys
import urllib.error
import urllib.parse
import urllib.request
import zipfile

VERSION = "1.2.0"
REPO = "BlackGhost3/desktop-stat-widget"
API = f"https://api.github.com/repos/{REPO}/releases/latest"
FROZEN = getattr(sys, "frozen", False)  # True when running as the packaged .exe
EXE_NAME = "DesktopStatWidget.exe"
APP_DIR = os.path.dirname(sys.executable if FROZEN else os.path.abspath(__file__))
KEEP = (".py", ".txt", ".bat", ".md")  # only these file types are ever overwritten


class UpdateError(Exception):
    pass


def _version_tuple(tag):
    return tuple(int(n) for n in re.findall(r"\d+", tag)[:3])


def is_newer(tag, current=VERSION):
    try:
        return _version_tuple(tag) > _version_tuple(current)
    except ValueError:
        return False


def _get(url, timeout=15):
    req = urllib.request.Request(url, headers={"User-Agent": "desktop-stat-widget", "Accept": "application/vnd.github+json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()
    except urllib.error.HTTPError as err:
        if err.code == 404:
            raise UpdateError("No releases have been published yet.") from err
        raise UpdateError(f"GitHub returned an error ({err.code}).") from err
    except (urllib.error.URLError, OSError) as err:
        raise UpdateError("Couldn't reach GitHub. Check your connection.") from err


def latest_release():
    """Returns {tag, notes, page, zip, exe} for the newest release."""
    data = json.loads(_get(API))
    exe = next((a.get("browser_download_url", "") for a in data.get("assets", []) if a.get("name") == EXE_NAME), "")
    return {"tag": data.get("tag_name", ""), "notes": data.get("body") or "",
            "page": data.get("html_url", f"https://github.com/{REPO}/releases"),
            "zip": data.get("zipball_url", ""), "exe": exe}


def in_git_checkout():
    return not FROZEN and os.path.isdir(os.path.join(APP_DIR, ".git"))


def cleanup_old_exe():
    """Removes the previous version left beside the exe by an update."""
    if FROZEN:
        try:
            os.remove(sys.executable + ".old")
        except OSError:
            pass


def install_exe(url, current=None):
    """Downloads the new exe and swaps it in. A running exe can be renamed but not overwritten,
    so the old one is renamed to .old and removed on the next launch. Returns the exe path to start."""
    if urllib.parse.urlparse(url).hostname != "github.com":
        raise UpdateError("Unexpected download address.")
    current = current or sys.executable
    new, old = current + ".new", current + ".old"
    req = urllib.request.Request(url, headers={"User-Agent": "desktop-stat-widget"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp, open(new, "wb") as out:
            shutil.copyfileobj(resp, out, 1 << 20)
        with open(new, "rb") as f:
            head = f.read(2)
        if head != b"MZ" or os.path.getsize(new) < 5_000_000:
            raise UpdateError("The download wasn't a valid program file.")
        if os.path.exists(old):
            os.remove(old)
        os.replace(current, old)
        os.replace(new, current)
    except (urllib.error.URLError, OSError) as err:
        _discard(new)
        raise UpdateError(f"Couldn't download or replace the program ({err}).") from err
    except UpdateError:
        _discard(new)
        raise
    return current


def _discard(path):
    try:
        os.remove(path)
    except OSError:
        pass


def install(zip_url, dest=APP_DIR):
    """Downloads the release zip and overwrites the app's source files. Returns files written."""
    if urllib.parse.urlparse(zip_url).hostname != "api.github.com":
        raise UpdateError("Unexpected download address.")
    try:
        archive = zipfile.ZipFile(io.BytesIO(_get(zip_url, timeout=60)))
    except zipfile.BadZipFile as err:
        raise UpdateError("The download wasn't a valid zip file.") from err
    written = []
    for info in archive.infolist():
        parts = info.filename.split("/")[1:]  # drop GitHub's top-level folder
        name = "/".join(parts)
        if info.is_dir() or not name or ".." in parts or not name.lower().endswith(KEEP):
            continue
        target = os.path.abspath(os.path.join(dest, name))
        if not target.startswith(os.path.abspath(dest) + os.sep):
            continue
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "wb") as f:
            f.write(archive.read(info))
        written.append(name)
    if "app.py" not in written:
        raise UpdateError("The release doesn't contain the app.")
    return written
