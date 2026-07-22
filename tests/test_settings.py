import json

import settings


def test_load_missing_file_returns_defaults(tmp_path):
    assert settings.load(tmp_path / "nope.json") == settings.DEFAULTS


def test_load_corrupt_file_returns_defaults(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text("{not json")
    assert settings.load(path) == settings.DEFAULTS


def test_save_load_roundtrip(tmp_path):
    path = tmp_path / "settings.json"
    data = {"in_port": "KeyStep", "out_port": "USB MIDI", "base": 48,
            "channel": 3, "key": "D", "spread": True, "strum": 40,
            "mono": True, "offkey": "snap", "voicing": "smart", "voice_lead": False, "humanize": 12, "arp": True,
            "tempo": 100, "arp_div": "1/16", "arp_pattern": "updn",
            "arp_oct": 2, "arp_gate": 45, "mode": "minor", "clock_port": "IAC Bus 1",
            "chord_keys": ["dim"] * 12, "sync_on": True, "float_on_top": True}
    settings.save(data, path)
    assert settings.load(path) == data


def test_load_ignores_unknown_keys_and_fills_missing(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"in_port": "KeyStep", "bogus": 1}))
    loaded = settings.load(path)
    assert loaded["in_port"] == "KeyStep"
    assert loaded["base"] == settings.DEFAULTS["base"]
    assert "bogus" not in loaded


def test_save_creates_missing_parent_directories(tmp_path):
    path = tmp_path / "nested" / "deeper" / "settings.json"
    settings.save({"in_port": "x"}, path)
    assert settings.load(path)["in_port"] == "x"


def test_default_path_is_in_application_support():
    assert "Application Support/Blossom" in str(settings.SETTINGS_PATH)
