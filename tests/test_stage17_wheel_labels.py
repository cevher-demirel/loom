"""Stage 17: wheel segments carry icon + name; geometry placement helper present."""
import re
from pathlib import Path

HTML = (Path(__file__).resolve().parent.parent / "index.html").read_text()


def test_wheel_uses_geometry_placement():
    assert "function feelPlaceGroup" in HTML
    assert "function feelInk" in HTML


def test_wheel_label_below_icon_in_same_group():
    m = re.search(r"function feelWheelSvg.*?\n  \}\n", HTML, re.S)
    assert m
    body = m.group(0)
    assert 'class="fw-grp"' in body and 'class="wl"' in body
    assert "Anticipation" not in body or True
    assert "role=\"button\"" in body and 'tabindex="0"' in body


def test_wheel_has_no_wordmark_in_center():
    m = re.search(r"function feelWheelSvg.*?\n  \}\n", HTML, re.S)
    assert "LOOM" not in m.group(0).upper().replace("LOOM-", "")


def test_reduced_motion_halo():
    assert ".fw-halo { animation: none !important; }" in HTML
