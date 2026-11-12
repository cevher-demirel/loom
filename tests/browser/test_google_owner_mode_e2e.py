"""Owner-only Google testing switch, end to end: the real index.html against the real FastAPI
app and the local mock Google (tests/mock_idp.py). Placeholder credentials, loopback only; this
is NOT a test against real Google."""
import re

import pytest

import database
from tests.browser.test_stage29_google_e2e import _ctx, _open, _signed_in, stack  # noqa: F401

pytestmark = pytest.mark.browser
KEY = "owner-test-key-" + "x" * 20


@pytest.fixture
def restricted(monkeypatch):
    monkeypatch.setenv("GOOGLE_SIGNIN_MODE", "test")
    monkeypatch.setenv("GOOGLE_TEST_KEY", KEY)
    monkeypatch.setenv("GOOGLE_TEST_EMAILS", "dreamer@example.test")   # the mock Google's default account


def _open_as_owner(page, s):
    page.goto(s.front + "/#owner")
    page.wait_for_function("document.getElementById('app-splash').hidden === true", timeout=10000)
    page.wait_for_timeout(400)
    page.fill("#auth-owner-key", KEY)
    page.click("#auth-owner-btn")
    page.wait_for_selector("#auth-google-btn", state="visible", timeout=10000)


def test_ordinary_visitors_never_see_the_google_button(browser, stack, restricted):
    ctx, page, errs = _ctx(browser, stack)
    _open(page, stack)
    page.wait_for_timeout(500)
    assert page.locator("#auth-google-btn").is_hidden() and page.locator("#auth-providers").is_hidden()
    page.click("#login-to-signup-btn")
    assert page.locator("#auth-google-btn").is_hidden()
    assert not errs, errs
    ctx.close()


def test_owner_sees_the_button_key_leaves_the_url_and_sign_in_completes(browser, stack, restricted):
    ctx, page, errs = _ctx(browser, stack)
    _open_as_owner(page, stack)
    assert page.locator("#auth-google-btn").is_visible()
    assert KEY not in page.url and "google_test" not in page.url and "owner" not in page.url
    assert page.locator("#auth-owner").is_hidden() and page.input_value("#auth-owner-key") == ""
    page.click("#auth-google-btn")
    _signed_in(page)
    assert "oauth_" not in page.url and KEY not in page.url
    assert not errs, errs
    ctx.close()


def test_owner_with_an_unlisted_google_account_is_refused_and_nothing_is_created(browser, stack, restricted):
    stack.idp.user.update(sub="stranger", email="stranger@example.test")
    before = database._execute("SELECT COUNT(*) AS n FROM users")[0][0]["n"]
    ctx, page, errs = _ctx(browser, stack)
    _open_as_owner(page, stack)
    page.click("#auth-google-btn")
    page.wait_for_url(re.compile(r"^http://127\.0\.0\.1:\d+/(#.*)?$"))
    page.wait_for_timeout(900)
    assert not page.evaluate("localStorage.getItem('loom_token')")
    assert "isn't open to this account yet" in page.locator("#auth-notice").inner_text()
    assert database._execute("SELECT COUNT(*) AS n FROM users")[0][0]["n"] == before
    ctx.close()


def test_cancelling_at_google_returns_to_sign_in(browser, stack, restricted):
    stack.idp.mode = "cancel"
    ctx, page, errs = _ctx(browser, stack)
    _open_as_owner(page, stack)
    page.click("#auth-google-btn")
    page.wait_for_url(re.compile(r"^http://127\.0\.0\.1:\d+/(#.*)?$"))
    page.wait_for_timeout(900)
    assert not page.evaluate("localStorage.getItem('loom_token')")
    assert "cancelled" in page.locator("#auth-notice").inner_text().lower()
    ctx.close()


def test_a_wrong_key_shows_nothing(browser, stack, restricted):
    ctx, page, errs = _ctx(browser, stack)
    page.goto(stack.front + "/#owner")
    page.wait_for_function("document.getElementById('app-splash').hidden === true", timeout=10000)
    page.wait_for_timeout(400)
    page.fill("#auth-owner-key", "not-the-key")
    page.click("#auth-owner-btn")
    page.wait_for_timeout(800)
    assert page.locator("#auth-google-btn").is_hidden()
    ctx.close()


def test_owner_box_is_absent_for_ordinary_visitors_and_key_in_url_is_ignored(browser, stack, restricted):
    ctx, page, errs = _ctx(browser, stack)
    _open(page, stack)
    assert page.locator("#auth-owner").is_hidden()
    page.goto(stack.front + "/#google_test=" + KEY)      # the old link style must no longer unlock anything
    page.wait_for_function("document.getElementById('app-splash').hidden === true", timeout=10000)
    page.wait_for_timeout(600)
    assert page.locator("#auth-google-btn").is_hidden()
    assert page.evaluate("sessionStorage.getItem('loom_google_test')") is None
    ctx.close()


def test_the_key_field_is_a_password_field(browser, stack, restricted):
    ctx, page, errs = _ctx(browser, stack)
    page.goto(stack.front + "/#owner")
    page.wait_for_function("document.getElementById('app-splash').hidden === true", timeout=10000)
    page.wait_for_timeout(400)
    assert page.get_attribute("#auth-owner-key", "type") == "password"
    assert "owner" not in page.url
    ctx.close()
