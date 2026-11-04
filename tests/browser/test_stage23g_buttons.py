"""Stage 23g -- computed button hierarchy and loading state behave."""
import re

import pytest

from tests.browser.harness import make

pytestmark = pytest.mark.browser

JS = """() => {
  const mk = (cls, extra) => { const b = document.createElement('button'); b.className = cls; b.textContent = 'Label'; if (extra) b.disabled = true; document.body.appendChild(b); return b; };
  const read = b => { const s = getComputedStyle(b); return {h: b.getBoundingClientRect().height, bg: s.backgroundImage + s.backgroundColor, color: s.color, border: s.borderTopColor, op: s.opacity}; };
  const out = {};
  out.primary = read(mk('primary-btn')); out.secondary = read(mk('secondary-btn')); out.danger = read(mk('danger-btn'));
  out.disabled = read(mk('primary-btn', true));
  const l = mk('primary-btn is-loading'); out.loading = {color: getComputedStyle(l).color, pe: getComputedStyle(l).pointerEvents, after: getComputedStyle(l, '::after').content};
  return out; }"""


def test_buttons_follow_the_hierarchy(browser):
    ctx, page, st = make(browser, width=390, height=844)
    page.wait_for_function("document.getElementById('app-splash').hidden === true", timeout=8000)
    r = page.evaluate(JS)
    assert r["danger"]["h"] >= 44 and r["primary"]["h"] >= 40 and r["secondary"]["h"] >= 34   # layout heights; tap area is widened invisibly
    assert "gradient" in r["primary"]["bg"]
    assert "gradient" not in r["secondary"]["bg"]
    nums = [int(v) for v in re.findall(r"\d+", r["danger"]["border"])[:3]]
    assert nums[0] > 180 and nums[1] < 140                      # red outline
    assert float(r["disabled"]["op"]) < 0.7
    assert r["loading"]["pe"] == "none" and "rgba(0, 0, 0, 0)" in r["loading"]["color"] or r["loading"]["color"].endswith(", 0)")
    ctx.close()
