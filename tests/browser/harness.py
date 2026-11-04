"""Shared mocked-backend harness for the browser tests (no real network)."""
import json
import os
from pathlib import Path

import pytest

if os.environ.get("REQUIRE_BROWSER") == "1":
    import playwright.sync_api as pw
else:
    pw = pytest.importorskip("playwright.sync_api")

INDEX = (Path(os.environ["LOOM_INDEX_HTML"]).resolve() if os.environ.get("LOOM_INDEX_HTML") else Path(__file__).resolve().parents[2] / "index.html").as_uri()
SEP = "\u001e"
FAMILIES = ["happy", "trust", "fear", "surprise", "sad", "disgust", "angry", "anticipation"]


def make(browser, width=390, height=844, delay_ms=0, reduced=False, timeout_ms=0, dreams=None, recover_ms=120, dreams_script=None):
    ctx = browser.new_context(viewport={"width": width, "height": height}, has_touch=True, is_mobile=True,
                              reduced_motion="reduce" if reduced else "no-preference")
    page = ctx.new_page()
    st = {"dreams_script": list(dreams_script or []), "n": 100, "dreams": list(dreams or []), "bodies": [], "fail": False, "abort": False, "hang_ms": 0, "errors": [], "by_rid": {}, "inflight": set(), "lose_response": 0, "replays": 0, "in_progress_hits": 0, "fail_once": 0}
    page.on("pageerror", lambda e: st["errors"].append(str(e)))

    def handler(route):
        r, u = route.request, route.request.url
        if u.endswith("/interpret") and r.method == "POST":
            body = json.loads(r.post_data)
            st["bodies"].append(body)
            rid = body.get("request_id")
            # The mock backend behaves like the real one: one dream per
            # request_id, replay of a finished submission, 409 while busy.
            if rid and rid in st["by_rid"]:
                st["replays"] += 1
                meta = st["by_rid"][rid]
                return route.fulfill(status=200, content_type="text/plain", body=meta["interpretation"] + SEP + json.dumps(dict(meta, replayed=True)))
            if rid and rid in st["inflight"]:
                st["in_progress_hits"] += 1
                return route.fulfill(status=409, content_type="application/json", body=json.dumps({"detail": "busy", "code": "in_progress"}))
            if st["abort"]:
                return route.abort("failed")
            if st["fail_once"]:
                st["fail_once"] -= 1
                return route.fulfill(status=200, content_type="text/plain", body="partial" + SEP + json.dumps({"error": "provider down"}))
            if rid:
                st["inflight"].add(rid)
            if st["hang_ms"]:
                try:
                    page.wait_for_timeout(st["hang_ms"])
                except Exception:      # page closed while the request was still "hanging"
                    return
            if st["fail"]:
                st["inflight"].discard(rid)
                return route.fulfill(status=500, content_type="application/json", body=json.dumps({"detail": "boom"}))
            st["n"] += 1
            meta = {"id": st["n"], "symbols": ["a key"], "emotions": ["curious"], "people": [], "settings": [], "themes": [],
                    "interpretation": "A reading of your dream.", "symbol_icons": {"a key": "key"},
                    "emotions_reported": body.get("emotions_reported", []), "emotions_plutchik": ["Anticipation"], "similar": []}
            st["dreams"].append({"id": st["n"], "timestamp": "2025-11-01T08:00:00Z", "raw_text": body["raw_text"],
                                 "interpretation": meta["interpretation"], "symbols": ["a key"], "emotions": ["curious"],
                                 "emotions_plutchik": ["Anticipation"], "people": [], "settings": [], "themes": [],
                                 "symbol_icons": {"a key": "key"}, "emotions_reported": meta["emotions_reported"], "conversation": []})
            if rid:
                st["by_rid"][rid] = meta
                st["inflight"].discard(rid)
            if st["lose_response"]:
                st["lose_response"] -= 1       # dream IS saved, but the client never hears back
                try:
                    return route.abort("connectionreset")
                except Exception:
                    return
            return route.fulfill(status=200, content_type="text/plain", body="A reading." + SEP + json.dumps(meta))
        if "/entity-confirmations" in u:
            from urllib.parse import urlparse, parse_qs
            if r.method == "PUT":
                body = json.loads(r.post_data)
                st.setdefault("confirm_puts", []).append(body)
                for d in st["dreams"]:
                    if d["id"] == body["dream_id"]:
                        d.setdefault("confirmed_people", [])
                        if body["label"] not in d["confirmed_people"]:
                            d["confirmed_people"].append(body["label"])
                        if body["label"] not in d["people"]:
                            d["people"].append(body["label"])
                return route.fulfill(status=200, content_type="application/json", body='{"ok": true}')
            if r.method == "DELETE":
                q = parse_qs(urlparse(u).query)
                for d in st["dreams"]:
                    if str(d["id"]) == q["dream_id"][0]:
                        lab = q["label"][0]
                        d["confirmed_people"] = [x for x in d.get("confirmed_people", []) if x != lab]
                        d["people"] = [x for x in d["people"] if x != lab]
                return route.fulfill(status=200, content_type="application/json", body='{"ok": true}')
            return route.fulfill(status=200, content_type="application/json", body="[]")
        if u.endswith("/symbols/insight/stream") or u.endswith("/symbols/insight"):
            st.setdefault("insight_calls", []).append(u.rsplit("/symbols/", 1)[1])
            beh = st["insight_script"].pop(0) if st.get("insight_script") else "ok"
            streaming = u.endswith("/stream")
            if beh == "hang":
                return                                   # never answered
            if beh == "http500":
                return route.fulfill(status=500, content_type="application/json", body=json.dumps({"detail": "boom"}))
            if beh == "meta_error" and streaming:
                return route.fulfill(status=200, content_type="text/plain", body="\x1dTEASER\x1d\npart" + SEP + json.dumps({"error": "SymbolInsightStreamMalformed: raw provider detail"}))
            res = {"teaser": "t", "meaning": "General reading text.", "general": "General reading text.", "journal": "Journal reading text.", "direction": "What does it stir?"}
            if not streaming:
                return route.fulfill(status=200, content_type="application/json", body=json.dumps(res))
            S = "\x1d"
            body = (S + "TEASER" + S + "\nt\n" + S + "GENERAL" + S + "\n" + res["general"] + "\n" + S + "JOURNAL" + S + "\n" + res["journal"] + "\n" +
                    S + "DIRECTION" + S + "\n" + res["direction"] + "\n" + S + "END" + S + SEP + json.dumps(dict(res, cached=False)))
            return route.fulfill(status=200, content_type="text/plain", body=body)
        if u.endswith("/health"):
            return route.fulfill(status=200, content_type="application/json",
                                 body=json.dumps({"ok": True, "features": [] if st.get("old_backend") else ["idempotent_interpret"]}))
        if u.endswith("/similar") and r.method == "GET":
            import re as _re
            did = int(_re.search(r"/dreams/(\d+)/similar", u).group(1))
            return route.fulfill(status=200, content_type="application/json", body=json.dumps(st.get("similar", {}).get(did, [])))
        if "/dreams" in u and r.method == "GET" and "/dreams/" not in u:
            beh = st["dreams_script"].pop(0) if st.get("dreams_script") else "ok"
            st.setdefault("dreams_calls", []).append(beh)
            if beh == "500":
                return route.fulfill(status=500, content_type="application/json", body='{"detail":"boom"}')
            if beh == "abort":
                return route.abort("failed")
            if beh == "401":
                return route.fulfill(status=401, content_type="application/json", body='{"detail":"nope"}')
            return route.fulfill(status=200, content_type="application/json", body=json.dumps(st["dreams"]))
        route.fulfill(status=200, content_type="application/json", body="[]" if "/personal-meanings" in u else "{}")

    page.route("**://loom-phas.onrender.com/**", handler)
    page.add_init_script("window.__of=window.fetch;window.fetch=function(u,o){if(String(u).indexOf('/interpret')>-1&&%d){return new Promise(function(r){setTimeout(r,%d)}).then(function(){return window.__of(u,o)})}return window.__of(u,o)};" % (delay_ms, delay_ms))
    page.add_init_script("window.__LOOM_RECOVER_DELAY_MS=%d;" % recover_ms)
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
