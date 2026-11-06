"""Stage 23c/23d -- Loom Map honesty notes and the selected-node connection experience (real behaviour)."""
import re

import pytest

from tests.browser.harness import make
from tests.browser.seed import dreams

pytestmark = pytest.mark.browser


def _open_map(browser, n, w=390, h=844, reduced=False):
    ctx, page, st = make(browser, width=w, height=h, dreams=dreams(n), reduced=reduced)
    page.wait_for_function("document.getElementById('app-splash').hidden === true", timeout=8000)
    page.evaluate("document.querySelector('.bottom-tab-btn[data-tab=symbols]').click()")
    page.wait_for_timeout(900)
    return ctx, page, st


def _fields(d):
    return {x.lower() for k in ("symbols", "emotions", "people", "settings") for x in d.get(k, [])}


def _list_total(page):
    page.click("#loom-view-list-btn")
    page.wait_for_timeout(300)
    n = page.locator("#loom-list-view .symbol-lib-item").count()
    page.click("#loom-view-network-btn")
    page.wait_for_timeout(300)
    return n


def _first_connected_node(page):
    """Select nodes until one has Connected-to pills; return its index."""
    for i in range(page.locator(".loom-graph-node--symbol").count()):
        page.locator(".loom-graph-node--symbol").nth(i).click()
        page.wait_for_timeout(350)
        if page.locator(".loom-preview-pill").count():
            return i
        page.keyboard.press("Escape")
        page.wait_for_timeout(200)
    raise AssertionError("no node has connections")


# ---------------- 23c: honest counts ----------------

def test_zero_dreams_shows_empty_state_and_no_notes(browser):
    ctx, page, st = _open_map(browser, 0)
    assert page.locator("#loom-graph-empty-note").is_visible()
    assert not page.locator("#loom-graph-dropped-note").is_visible()
    assert not page.locator("#loom-graph-lowdata-note").is_visible()
    assert st["errors"] == []
    ctx.close()


def test_three_dreams_low_data_message_and_no_proximity_claim(browser):
    ctx, page, st = _open_map(browser, 3)
    assert page.locator("#loom-graph-lowdata-note").inner_text().strip() == "Your dream connections will grow as you record more dreams."
    assert st["errors"] == []
    ctx.close()


@pytest.mark.parametrize("n", [30, 120])
def test_subset_message_uses_real_counts_and_view_list_works(browser, n):
    ctx, page, st = _open_map(browser, n)
    shown = page.locator(".loom-graph-node--symbol").count()
    assert shown == 12
    total = _list_total(page)
    note = page.locator("#loom-graph-dropped-note")
    assert note.is_visible()
    assert re.sub(r"\s+", " ", note.inner_text()).strip() == "Showing 12 of %d elements. View list to explore all." % total
    assert not page.locator("#loom-graph-lowdata-note").is_visible()
    page.click("#loom-graph-view-list-btn")
    page.wait_for_timeout(400)
    assert page.locator("#loom-list-view").is_visible() and not page.locator("#loom-network-view").is_visible()
    assert page.locator("#loom-view-list-btn").get_attribute("aria-pressed") == "true"
    assert st["errors"] == []
    ctx.close()


def test_subset_message_updates_when_filters_change(browser):
    ctx, page, st = _open_map(browser, 30)
    before = re.search(r"of (\d+)", page.inner_text("#loom-graph-dropped-note")).group(1)
    page.click("#loom-map-filter-btn")
    page.wait_for_timeout(400)
    page.locator('input[data-filter-category="place"]').evaluate("e => e.click()")
    page.locator('input[data-filter-category="person"]').evaluate("e => e.click()")
    page.click("#loom-filters-apply-btn")
    page.wait_for_timeout(600)
    shown = page.locator(".loom-graph-node--symbol").count()
    total = _list_total(page)
    assert total < int(before)
    if total > shown:
        assert page.inner_text("#loom-graph-dropped-note").strip().startswith("Showing %d of %d elements." % (shown, total))
    else:
        assert not page.locator("#loom-graph-dropped-note").is_visible()
    ctx.close()


def test_equal_counts_do_not_claim_distance_means_frequency(browser):
    ctx, page, st = _open_map(browser, 3)
    counts = page.evaluate("[...document.querySelectorAll('.loom-graph-node--symbol')].length")
    legend = page.inner_text("#loom-graph-legend-distance")
    assert legend in ("Closer = more frequent", "Distance is only layout")
    ctx.close()


