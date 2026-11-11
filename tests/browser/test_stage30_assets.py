"""Stage 30 -- frontend packaging: the minimal build contains exactly the page and its
login artwork, and works at the site root and under a subpath (relative asset URLs)."""
import http.server
import subprocess
import sys
import threading
from pathlib import Path

import pytest

pytestmark = pytest.mark.browser
ROOT = Path(__file__).resolve().parents[2]


def _build(tmp_path):
    out = tmp_path / "dist"
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "build_frontend.py"), "--out", str(out)],
                       capture_output=True, text=True, timeout=60, cwd=str(ROOT))
    assert r.returncode == 0, r.stderr
    return out


def test_build_contains_only_the_page_and_its_assets(tmp_path):
    out = _build(tmp_path)
    files = sorted(str(p.relative_to(out)) for p in out.rglob("*") if p.is_file())
    assert files == ["assets/login/login-desktop.webp", "assets/login/login-mobile.webp", "index.html", "privacy.html", "terms.html"]
    assert not list(out.rglob("*.py")) and not (out / "docs").exists() and not (out / "tests").exists()


def _serve(directory):
    class H(http.server.SimpleHTTPRequestHandler):
        def __init__(s, *a, **k): super().__init__(*a, directory=str(directory), **k)
        def log_message(s, *a): pass
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, srv.server_address[1]


@pytest.mark.parametrize("prefix", ["", "loom/"])
@pytest.mark.parametrize("w,h", [(390, 844), (1280, 800)])
def test_login_artwork_loads_from_root_and_subpath(browser, tmp_path, prefix, w, h):
    out = _build(tmp_path)
    site = tmp_path / "site"
    (site / prefix).mkdir(parents=True, exist_ok=True) if prefix else site.mkdir()
    import shutil
    shutil.copytree(out, site / prefix, dirs_exist_ok=True)
    srv, port = _serve(site)
    ctx = browser.new_context(viewport={"width": w, "height": h})
    page = ctx.new_page()
    bad = []
    page.on("response", lambda r: bad.append((r.status, r.url)) if r.status >= 400 and "127.0.0.1" in r.url else None)
    page.route("**/auth/providers", lambda r: r.fulfill(status=200, content_type="application/json",
                                                         headers={"access-control-allow-origin": "*"}, body='{"google": false}'))
    page.route("https://**", lambda r: r.abort())            # no external network (fonts); local assets only
    page.goto(f"http://127.0.0.1:{port}/{prefix}")
    page.wait_for_function("document.getElementById('app-splash').hidden === true", timeout=10000)
    page.wait_for_timeout(600)
    name = "login-mobile.webp" if w < 900 else "login-desktop.webp"
    status = page.evaluate("fetch('assets/login/%s').then(r=>r.status)" % name)
    assert status == 200 and not [b for b in bad if "/assets/" in b[1]], bad
    assert page.evaluate("getComputedStyle(document.querySelector('.auth-panel')).backgroundImage || getComputedStyle(document.getElementById('auth-shell')).backgroundImage") != ""
    ctx.close(); srv.shutdown()
