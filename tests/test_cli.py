import pytest

from orchid import pick_port

PORTS = ["IAC Driver Bus 1", "Arturia KeyStep 32", "USB MIDI Interface"]


def test_pick_port_by_index():
    assert pick_port(PORTS, "1") == "Arturia KeyStep 32"


def test_pick_port_by_name_substring_case_insensitive():
    assert pick_port(PORTS, "keystep") == "Arturia KeyStep 32"


def test_pick_port_no_match_exits():
    with pytest.raises(SystemExit):
        pick_port(PORTS, "moog")


def test_pick_port_ambiguous_match_exits():
    with pytest.raises(SystemExit):
        pick_port(PORTS, "i")  # matches all three


def test_pick_port_index_out_of_range_exits():
    with pytest.raises(SystemExit):
        pick_port(PORTS, "9")
