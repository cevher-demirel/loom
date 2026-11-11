"""Terms and Privacy links on Sign In / Create Account and in Settings; the two pages themselves lay out
cleanly at phone, tablet and desktop widths. All network is stubbed."""
import pytest

from pathlib import Path

from tests.browser.harness import INDEX
from tests.browser.test_stage28_login import SIZES, _page

pytestmark = pytest.mark.browser
ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("w,h", SIZES)
def test_signin_and_signup_show_both_legal_links(browser, w, h):
    ctx, page, errs, _ = _page(browser, w, h)
    assert not page.evaluate("document.documentElement.scrollWidth > document.documentElement.clientWidth")
    for view_btn in (None, "#login-to-signup-btn"):
        if view_btn:
            page.click(view_btn)
            page.wait_for_timeout(300)
        links = page.locator(".auth-legal:visible a")
        assert links.count() == 2
        for i in range(2):
            b = links.nth(i).bounding_box()
            assert b and b["x"] >= 0 and b["x"] + b["width"] <= w + 1, b
            assert links.nth(i).get_attribute("target") == "_blank" and "noopener" in links.nth(i).get_attribute("rel")
        assert {links.nth(0).get_attribute("href"), links.nth(1).get_attribute("href")} == {"terms.html", "privacy.html"}
        fs = page.evaluate("parseFloat(getComputedStyle(document.querySelector('.auth-legal:not([hidden])')).fontSize)")
        assert fs >= 12
    assert not errs, errs
    ctx.close()


@pytest.mark.parametrize("w,h", [(320, 568), (390, 844), (768, 1024), (1280, 800)])
@pytest.mark.parametrize("name", ["privacy.html", "terms.html"])
def test_legal_page_layout(browser, w, h, name):
    ctx = browser.new_context(viewport={"width": w, "height": h}, is_mobile=w < 900, has_touch=w < 900)
    page = ctx.new_page()
    page.route("**/*", lambda r: r.continue_() if r.request.url.startswith("file:") else r.abort())
    page.goto("file://" + (ROOT / name).as_posix())
    page.wait_for_timeout(300)
    assert not page.evaluate("document.documentElement.scrollWidth > document.documentElement.clientWidth")
    assert page.locator("h1").count() == 1
    assert page.evaluate("[...document.querySelectorAll('p,li,td')].every(e=>parseFloat(getComputedStyle(e).fontSize)>=14)")
    back = page.locator("a.back").bounding_box()
    assert back and back["height"] >= 44
    ctx.close()
