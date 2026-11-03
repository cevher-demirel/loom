"""Shared mocked-backend harness for the browser tests (no real network)."""
import json
import os
from pathlib import Path

import pytest

if os.environ.get("REQUIRE_BROWSER") == "1":
    import playwright.sync_api as pw
else:
    pw = pytest.importorskip("playwright.sync_api")

INDEX = (Path(__file__).resolve().parents[2] / "index.html").as_uri()
SEP = "\u001e"
FAMILIES = ["happy", "trust", "fear", "surprise", "sad", "disgust", "angry", "anticipation"]


def make(browser, width=390, height=844, delay_ms=0, reduced=False, timeout_ms=0, dreams=None):
    ctx = browser.new_context(viewport={"width": width, "height": height}, has_touch=True, is_mobile=True,
                              reduced_motion="reduce" if reduced else "no-preference")
    page = ctx.new_page()
    st = {"n": 100, "dreams": list(dreams or []), "bodies": [], "fail": False, "abort": False, "hang_ms": 0, "errors": []}
    page.on("pageerror", lambda e: st["errors"].append(str(e)))

    def handler(route):
        r, u = route.request, route.request.url
        if u.endswith("/interpret") and r.method == "POST":
            body = json.loads(r.post_data)
            st["bodies"].append(body)
            if st["abort"]:
                return route.abort("failed")
            if st["hang_ms"]:
                try:
                    page.wait_for_timeout(st["hang_ms"])
                except Exception:      # page closed while the request was still "hanging"
                    return
            if st["fail"]:
                return route.fulfill(status=500, content_type="application/json", body=json.dumps({"detail": "boom"}))
            st["n"] += 1
            meta = {"id": st["n"], "symbols": ["a key"], "emotions": ["curious"], "people": [], "settings": [], "themes": [],
                    "interpretation": "A reading of your dream.", "symbol_icons": {"a key": "key"},
                    "emotions_reported": body.get("emotions_reported", []), "emotions_plutchik": ["Anticipation"], "similar": []}
            st["dreams"].append({"id": st["n"], "timestamp": "2025-11-01T08:00:00Z", "raw_text": body["raw_text"],
                                 "interpretation": meta["interpretation"], "symbols": ["a key"], "emotions": ["curious"],
                                 "emotions_plutchik": ["Anticipation"], "people": [], "settings": [], "themes": [],
                                 "symbol_icons": {"a key": "key"}, "emotions_reported": meta["emotions_reported"], "conversation": []})
            return route.fulfill(status=200, content_type="text/plain", body="A reading." + SEP + json.dumps(meta))
        if "/dreams" in u and r.method == "GET" and "/dreams/" not in u:
            return route.fulfill(status=200, content_type="application/json", body=json.dumps(st["dreams"]))
        route.fulfill(status=200, content_type="application/json", body="[]" if "/personal-meanings" in u else "{}")

    page.route("**://loom-phas.onrender.com/**", handler)
    page.add_init_script("window.__of=window.fetch;window.fetch=function(u,o){if(String(u).indexOf('/interpret')>-1&&%d){return new Promise(function(r){setTimeout(r,%d)}).then(function(){return window.__of(u,o)})}return window.__of(u,o)};" % (delay_ms, delay_ms))
    if timeout_ms:
        page.add_init_script("window.__LOOM_INTERPRET_TIMEOUT_MS=%d;" % timeout_ms)
    page.add_init_script("localStorage.setItem('loom_token','tok');localStorage.setItem('loom_username','Tester');")
    page.goto(INDEX)
    page.wait_for_selector("#app-shell:not([hidden])")
    page.wait_for_timeout(600)
    return ctx, page, st


def to_explorer(page, text="A key in a long hallway of doors."):
    page.evaluate("document.getElementById('home-record-btn').click()")
    page.fill("#dream-input", text)
    page.click("#interpret-btn")
    page.wait_for_selector(".feel-wheel")


def focus(page, fam):
    page.click('path[data-feel-family="%s"]' % fam, force=True)


def pick_child(page, fam, mid_idx=0, leaf_idx=0):
    """focus a family, expand one group, select one child chip"""
    focus(page, fam)
    mid = page.locator(".feel-mid").nth(mid_idx)
    if mid.locator(".feel-leaf").count() == 0:
        mid.locator("[data-feel-mid]").click()
    mid.locator(".feel-leaf").nth(leaf_idx).click()


def sel_count(page):
    """number of selected emotions, read from what the person sees (the action button / summary)"""
    return page.evaluate("""() => { const b = document.getElementById('feel-go-btn'); if (!b) return 0;
      const m = b.textContent.match(/\\((\\d+)\\)/); return m ? +m[1] : 0; }""")




def sel_count(page):
    """number of selected emotions, read from what the person sees (the action button / summary)"""
    return page.evaluate("""() => { const b = document.getElementById('feel-go-btn'); if (!b) return 0;
      const m = b.textContent.match(/\\((\\d+)\\)/); return m ? +m[1] : 0; }""")


def settle(page):
    """wait until every finite CSS transition/animation has finished (infinite glow loops are ignored) (deterministic, not a fixed sleep)"""
    page.evaluate("Promise.all(document.getAnimations().filter(a => a.effect.getComputedTiming().iterations !== Infinity).map(a => a.finished.catch(() => null)))")
