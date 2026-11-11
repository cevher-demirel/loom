"""Privacy Policy and Terms of Service: present, linked from sign-in and Settings, published by the
static build, and consistent with what the code actually does."""
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / "index.html").read_text(encoding="utf-8")
PRIVACY = (ROOT / "privacy.html").read_text(encoding="utf-8")
TERMS = (ROOT / "terms.html").read_text(encoding="utf-8")


def test_pages_exist_and_are_complete_documents():
    for page, h1 in ((PRIVACY, "Privacy Policy"), (TERMS, "Terms of Service")):
        assert page.startswith("<!DOCTYPE html>") and '<html lang="en">' in page
        assert 'name="viewport"' in page and f"<h1>{h1}</h1>" in page
        assert "Last updated" in page and 'href="./"' in page


def test_pages_have_no_placeholders_or_scripts():
    for page in (PRIVACY, TERMS):
        assert not re.search(r"\b(TODO|TBD|FIXME|lorem|\[\[|OWNER)\b", page, re.I)
        assert "<script" not in page.lower()


def test_privacy_policy_names_every_service_the_code_uses():
    for name in ("Anthropic", "Voyage AI", "Pinecone", "Turso", "Render", "GitHub Pages", "Resend", "Google Fonts", "Google"):
        assert name in PRIVACY, name
    # services named must really be in the codebase
    code = " ".join((ROOT / f).read_text(encoding="utf-8") for f in ("engine.py", "vectorstore.py", "emailer.py", "database.py"))
    for needle in ("anthropic", "voyageai", "pinecone", "resend", "libsql"):
        assert needle in code.lower(), needle


def test_pages_use_only_the_contact_address_already_in_the_app():
    app_mail = set(re.findall(r"mailto:([^\"']+)", INDEX))
    for page in (PRIVACY, TERMS):
        assert set(re.findall(r"mailto:([^\"']+)", page)) <= app_mail


def test_signin_signup_and_settings_link_to_both_pages():
    assert INDEX.count('class="auth-legal"') == 2
    for href in ('href="terms.html"', 'href="privacy.html"'):
        assert INDEX.count(href) >= 3, href  # login, signup, settings
    assert 'id="settings-privacy-policy-link"' in INDEX and 'id="settings-terms-link"' in INDEX


def test_static_build_publishes_both_pages():
    with tempfile.TemporaryDirectory() as d:
        subprocess.run([sys.executable, str(ROOT / "scripts/build_frontend.py"), "--out", d + "/dist"], check=True, capture_output=True)
        files = {p.name for p in Path(d, "dist").rglob("*") if p.is_file()}
    assert {"index.html", "privacy.html", "terms.html"} <= files
