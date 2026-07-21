"""Self-update support: version comparison and fetching from GitHub."""

import urllib.request
from pathlib import Path

OWNER, REPO, BRANCH = "gleyzeddonut", "blossom", "main"
RAW_BASE = "https://raw.githubusercontent.com/%s/%s/%s/" % (OWNER, REPO, BRANCH)
APP_FILES = ("gui.py", "chords.py", "settings.py", "update.py",
             "requirements.txt", "VERSION")
UPDATE_DIR = Path.home() / "Library" / "Application Support" / "Blossom" / "app"
TIMEOUT = 10


def parse_version(text):
    """'1.2.3' -> (1, 2, 3); anything malformed -> (0,)."""
    try:
        return tuple(int(part) for part in str(text).strip().split("."))
    except ValueError:
        return (0,)


def is_newer(candidate, current):
    return parse_version(candidate) > parse_version(current)


def local_version():
    """Version of the code this process is running from."""
    try:
        return (Path(__file__).resolve().parent / "VERSION").read_text().strip()
    except OSError:
        return "0.0.0"


def fetch_remote_version():
    """Latest published version string, or None if unreachable."""
    try:
        with urllib.request.urlopen(RAW_BASE + "VERSION", timeout=TIMEOUT) as resp:
            return resp.read().decode().strip()
    except OSError:
        return None


def download_update(dest_dir=UPDATE_DIR):
    """Download the published app files into dest_dir. All-or-nothing."""
    staged = {}
    for name in APP_FILES:
        with urllib.request.urlopen(RAW_BASE + name, timeout=TIMEOUT) as resp:
            staged[name] = resp.read()
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)
    for name, data in staged.items():
        (dest / name).write_bytes(data)
