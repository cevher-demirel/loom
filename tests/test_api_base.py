"""Guards the frontend's backend address (api.loominous.org migration)."""
import re
from pathlib import Path

HTML = (Path(__file__).resolve().parent.parent / "index.html").read_text()


def test_api_base_is_the_loominous_api_domain_over_https():
    m = re.search(r'var API_BASE = "([^"]+)";', HTML)
    assert m, "API_BASE line not found"
    assert m.group(1) == "https://api.loominous.org"


def test_page_has_no_other_hardcoded_backend_host():
    assert "onrender.com" not in HTML
