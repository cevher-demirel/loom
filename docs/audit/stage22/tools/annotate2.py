import sys, os, io
sys.path.insert(0, os.path.dirname(__file__))
from capture import make, tab, settle, seed, sync_playwright, pick_child, to_explorer
from PIL import Image, ImageDraw, ImageFont
R = "/home/claude/cevher-demirel/loom/docs/audit/stage22/annotated/"
F = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 15); FS = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 13)
def wrap(t, n):
    out, cur = [], ""
    for w in t.split():
        if len(cur) + len(w) + 1 > n: out.append(cur); cur = w
        else: cur = (cur + " " + w).strip()
    return out + [cur]
def draw(pg, out, title, items, scale=1.6):
    boxes = []
    for sel, txt in items:
        b = pg.evaluate("(s)=>{const e=document.querySelector(s);if(!e)return null;const r=e.getBoundingClientRect();return [r.left,r.top,r.right,r.bottom]}", sel)
        boxes.append((b, txt))
    im = Image.open(io.BytesIO(pg.screenshot())).convert("RGB"); W, H = im.size
    im = im.resize((int(W * scale), int(H * scale))); d = ImageDraw.Draw(im); lines = []
    n = 0
    for b, txt in boxes:
        if not b: continue
        n += 1; x0, y0, x1, y1 = [int(v * scale) for v in b]
        d.rectangle([x0, y0, x1, y1], outline=(255, 90, 90), width=3); d.ellipse([x0 - 4, y0 - 4, x0 + 22, y0 + 22], fill=(255, 90, 90)); d.text((x0 + 4, y0), str(n), font=F, fill=(255, 255, 255))
        lines += wrap("%d. %s" % (n, txt), max(40, int(im.width / 8.2)))
    ph = 40 + 18 * len(lines); panel = Image.new("RGB", (im.width, ph), (22, 18, 40)); pd = ImageDraw.Draw(panel); pd.text((10, 8), title, font=F, fill=(255, 217, 122))
    for k, l in enumerate(lines): pd.text((10, 34 + 18 * k), l, font=FS, fill=(235, 230, 250))
    res = Image.new("RGB", (im.width, im.height + ph)); res.paste(im, (0, 0)); res.paste(panel, (0, im.height)); res.save(R + out)
