import pytest

import update


@pytest.mark.parametrize("text,expected", [
    ("1.0.0", (1, 0, 0)), ("2.10.3", (2, 10, 3)), (" 1.2 \n", (1, 2)),
    ("garbage", (0,)), ("", (0,)), (None, (0,)),
])
def test_parse_version(text, expected):
    assert update.parse_version(text) == expected


@pytest.mark.parametrize("cand,cur,newer", [
    ("1.0.1", "1.0.0", True), ("2.0.0", "1.9.9", True), ("1.0.0", "1.0.0", False),
    ("0.9.0", "1.0.0", False), ("1.10.0", "1.9.0", True), ("garbage", "1.0.0", False),
])
def test_is_newer(cand, cur, newer):
    assert update.is_newer(cand, cur) is newer


def test_local_version_reads_version_file():
    assert update.local_version() == open("VERSION").read().strip()
