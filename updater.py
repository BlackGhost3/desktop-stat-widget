"""Update check and install from the project's GitHub releases."""
import io
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
import zipfile

VERSION = "1.1.0"
REPO = "BlackGhost3/desktop-stat-widget"
API = f"https://api.github.com/repos/{REPO}/releases/latest"
APP_DIR = os.path.dirname(os.path.abspath(__file__))
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
    """Returns {tag, notes, page, zip} for the newest release."""
    data = json.loads(_get(API))
    return {"tag": data.get("tag_name", ""), "notes": data.get("body") or "",
            "page": data.get("html_url", f"https://github.com/{REPO}/releases"),
            "zip": data.get("zipball_url", "")}


def in_git_checkout():
    return os.path.isdir(os.path.join(APP_DIR, ".git"))


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
