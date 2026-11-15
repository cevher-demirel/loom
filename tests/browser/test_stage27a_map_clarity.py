"""Stage 27a -- Map label readability, empty-Map chrome, view descriptions, single load-error message."""
import pytest

from tests.browser.harness import make, map_view
from tests.browser import seed
from tests.browser.test_stage24c_relationships import dataset

pytestmark = pytest.mark.browser
WIDTHS = [(320, 568), (375, 667), (390, 844), (430, 932), (768, 1024), (1280, 800), (844, 390)]


def data():
    ds = dataset() + seed.dreams(18)
    for i, d in enumerate(ds):
        d["id"] = i + 1
    return ds


def _map(browser, w, h, ds=None):
    ctx, page, st = make(browser, width=w, height=h, dreams=data() if ds is None else ds)
    page.evaluate("document.querySelector('.bottom-tab-btn[data-tab=symbols], .side-nav-btn[data-tab=symbols]').click()")
    page.evaluate("document.fonts && document.fonts.ready")
    page.wait_for_timeout(700)
    return ctx, page, st


LABELS = """(function(){return [].slice.call(document.querySelectorAll('.loom-graph-node--symbol')).map(function(b){
  var l=b.querySelector('.loom-graph-node-label'), r=l.getBoundingClientRect(), off=b.classList.contains('loom-graph-node--label-off');
  return {off:off, h:r.height, lines:Math.round(r.height/(parseFloat(getComputedStyle(l).fontSize)*1.15*(r.height/l.offsetHeight||1))) , fs:parseFloat(getComputedStyle(l).fontSize)*(r.height/(l.offsetHeight||1)), l:r.left,t:r.top,rr:r.right,bb:r.bottom, name:b.getAttribute('aria-label')}})})()"""


@pytest.mark.parametrize("w,h", WIDTHS)
def test_visible_labels_are_readable_and_do_not_overlap(browser, w, h):
    ctx, page, st = _map(browser, w, h)
    labs = page.evaluate(LABELS)
    shown = [x for x in labs if not x["off"]]
    assert len(labs) >= 8 and len(shown) >= 4                       # still discoverable: most names visible at rest
    for x in shown:
        assert x["fs"] >= 10.9, x                                   # effective on-screen font size
    for i, a in enumerate(shown):                                   # no two visible labels collide
        for b in shown[i + 1:]:
            assert not (a["l"] < b["rr"] and a["rr"] > b["l"] and a["t"] < b["bb"] and a["bb"] > b["t"]), (a["name"], b["name"])
    assert st["errors"] == []
    ctx.close()


def test_every_name_is_shown_inside_its_node_even_at_320px(browser):
    # Immersive Map: labels live inside their own (never-overlapping) circles,
    # so no name is hidden for overlap any more -- not even at 320px.
    ctx, page, st = _map(browser, 320, 568)
    labs = page.evaluate(LABELS)
    assert len(labs) == 12 and not [x for x in labs if x["off"]]
    assert page.locator("#loom-graph-hidden-labels-note").is_hidden()
    assert all(x["name"] for x in labs)                             # every node keeps its accessible name
    inside = page.evaluate("""[...document.querySelectorAll('.loom-graph-node--symbol')].every(b => {
      var c=b.querySelector('.loom-graph-node-circle').getBoundingClientRect(), l=b.querySelector('.loom-graph-node-label').getBoundingClientRect();
      return l.left>=c.left-1 && l.right<=c.right+1 && l.top>=c.top-1 && l.bottom<=c.bottom+1; })""")
    assert inside
    ctx.close()


def test_selecting_a_node_always_shows_its_name_and_zooming_in_reveals_more(browser):
    ctx, page, st = _map(browser, 320, 568)
    before = [x for x in page.evaluate(LABELS) if not x["off"]]
    btn = page.locator(".loom-graph-node--symbol[aria-label^='People: Brother']")
    btn.click(); page.wait_for_timeout(500)
    sel = page.locator(".loom-graph-node--selected")
    assert sel.count() == 1 and "loom-graph-node--label-off" not in (sel.first.get_attribute("class") or "")
    page.keyboard.press("Escape"); page.wait_for_timeout(300)
    page.mouse.move(160, 300)
    for _ in range(4):
        page.mouse.wheel(0, -150); page.wait_for_timeout(120)       # zoom in (the +/- buttons are gone)
    after = [x for x in page.evaluate(LABELS) if not x["off"]]
    assert len(after) >= len(before)
    ctx.close()


