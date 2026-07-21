import pytest

from gui import validate_config


@pytest.fixture
def piano():
    from AppKit import NSMakeRect
    from gui import PianoView
    return PianoView.alloc().initWithFrame_(NSMakeRect(0, 0, 380, 88))


def test_note_at_edges(piano):
    assert piano.note_at(1, 10) == 24       # C1, leftmost white
    assert piano.note_at(379, 10) == 96     # C7, rightmost white


def test_note_at_out_of_bounds(piano):
    assert piano.note_at(-5, 10) is None
    assert piano.note_at(400, 10) is None


def test_note_at_black_key_and_white_below(piano):
    _, height, _, key_w = piano._geometry()
    x = key_w  # boundary of first two whites: C#1 black key sits here
    assert piano.note_at(x, height - 5) == 25   # black key on top
    assert piano.note_at(x, 5) == 26            # white key below it


def test_set_zone_filters_to_piano_range(piano):
    piano.set_zone(range(20, 30))
    assert piano.zone == {24, 25, 26, 27, 28, 29}


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
