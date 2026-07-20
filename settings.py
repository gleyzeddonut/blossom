"""Persisted GUI settings (port names, zone base, user-facing channel 1-16)."""

import json
from pathlib import Path

SETTINGS_PATH = Path(__file__).resolve().parent / "settings.json"
DEFAULTS = {"in_port": "", "out_port": "", "base": 36, "channel": 1}


def load(path=SETTINGS_PATH):
    """Defaults merged with whatever valid keys the file has; never raises."""
    try:
        data = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return dict(DEFAULTS)
    merged = dict(DEFAULTS)
    if isinstance(data, dict):
        merged.update({k: data[k] for k in DEFAULTS if k in data})
    return merged


def save(values, path=SETTINGS_PATH):
    Path(path).write_text(json.dumps(values, indent=2))
