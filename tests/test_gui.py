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


def test_non_numeric_fields_rejected():
    config, err = validate_config("a", "b", "abc", "1")
    assert config is None and "numbers" in err


@pytest.mark.parametrize("base", ["-1", "117"])
def test_base_out_of_range_rejected(base):
    config, err = validate_config("a", "b", base, "1")
    assert config is None and "0-116" in err


@pytest.mark.parametrize("channel", ["0", "17"])
def test_channel_out_of_range_rejected(channel):
    config, err = validate_config("a", "b", "36", channel)
    assert config is None and "1-16" in err
