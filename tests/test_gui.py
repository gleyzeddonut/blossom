import pytest

from gui import validate_config


def test_valid_config_passes_through():
    config, err = validate_config("KeyStep", "USB MIDI", "36", "1")
    assert err is None
    assert config == {"in_port": "KeyStep", "out_port": "USB MIDI",
                      "base": 36, "channel": 1}


@pytest.mark.parametrize("in_port,out_port", [("", "USB"), ("Key", ""), (None, "USB")])
def test_missing_ports_rejected(in_port, out_port):
    config, err = validate_config(in_port, out_port, "36", "1")
    assert config is None and "port" in err


def test_note_name_base_accepted():
    config, err = validate_config("a", "b", "C2", "1")
    assert err is None and config["base"] == 36


def test_bad_base_rejected():
    config, err = validate_config("a", "b", "H7", "1")
    assert config is None and "C-1" in err


@pytest.mark.parametrize("base", ["A9", "117", "C-2"])
def test_base_out_of_range_rejected(base):
    config, err = validate_config("a", "b", base, "1")
    assert config is None and "C-1" in err


def test_non_numeric_channel_rejected():
    config, err = validate_config("a", "b", "C2", "x")
    assert config is None and "Channel" in err


@pytest.mark.parametrize("channel", ["0", "17"])
def test_channel_out_of_range_rejected(channel):
    config, err = validate_config("a", "b", "36", channel)
    assert config is None and "1-16" in err
