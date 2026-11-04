"""Stage 23g -- design tokens exist, mechanical consolidation is complete, buttons have a hierarchy."""
import re
from pathlib import Path

HTML = (Path(__file__).resolve().parents[1] / "index.html").read_text()
CSS = HTML[HTML.index("<style>"):HTML.index("</style>")]
ROOT = CSS[CSS.index(":root"):CSS.index("color-scheme: dark;")]


def test_tokens_are_defined():
    for t in ("--space-1", "--space-8", "--radius-sm", "--radius-pill", "--fs-xs", "--motion-base", "--z-sheet",
              "--z-toast", "--focus-ring", "--focus-offset", "--danger", "--danger-strong"):
        assert t + ":" in ROOT, t


def test_no_duplicate_literal_focus_rings_or_layer_numbers_remain():
    body = CSS[CSS.index("color-scheme: dark;"):]
    assert "outline: 2px solid var(--accent-strong); outline-offset: 2px;" not in body
    assert not re.search(r"z-index: *(20|40|45|46|48|49|50|200|999)\b", body)
    assert "#e5676b" not in body and "#ff8589" not in body


def test_z_layers_keep_their_relative_order():
    vals = dict(re.findall(r"--z-([a-z-]+): *(\d+);", ROOT))
    order = ["header", "nav", "menu", "screen", "screen-top", "backdrop", "sheet", "splash", "overlay", "toast"]
    nums = [int(vals[k]) for k in order]
    assert nums == sorted(nums) and len(set(nums)) == len(nums)


def test_type_floor_is_12px():
    m = re.search(r"--fs-xs: *([\d.]+)rem", ROOT)
    assert float(m.group(1)) * 16 >= 12


def test_button_hierarchy_is_defined():
    for cls in (".primary-btn", ".secondary-btn", ".link-btn", ".danger-btn", ".is-loading"):
        assert cls in CSS, cls
