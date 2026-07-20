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
    data = {"in_port": "KeyStep", "out_port": "USB MIDI", "base": 48, "channel": 3}
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
    assert "Application Support/Orchid" in str(settings.SETTINGS_PATH)
