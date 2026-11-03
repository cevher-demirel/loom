import os

import pytest

from harness import pw


@pytest.fixture(scope="module")
def browser():
    with pw.sync_playwright() as p:
        try:
            b = p.chromium.launch()
        except Exception as e:  # no browser installed
            if os.environ.get("REQUIRE_BROWSER") == "1":
                raise
            pytest.skip("chromium unavailable: %s" % e)
        yield b
        b.close()