with sync_playwright() as p:
    b = p.chromium.launch()
    def ctx(w, h, n=30): return make(b, w, h, dreams=seed.dreams(n))
    c, pg, st = ctx(390, 844); tab(pg, "symbols"); settle(pg, 1200)
    draw(pg, "A1_loom_map_network_390.png", "Loom Map / Network, 390x844, 30 seeded dreams", [
        ("#loom-graph-wrap", "The network draws only 'You' to element spokes. Element-to-element lines were removed by design, so no relationship between two nodes is visible. [P1]"),
        (".loom-graph-node-label", "Node labels measure 11.7px (10.6px at 320 wide) [P2]."),
        (".loom-view-toggle", "View toggle buttons are 28px tall, under the 44px guideline [P2]."),
        (".loom-graph-legend", "Legend explains 'You', 'Tap to open' and 'Closer = more frequent' but never says what a connection is.")])
    c.close()
    c, pg, st = ctx(390, 844); tab(pg, "archive"); settle(pg, 900)
    draw(pg, "A4_journal_390.png", "Journal / populated, 390x844", [
        ("#journal-record-btn", "Three entry points to 'new dream' on one screen: header +, this button, and Home [P2]."),
        ("#journal-head-add-btn", "Header + duplicates the button below (32px target)."),
        ("#archive-search-input", "Search placeholder is clipped: 'Search your dreams, symbols, peop' [P2]."),
        ("#archive-list > * .archive-swatch, #archive-list > *:first-child > *:first-child", "Colored square on each card has no label or legend [P2]."),
        ("#journal-filter-chips", "Filter chips scroll sideways; 'Symbols' is cut off and chips are 32px tall [P3].")])
    c.close()
    c, pg, st = ctx(390, 844); pg.evaluate("document.querySelector('.bottom-tab-btn[data-tab=archive]').click()"); settle(pg, 700); pg.locator("#archive-list > *").first.click(); settle(pg, 900)
    draw(pg, "A5_dream_detail_390.png", "Dream Detail from Journal, 390x844", [
        (".dream-screen-back", "Back label says 'Archive'; the tab, the title and the bottom nav all say 'Journal' [P2 naming]."),
        ("#dream-screen-moods", "Emotion flower for 1-2 emotions: sqrt-scaled petals, no sample-size context.")])
    c.close()
    c, pg, st = ctx(390, 844, 3); tab(pg, "patterns"); settle(pg, 1200)
    draw(pg, "A6_insights_low_data_390.png", "Insights / 3 dreams, 390x844", [
        ("#insights-landscape .emotion-wheel-wrap", "Three dreams produce '67% - 2 of 3' as the headline. Small samples are not flagged [P2]."),
        ("#insights-landscape", "Legend colors differ from the Emotion Wheel for the same family (Fear violet here, blue on the wheel; Sadness blue here, lavender on the wheel) [P2].")])
    c.close()
    c, pg, st = ctx(320, 568); to_explorer(pg, "A key."); pick_child(pg, "fear", 0, 0); pick_child(pg, "trust", 0, 0); pick_child(pg, "sad", 0, 0); pg.click("[data-feel-tray]"); settle(pg, 500)
    draw(pg, "A7_tray_expanded_320.png", "Emotion tray expanded / 320x568", [
        ("[data-feel-tray]", "Tray header wraps to two lines at 320px."),
        ("#feel-scroll", "Only ~2 group rows of choices remain visible above the tray; family title can slide under the header [P2]."),
        ("#feel-go-btn", "Dock stays pinned and legible.")], 1.8)
    c.close()
    c, pg, st = ctx(390, 844); tab(pg, "symbols"); settle(pg, 900); pg.click("#loom-view-timeline-btn"); settle(pg, 600); pg.locator("#loom-timeline-picker-list button").first.click(); settle(pg, 900)
    draw(pg, "A8_timeline_detail_390.png", "Loom Map / Timeline element detail, 390x844", [
        (".loom-view-toggle", "Two stacked 'Timeline' controls: Network/Timeline/List above, Timeline/Month/Patterns below [P2]."),
        ("#loom-timeline-list > *", "Dream excerpts are cut mid-word with no ellipsis ('the whole t') [P2].")])
    c.close()
    c, pg, st = ctx(390, 844, 5); pg.evaluate("document.querySelector('.header-gear-btn, .side-nav-btn--gear').click()"); settle(pg, 800)
    pg.evaluate("(()=>{const b=[...document.querySelectorAll('#panel-profile button, #panel-profile a')].find(x=>x.textContent.trim().startsWith('Account'));b.click()})()"); settle(pg, 900)
    draw(pg, "A9_settings_account_390.png", "Settings / Account, 390x844", [
        ("#settings-back-btn", "Header says 'Account' but the page is About You (profile) + email + data + delete; the page called 'Profile' holds only avatar and name [P2 naming]. Back target is 32px [P1/P2 touch]."),
        ("#export-dreams-btn", "Export is a full-width text-weight button; Delete is a text link further down [P2].")])
    c.close()
    c, pg, st = ctx(844, 390, 10); to_explorer(pg, "A key."); pick_child(pg, "fear", 0, 0); pick_child(pg, "trust", 0, 0); settle(pg, 500)
    draw(pg, "A2_wheel_landscape_844x390.png", "Emotion Wheel explorer / landscape 844x390", [
        ("#feel-scroll", "Scroll area is a single row tall; the wheel is not visible [P1, landscape]."),
        ("#feel-go-btn", "Dock + bottom nav consume most of the 390px height.")], 1.2)
    c.close()
    c, pg, st = make(b, 390, 420, dreams=seed.dreams(10)); pg.evaluate("document.getElementById('home-record-btn').click()"); settle(pg, 700); pg.fill("#dream-input", "Typing a dream with the keyboard open."); settle(pg, 500)
    draw(pg, "A3_record_keyboard_390x420.png", "Record a dream / keyboard-open emulation 390x420", [
        ("#dream-input", "Only the text box fits."),
        ("#interpret-btn", "'Continue' is below the fold (box present but off-screen); the person must scroll to proceed [P1]. Emulated by resizing the viewport; a real OS keyboard was not available.")])
    c.close(); b.close()
print(sorted(os.listdir(R)))
