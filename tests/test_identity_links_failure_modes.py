"""
tests/test_identity_links_failure_modes.py -- Stage 8 Phase B.2
Priority 1: identity-link load/mutation failure safety.

Exercises the REAL loadPersonIdentityLinks / savePersonIdentityLink /
deletePersonIdentityLink / resetPersonIdentityLinksState source,
extracted verbatim out of index.html and run under Node (the same
extraction-and-run approach test_people_identity_links.py and
test_identity_parity.py already use), against a controllable fake
`authedFetch` that stands in for the real network call. This is the
dedicated test coverage the Phase B.2 spec calls for: 401/403/404/500,
a network timeout/rejection, malformed JSON, a stale (prior-account)
response landing late, rapid repeated mutation calls, and that a
failed PUT/DELETE never corrupts in-memory state.

Faking `authedFetch` itself (rather than mocking fetch underneath it)
is deliberate: authedFetch's own 401-retry-then-logout behavior is
existing, shared, app-wide plumbing untouched by Phase B.2 -- every
endpoint in the app goes through it the same way, so re-testing IT
here would be testing something else entirely. What Phase B.2 Priority
1 actually added is everything loadPersonIdentityLinks/
savePersonIdentityLink/deletePersonIdentityLink do with whatever
authedFetch resolves or rejects with, which is exactly the boundary
these tests fake and verify.
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

INDEX_HTML = Path(__file__).resolve().parent.parent / "index.html"


@pytest.fixture(scope="module")
def links_js():
    text = INDEX_HTML.read_text()
    start = text.index("var personIdentityOverridesByKey = {};")
    end = text.index("function resolvePersonMention(raw, index) {")
    block = text[start:end]
    assert "function loadPersonIdentityLinks()" in block
    assert "function savePersonIdentityLink(" in block
    assert "function deletePersonIdentityLink(" in block
    assert "function resetPersonIdentityLinksState()" in block, "extraction boundary drifted -- update the markers above"
    return block


def _run(js_source, driver_js):
    if shutil.which("node") is None:
        pytest.skip("node is not available in this environment")
    harness = js_source + "\n" + driver_js
    result = subprocess.run(["node", "-e", harness], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, f"node failed:\n{result.stderr}\n--- harness ---\n{harness}"
    return json.loads(result.stdout)


# Every scenario below installs its own `authedFetch` just before the
# call under test, then reports back loadState/overrides (and, for
# mutation tests, whether the call rejected) as JSON so pytest can
# assert on it.

def _dump_state_js():
    return (
        "console.log(JSON.stringify({"
        "loadState: personIdentityLinksLoadState, "
        "overrides: personIdentityOverridesByKey"
        "}));"
    )


# ---------------------------------------------------------------------
# GET failure modes: each must leave the state CLEARLY in 'error', not
# silently indistinguishable from a real empty/successful load.
# ---------------------------------------------------------------------

@pytest.mark.parametrize("status", [401, 403, 404, 500])
def test_load_http_error_status_sets_error_state_not_empty_loaded(links_js, status):
    driver = (
        f"authedFetch = function() {{ return Promise.resolve({{ ok: false, status: {status} }}); }};\n"
        "loadPersonIdentityLinks().then(function () { " + _dump_state_js() + " });\n"
    )
    result = _run(links_js, driver)
    assert result["loadState"] == "error"
    assert result["overrides"] == {}


def test_load_network_rejection_sets_error_state(links_js):
    """A timeout/offline/DNS failure rejects the fetch promise outright
    -- never reaches a .then at all -- and must be caught the same way
    as a bad HTTP status."""
    driver = (
        "authedFetch = function() { return Promise.reject(new Error('network timeout')); };\n"
        "loadPersonIdentityLinks().then(function () { " + _dump_state_js() + " });\n"
    )
    result = _run(links_js, driver)
    assert result["loadState"] == "error"


def test_load_malformed_json_sets_error_state(links_js):
    """A 200 response whose body isn't the array shape expected (here,
    a plain object) must not be silently treated as a correction-free
    list -- it's an error, since it means something is wrong with the
    endpoint, not that there happen to be zero corrections."""
    driver = (
        "authedFetch = function() { return Promise.resolve({ ok: true, status: 200, "
        "json: function() { return Promise.resolve({ not: 'an array' }); } }); };\n"
        "loadPersonIdentityLinks().then(function () { " + _dump_state_js() + " });\n"
    )
    result = _run(links_js, driver)
    assert result["loadState"] == "error"


def test_load_json_parse_failure_sets_error_state(links_js):
    """res.json() itself rejecting (truly unparsable body, not just an
    unexpected shape) is caught the same way."""
    driver = (
        "authedFetch = function() { return Promise.resolve({ ok: true, status: 200, "
        "json: function() { return Promise.reject(new Error('Unexpected token')); } }); };\n"
        "loadPersonIdentityLinks().then(function () { " + _dump_state_js() + " });\n"
    )
    result = _run(links_js, driver)
    assert result["loadState"] == "error"


def test_load_success_after_error_recovers_cleanly_via_retry(links_js):
    """The documented retry path: a failed load followed by a genuinely
    successful one (the person tapping 'Retry') ends in 'loaded' with
    the real corrections, not stuck in 'error' or silently empty."""
    driver = (
        "authedFetch = function() { return Promise.resolve({ ok: false, status: 500 }); };\n"
        "loadPersonIdentityLinks().then(function () {\n"
        "  authedFetch = function() { return Promise.resolve({ ok: true, status: 200, json: function() {\n"
        "    return Promise.resolve([{ subject_key: 'role:brother', decision: 'merge', target_key: 'james', target_label: 'James' }]);\n"
        "  } }); };\n"
        "  return loadPersonIdentityLinks();\n"
        "}).then(function () { " + _dump_state_js() + " });\n"
    )
    result = _run(links_js, driver)
    assert result["loadState"] == "loaded"
    assert result["overrides"] == {"role:brother": {"subject_key": "role:brother", "decision": "merge", "target_key": "james", "target_label": "James"}}


def test_a_failure_after_a_real_success_does_not_erase_already_loaded_corrections(links_js):
    """Priority 1's explicit requirement: 'never erase/overwrite cached
    decisions on a failed fetch.' A transient failure on a SECOND load
    (an automatic refresh, say) must not wipe out corrections a prior
    successful load already put in memory -- only the load state moves
    to 'error', the data stays."""
    driver = (
        "authedFetch = function() { return Promise.resolve({ ok: true, status: 200, json: function() {\n"
        "  return Promise.resolve([{ subject_key: 'abby', decision: 'merge', target_key: 'bob', target_label: 'Bob' }]);\n"
        "} }); };\n"
        "loadPersonIdentityLinks().then(function () {\n"
        "  authedFetch = function() { return Promise.resolve({ ok: false, status: 500 }); };\n"
        "  return loadPersonIdentityLinks();\n"
        "}).then(function () { " + _dump_state_js() + " });\n"
    )
    result = _run(links_js, driver)
    assert result["loadState"] == "error"
    assert result["overrides"] == {"abby": {"subject_key": "abby", "decision": "merge", "target_key": "bob", "target_label": "Bob"}}


# ---------------------------------------------------------------------
# Stale-response / account-switch race: a load/save/delete that was
# still in flight from a PREVIOUS account generation must never mutate
# the CURRENT account's state once it resolves late.
# ---------------------------------------------------------------------

def test_a_load_still_in_flight_during_logout_never_lands_on_the_new_account(links_js):
    driver = (
        "var resolveSlow;\n"
        "authedFetch = function() { return new Promise(function (res) { resolveSlow = res; }); };\n"
        "var p = loadPersonIdentityLinks();\n"
        "resetPersonIdentityLinksState();\n"  # simulates logout/new-login happening before the slow response arrives
        "resolveSlow({ ok: true, status: 200, json: function() {\n"
        "  return Promise.resolve([{ subject_key: 'role:brother', decision: 'merge', target_key: 'james', target_label: 'James' }]);\n"
        "} });\n"
        "p.then(function () { " + _dump_state_js() + " });\n"
    )
    result = _run(links_js, driver)
    # The stale response must be discarded entirely: the fresh account's
    # state (idle, empty) is exactly as resetPersonIdentityLinksState
    # left it, never overwritten by the previous account's data.
    assert result["loadState"] == "idle"
    assert result["overrides"] == {}


def test_a_save_still_in_flight_during_logout_never_lands_on_the_new_account(links_js):
    driver = (
        "var resolveSlow;\n"
        "authedFetch = function() { return new Promise(function (res) { resolveSlow = res; }); };\n"
        "var p = savePersonIdentityLink('role:brother', 'merge', 'james', 'James');\n"
        "resetPersonIdentityLinksState();\n"
        "resolveSlow({ ok: true, status: 200, json: function() {\n"
        "  return Promise.resolve({ subject_key: 'role:brother', decision: 'merge', target_key: 'james', target_label: 'James' });\n"
        "} });\n"
        "p.then(function () { " + _dump_state_js() + " });\n"
    )
    result = _run(links_js, driver)
    assert result["overrides"] == {}  # the new (empty) account's map was never touched


# ---------------------------------------------------------------------
# Mutation failure safety: PUT/DELETE must never leave the in-memory
# map changed unless the server actually confirmed the write.
# ---------------------------------------------------------------------

def test_save_failure_leaves_overrides_unchanged(links_js):
    driver = (
        "authedFetch = function() { return Promise.resolve({ ok: true, status: 200, json: function() {\n"
        "  return Promise.resolve([{ subject_key: 'abby', decision: 'merge', target_key: 'bob', target_label: 'Bob' }]);\n"
        "} }); };\n"
        "loadPersonIdentityLinks().then(function () {\n"
        "  authedFetch = function() { return Promise.resolve({ ok: false, status: 500 }); };\n"
        "  return savePersonIdentityLink('role:brother', 'merge', 'james', 'James').catch(function (e) { return 'rejected: ' + e.message; });\n"
        "}).then(function (outcome) {\n"
        "  var state = JSON.parse('" + '{}' + "'.replace('{}', '{}'));\n"
        "  console.log(JSON.stringify({ outcome: outcome, overrides: personIdentityOverridesByKey }));\n"
        "});\n"
    )
    result = _run(links_js, driver)
    assert result["outcome"].startswith("rejected")
    # The pre-existing "abby" correction is untouched, and the failed
    # "role:brother" write never appears -- no partial/optimistic state.
    assert result["overrides"] == {"abby": {"subject_key": "abby", "decision": "merge", "target_key": "bob", "target_label": "Bob"}}


def test_delete_failure_leaves_overrides_unchanged(links_js):
    driver = (
        "authedFetch = function() { return Promise.resolve({ ok: true, status: 200, json: function() {\n"
        "  return Promise.resolve([{ subject_key: 'abby', decision: 'merge', target_key: 'bob', target_label: 'Bob' }]);\n"
        "} }); };\n"
        "loadPersonIdentityLinks().then(function () {\n"
        "  authedFetch = function() { return Promise.resolve({ ok: false, status: 500 }); };\n"
        "  return deletePersonIdentityLink('abby').catch(function (e) { return 'rejected: ' + e.message; });\n"
        "}).then(function (outcome) {\n"
        "  console.log(JSON.stringify({ outcome: outcome, overrides: personIdentityOverridesByKey }));\n"
        "});\n"
    )
    result = _run(links_js, driver)
    assert result["outcome"].startswith("rejected")
    assert result["overrides"] == {"abby": {"subject_key": "abby", "decision": "merge", "target_key": "bob", "target_label": "Bob"}}


def test_successful_save_then_delete_round_trips_cleanly(links_js):
    """Sanity check that the happy path still works end to end through
    this same harness, so the failure-mode assertions above are known
    to be testing real behavior, not an artifact of the stubs."""
    driver = (
        "authedFetch = function(path, opts) { return Promise.resolve({ ok: true, status: 200, json: function() {\n"
        "  return Promise.resolve({ subject_key: 'role:brother', decision: 'merge', target_key: 'james', target_label: 'James' });\n"
        "} }); };\n"
        "savePersonIdentityLink('role:brother', 'merge', 'james', 'James').then(function () {\n"
        "  authedFetch = function() { return Promise.resolve({ ok: true, status: 200, json: function() { return Promise.resolve({}); } }); };\n"
        "  return deletePersonIdentityLink('role:brother');\n"
        "}).then(function () { " + _dump_state_js() + " });\n"
    )
    result = _run(links_js, driver)
    assert result["overrides"] == {}


def test_rapid_repeated_save_calls_each_resolve_independently_without_crashing(links_js):
    """Two taps in quick succession (a double-tap, or a slow first
    response that lets the person tap again) must not throw or corrupt
    state -- the last one to actually resolve successfully wins, and
    every promise settles."""
    driver = (
        "authedFetch = function() { return Promise.resolve({ ok: true, status: 200, json: function() {\n"
        "  return Promise.resolve({ subject_key: 'role:brother', decision: 'merge', target_key: 'james', target_label: 'James' });\n"
        "} }); };\n"
        "Promise.all([\n"
        "  savePersonIdentityLink('role:brother', 'merge', 'james', 'James'),\n"
        "  savePersonIdentityLink('role:brother', 'merge', 'james', 'James'),\n"
        "]).then(function () { " + _dump_state_js() + " });\n"
    )
    result = _run(links_js, driver)
    assert result["overrides"]["role:brother"]["target_key"] == "james"