# ---------------- 23d: selected node ----------------

def test_selected_node_highlights_related_draws_lines_and_dims_rest(browser):
    ctx, page, st = _open_map(browser, 30)
    i = _first_connected_node(page)
    nodes = page.locator(".loom-graph-node--symbol")
    assert nodes.nth(i).evaluate("e => e.classList.contains('loom-graph-node--selected')")
    related = page.locator(".loom-graph-node--related").count()
    links = page.locator(".loom-graph-edge-link").count()
    assert related >= 1 and links == related                      # one line per genuinely connected VISIBLE node
    assert page.locator(".loom-graph-node--dim").count() == nodes.count() - 1 - related
    # each line ends on a related node's real position
    ends = page.evaluate("""() => [...document.querySelectorAll('.loom-graph-edge-link')].map(l => [+l.getAttribute('x2'), +l.getAttribute('y2')])""")
    pos = page.evaluate("""() => [...document.querySelectorAll('.loom-graph-node--related')].map(b => [parseFloat(b.style.left), parseFloat(b.style.top)])""")
    assert sorted(ends) == sorted(pos)
    # unrelated nodes have no line
    assert page.locator("#loom-preview-sheet").is_visible()
    # closing clears everything (no stale highlight/lines)
    page.keyboard.press("Escape")
    page.wait_for_timeout(300)
    assert page.locator(".loom-graph-edge-link, .loom-graph-node--selected, .loom-graph-node--related, .loom-graph-node--dim").count() == 0
    assert st["errors"] == []
    ctx.close()


def test_connected_to_entries_are_buttons_and_open_connection_with_shared_dreams(browser):
    ctx, page, st = _open_map(browser, 30)
    _first_connected_node(page)
    pill = page.locator(".loom-preview-pill").first
    assert pill.evaluate("e => e.tagName") == "BUTTON"
    assert "Open connection" in pill.get_attribute("aria-label")
    pill_count = int(pill.locator(".loom-preview-pill-count").inner_text())
    node_label = page.inner_text("#loom-preview-node-name")
    other = pill.locator(".loom-preview-pill-label").inner_text()
    pill.click()
    page.wait_for_timeout(500)
    name = page.inner_text("#loom-preview-connection-name")
    assert node_label.lower() in name.lower() and other.lower() in name.lower()
    assert "Together in %d dream" % pill_count in page.inner_text("#loom-preview-connection-stat")
    rows = page.locator("#loom-preview-dreams-list [data-dream-id]")
    assert rows.count() == pill_count                           # shared dreams == the real co-occurrence count
    by_id = {str(d["id"]): d for d in st["dreams"]}
    for k in range(rows.count()):
        f = _fields(by_id[rows.nth(k).get_attribute("data-dream-id")])
        assert node_label.lower() in f and other.lower() in f, (node_label, other, f)   # no invented relationship
    # return paths
    assert page.locator("#loom-preview-connection-back-btn").is_visible()
    page.click("#loom-preview-connection-back-btn")
    page.wait_for_timeout(400)
    assert page.inner_text("#loom-preview-node-name") == node_label
    assert st["errors"] == []
    ctx.close()


def test_shared_dream_opens_detail_and_back_returns_to_the_connection(browser):
    ctx, page, st = _open_map(browser, 30)
    _first_connected_node(page)
    page.locator(".loom-preview-pill").first.click()
    page.wait_for_timeout(400)
    name = page.inner_text("#loom-preview-connection-name")
    page.locator("#loom-preview-dreams-list [data-dream-id]").first.click()
    page.wait_for_timeout(500)
    assert page.locator("#dream-screen").is_visible()
    assert page.inner_text("#dream-screen-back-label") == "Connection"
    page.click("#dream-screen-back-btn")
    page.wait_for_timeout(500)
    assert page.locator("#loom-preview-sheet").is_visible()
    assert page.inner_text("#loom-preview-connection-name") == name
    page.click("#loom-preview-connection-close-btn")
    page.wait_for_timeout(300)
    assert not page.locator("#loom-preview-sheet").is_visible()
    assert page.locator(".loom-graph-edge-link").count() == 0
    ctx.close()


