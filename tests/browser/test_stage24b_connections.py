"""Stage 24b -- a real relationship must never be hidden by the Home card cap."""
import pytest

from tests.browser.harness import make

pytestmark = pytest.mark.browser


def D(i, **kw):
    d = {"id": i, "timestamp": "2026-09-%02dT10:00:00Z" % (i + 1), "raw_text": "dream %d" % i, "interpretation": "r",
         "symbols": [], "emotions": [], "emotions_plutchik": ["Trust"], "people": [], "settings": [], "themes": [],
         "symbol_icons": {}, "emotions_reported": [], "conversation": [], "location": ""}
    d.update(kw)
    return d


def dataset():
    out, n = [], 1
    # 9 strong pairs (3 shared dreams each) -- more than the 8-card Home cap
    for k in range(9):
        for _ in range(3):
            out.append(D(n, people=["Person%d" % k], settings=["Place%d" % k])); n += 1
    # the real but weaker relationship: Brother + Barber shop in exactly 2 dreams
    out.append(D(n, people=["my brother"], settings=["barbershop"])); n += 1
    out.append(D(n, people=["Brother"], settings=["Barber shop"])); n += 1
    # Brother is also frequent elsewhere, so the Brother node is on the map while Barber shop is not
    out.append(D(n, people=["Brother"], settings=["Elsewhere1"])); n += 1
    out.append(D(n, people=["Brother"], settings=["Elsewhere2"])); n += 1
    return out


def _open_map(browser, ds, w=390, h=844):
    ctx, page, st = make(browser, width=w, height=h, dreams=ds)
    page.wait_for_function("document.getElementById('app-splash').hidden === true", timeout=8000)
    page.evaluate("document.querySelector('.bottom-tab-btn[data-tab=symbols]').click()")
    page.wait_for_timeout(900)
    return ctx, page, st


def test_weak_pair_beyond_home_card_cap_is_still_listed_for_hidden_node(browser):
    ctx, page, st = _open_map(browser, dataset())
    node = page.locator('.loom-graph-node--symbol[data-cat-key="person:brother"]')
    assert node.count() == 1
    node.click()
    page.wait_for_timeout(400)
    pills = page.locator(".loom-preview-pill").all_inner_texts()
    assert any("Barber shop" in t for t in pills), pills
    # Barber shop is not drawn as a node, so there is no line, and the sheet says so instead of hiding it
    assert page.locator('.loom-graph-node--symbol[data-cat-key="place:barber shop"]').count() == 0
    assert page.locator("#loom-preview-hidden-note").is_visible()
    page.locator(".loom-preview-pill", has_text="Barber shop").first.click()
    page.wait_for_timeout(400)
    assert "Together in 2 dreams" in page.locator("#loom-preview-connection-stat").inner_text()
    assert "Exact match" in page.locator("#loom-preview-overview-text").inner_text()
    assert page.locator("#loom-preview-dreams-list [data-dream-id]").count() == 2
    assert st["errors"] == []
    ctx.close()


def test_father_with_two_shared_dreams_has_supported_connection(browser):
    ds = [D(1, people=["Dad"], emotions=["joyful"]), D(2, people=["my dad"], emotions=["joyful"])]
    ctx, page, st = _open_map(browser, ds)
    page.locator('.loom-graph-node--symbol[data-cat-key="person:father"]').click()
    page.wait_for_timeout(400)
    assert page.locator(".loom-preview-pill").count() >= 1
    assert "No supported connections yet" not in page.locator("#loom-preview-connected-grid").inner_text()
    ctx.close()