@pytest.mark.parametrize("w,h", [(320, 568), (390, 844), (1280, 800)])
def test_empty_map_has_no_zoom_controls_or_legend(browser, w, h):
    ctx, page, st = _map(browser, w, h, ds=[])
    assert page.locator("#loom-graph-empty-note").is_visible()
    assert page.locator("#loom-graph-empty-record-btn").is_visible()   # the empty state still has its action
    assert page.locator("#loom-network-view .loom-graph-controls").is_hidden()
    assert page.locator("#loom-network-view .loom-graph-legend:not(.loom-graph-dropped-note)").is_hidden()
    ctx.close()


def test_immersive_map_has_no_chrome_and_you_opens_options(browser):
    # Approved redesign: no header, filter icon, view tabs, explanation,
    # zoom/Fit buttons or legend on the Map -- "You" reaches Filters /
    # Timeline / List / Re-center instead.
    ctx, page, st = _map(browser, 390, 844)
    for sel in ["#app-header", ".loom-map-head", "#loom-map-filter-btn", ".loom-view-toggle", "#loom-view-desc",
                "#loom-network-view .loom-graph-controls", "#loom-graph-legend-distance", "#loom-graph-dropped-note"]:
        assert page.locator(sel).first.is_hidden(), sel
    page.click("#loom-graph-you-btn")
    assert page.locator("#loom-options-sheet").is_visible()
    for b in ["filter", "timeline", "list", "recenter"]:
        assert page.locator("#loom-options-%s-btn" % b).is_visible()
    ctx.close()


def test_each_view_has_its_own_description_and_all_three_work(browser):
    ctx, page, st = _map(browser, 390, 844)
    desc = page.locator("#loom-view-desc")
    assert desc.is_hidden()                                         # immersive network: no explanation text
    assert page.locator("#loom-graph-wrap").is_visible()
    map_view(page, "timeline")
    assert "follow it through your dreams" in desc.inner_text()
    assert page.locator("#loom-timeline-picker-list .loom-timeline-pick-item").count() > 0
    page.locator("#loom-timeline-picker-list .loom-timeline-pick-item").first.click(); page.wait_for_timeout(300)
    assert page.locator("#loom-timeline-detail").is_visible()
    page.click("#loom-view-list-btn"); page.wait_for_timeout(300)
    assert "most frequent first" in desc.inner_text()
    assert page.locator("#loom-list-view .symbol-lib-item").count() > 0
    page.click("#loom-view-network-btn"); page.wait_for_timeout(300)
    assert desc.is_hidden() and page.locator("#loom-graph-you-btn").is_visible()
    ctx.close()


def test_load_error_shows_one_message_with_retry_inside_it(browser):
    ctx, page, st = make(browser, width=390, height=844, dreams=data(), dreams_script=["500"])
    page.wait_for_selector("#dreams-load-banner:not([hidden])", timeout=6000)
    page.evaluate("document.querySelector('.bottom-tab-btn[data-tab=archive]').click()"); page.wait_for_timeout(400)
    body = page.locator("body").inner_text()
    assert "Retry above" not in body
    assert page.locator("#dreams-load-banner").is_hidden()                      # the card carries the message
    assert page.locator("#capability-notice").is_hidden()                       # no second, generic toast
    assert body.count("couldn't be loaded") == 1
    btn = page.locator("#dreams-load-card-retry-btn")
    assert btn.bounding_box()["height"] >= 43
    btn.click()
    page.wait_for_function("document.querySelectorAll('#archive-list .archive-item').length > 0", timeout=8000)
    assert page.locator("#archive-list .archive-item").count() == len(data())
    assert st["dreams_calls"] == ["500", "ok"]
    ctx.close()


def test_banner_still_covers_other_tabs_when_the_load_failed(browser):
    ctx, page, st = make(browser, width=390, height=844, dreams=data(), dreams_script=["500"])
    page.wait_for_selector("#dreams-load-banner:not([hidden])", timeout=6000)
    assert page.locator("#dreams-load-banner").is_visible()                    # on Home
    ctx.close()