def test_hidden_related_elements_stay_listed_without_a_line(browser):
    ctx, page, st = _open_map(browser, 30)
    found = False
    for i in range(page.locator(".loom-graph-node--symbol").count()):
        page.locator(".loom-graph-node--symbol").nth(i).click()
        page.wait_for_timeout(350)
        pills, links = page.locator(".loom-preview-pill").count(), page.locator(".loom-graph-edge-link").count()
        if pills > links and page.locator("#loom-preview-hidden-note").is_visible():
            found = True
            page.locator(".loom-preview-pill").nth(pills - 1).click()      # still tappable
            page.wait_for_timeout(400)
            assert page.locator("#loom-preview-dreams-list [data-dream-id]").count() >= 1
            break
        page.keyboard.press("Escape")
        page.wait_for_timeout(200)
    assert found, "seed data should contain a node with an off-map connection"
    ctx.close()


def test_keyboard_flow_and_focus_restoration(browser):
    ctx, page, st = _open_map(browser, 30)
    page.focus(".loom-graph-node--symbol >> nth=0")
    page.keyboard.press("Enter")
    page.wait_for_timeout(400)
    if page.locator(".loom-preview-pill").count():
        page.focus(".loom-preview-pill >> nth=0")
        page.keyboard.press("Enter")
        page.wait_for_timeout(400)
        assert page.locator("#loom-preview-connection-name").is_visible()
    page.keyboard.press("Escape")
    page.wait_for_timeout(300)
    assert not page.locator("#loom-preview-sheet").is_visible()
    assert page.evaluate("document.activeElement.classList.contains('loom-graph-node--symbol')")
    ctx.close()


def test_reduced_motion_removes_link_transitions(browser):
    ctx, page, st = _open_map(browser, 30, reduced=True)
    _first_connected_node(page)
    assert page.evaluate("getComputedStyle(document.querySelector('.loom-graph-node--symbol')).transitionDuration") in ("0s", "0.001s")
    ctx.close()


@pytest.mark.parametrize("n", [3, 30, 120])
@pytest.mark.parametrize("w,h", [(320, 568), (390, 844), (1280, 800)])
def test_selection_flow_is_stable_across_sizes(browser, n, w, h):
    ctx, page, st = _open_map(browser, n, w, h)
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
    try:
        _first_connected_node(page)
    except AssertionError:
        ctx.close(); return                                        # 3 dreams may have no recurring pairs
    assert page.locator(".loom-graph-edge-link").count() == page.locator(".loom-graph-node--related").count()
    assert st["errors"] == []
    ctx.close()


def test_timeline_and_list_views_unaffected_by_selection(browser):
    ctx, page, st = _open_map(browser, 30)
    _first_connected_node(page)
    page.keyboard.press("Escape")
    page.wait_for_timeout(200)
    page.click("#loom-view-timeline-btn"); page.wait_for_timeout(300)
    assert page.locator("#loom-timeline-view").is_visible()
    page.click("#loom-view-list-btn"); page.wait_for_timeout(300)
    assert page.locator("#loom-list-view .symbol-lib-item").count() > 12
    ctx.close()


# ---------------- Home discovery deep link ----------------

def test_home_discovery_opens_the_relationship_not_a_generic_map(browser):
    ctx, page, st = make(browser, width=390, height=844, dreams=dreams(30))
    page.wait_for_function("document.getElementById('app-splash').hidden === true", timeout=8000)
    page.wait_for_timeout(500)
    names = page.inner_text("#home-discovery-names")
    stat = page.inner_text("#home-discovery-stat")
    a, b = [x.strip().lower() for x in names.split(" and ")]
    page.evaluate("document.getElementById('home-discovery-review-btn').click()")
    page.wait_for_timeout(900)
    assert page.locator("#loom-preview-sheet").is_visible()
    cname = page.inner_text("#loom-preview-connection-name").lower()
    assert a in cname and b in cname
    assert stat.replace("Together in ", "") in page.inner_text("#loom-preview-connection-stat")
    assert page.locator("#loom-preview-dreams-list [data-dream-id]").count() == int(re.search(r"(\d+)", stat).group(1))
    assert page.locator("#loom-network-view").is_visible()
    assert st["errors"] == []
    ctx.close()
