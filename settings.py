"""Persisted GUI settings (port names, zone base, user-facing channel 1-16)."""

import json
from pathlib import Path

SETTINGS_PATH = (Path.home() / "Library" / "Application Support" / "Blossom"
                 / "settings.json")
DEFAULTS = {"in_port": "", "out_port": "", "base": 36, "channel": 1,
            "key": "Off", "spread": False, "strum": 0, "mono": False,
            "offkey": "V7", "voicing": "1-3-5", "voice_lead": True, "humanize": 0, "arp": False, "tempo": 120, "arp_div": "1/8", "arp_pattern": "up", "arp_oct": 1, "arp_gate": 60,
            "mode": "major", "clock_port": "Off", "sync_on": False, "float_on_top": False,
            "chord_keys": ["major", "maj7", "minor", "min7", "dom7", "add9",
                           "sus4", "13", "halfdim", "dim", "aug", "\u2014"]}


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
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(values, indent=2))
