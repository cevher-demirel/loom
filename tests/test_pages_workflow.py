"""The GitHub Pages workflow is manual-only, secret-free, and publishes the built site only."""
from pathlib import Path
import subprocess, sys, tempfile

ROOT = Path(__file__).resolve().parents[1]
WF = (ROOT / ".github/workflows/pages-deploy.yml").read_text()


def test_workflow_is_manual_only_and_main_only():
    assert "workflow_dispatch:" in WF
    for trigger in ("push:", "pull_request", "schedule:"):
        assert trigger not in WF
    assert "github.ref == 'refs/heads/main'" in WF


def test_workflow_uses_no_secrets_and_publishes_dist_only():
    assert "secrets." not in WF
    assert "path: dist" in WF and "scripts/build_frontend.py" in WF


def test_built_site_contains_page_and_both_login_backgrounds_only():
    with tempfile.TemporaryDirectory() as d:
        subprocess.run([sys.executable, str(ROOT / "scripts/build_frontend.py"), "--out", d + "/dist"], check=True, capture_output=True)
        files = sorted(str(p.relative_to(d + "/dist")) for p in Path(d, "dist").rglob("*") if p.is_file())
    assert "index.html" in files and "assets/login/login-desktop.webp" in files and "assets/login/login-mobile.webp" in files
    assert not any(f.endswith((".py", ".md")) or f.startswith(("tests", "docs")) for f in files), files
