"""
tests/test_env_harness.py -- Stage 30 Phase B: the isolated test-environment script itself
(shutdown, cleanup, credential sanity checks). Mock provider only; no credential, no Google call.
"""
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = str(ROOT / "scripts" / "oauth_test_env.py")
sys.path.insert(0, str(ROOT))


def _env(tmp):
    e = {k: v for k, v in os.environ.items()
         if k not in ("TURSO_DATABASE_URL", "TURSO_AUTH_TOKEN", "GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET",
                      "PUBLIC_API_BASE", "FRONTEND_URL")}
    e["TMPDIR"] = str(tmp); e["TEMP"] = str(tmp); e["TMP"] = str(tmp)
    return e


def _start(tmp):
    p = subprocess.Popen([sys.executable, "-u", SCRIPT], env=_env(tmp), cwd=str(ROOT), text=True,
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    out = []
    deadline = time.time() + 60
    while time.time() < deadline:
        line = p.stdout.readline()
        if not line:
            break
        out.append(line)
        if "Ctrl+C to stop" in line:
            return p, out
    p.kill()
    raise AssertionError("did not start: " + "".join(out)[-500:])


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX signals; Windows is covered by the polling-loop design test")
@pytest.mark.parametrize("sig", [signal.SIGINT, signal.SIGTERM])
def test_script_stops_promptly_on_interrupt_and_deletes_its_data(tmp_path, sig):
    p, out = _start(tmp_path)
    assert list(tmp_path.glob("loom_stage30_env_*")), "environment folder should exist while running"
    p.send_signal(sig)
    rest, _ = p.communicate(timeout=20)
    assert p.returncode == 0 and "stopped; test data deleted" in rest
    assert not list(tmp_path.glob("loom_stage30_env_*"))


def test_wait_loop_polls_with_a_timeout_so_windows_can_interrupt_it():
    """A bare Event().wait() cannot be interrupted by Ctrl+C on Windows; the script must poll."""
    text = Path(SCRIPT).read_text()
    assert "threading.Event().wait()" not in text
    assert "time.sleep(0.25)" in text and "SIGBREAK" in text and "SIGINT" in text


def test_cleanup_removes_only_recognised_leftovers(tmp_path):
    stale1 = tmp_path / "loom_stage30_env_aaaa"; stale1.mkdir(); (stale1 / "loom_stage30_test_123.db").write_text("x")
    stale2 = tmp_path / "loom_stage30_env_bbbb"; stale2.mkdir(); (stale2 / ".loominous-test-env").write_text("x")
    decoy = tmp_path / "loom_stage30_env_cccc"; decoy.mkdir(); (decoy / "mine.txt").write_text("keep")
    other = tmp_path / "unrelated_folder"; other.mkdir()
    run = lambda stdin: subprocess.run([sys.executable, SCRIPT, "--cleanup"], input=stdin, env=_env(tmp_path),
                                       cwd=str(ROOT), capture_output=True, text=True, timeout=60)
    r = run("no\n")
    assert "nothing deleted" in r.stdout and stale1.exists() and stale2.exists()       # needs the word DELETE
    run("DELETE\n")
    assert not stale1.exists() and not stale2.exists()
    assert decoy.exists() and other.exists()                                            # not recognised: untouched
    assert "No leftover" in run("").stdout


def test_close_reports_honestly_when_the_folder_could_not_be_deleted(monkeypatch, fresh_db):
    import database, oauth
    from scripts.oauth_test_env import Stack
    saved_env, saved_google = dict(os.environ), dict(oauth.PROVIDERS["google"])
    saved_db, saved_turso = database.DB_PATH, database.USE_TURSO
    s = Stack()
    try:
        monkeypatch.setattr("scripts.oauth_test_env.shutil.rmtree", lambda *a, **k: None)
        monkeypatch.setattr("scripts.oauth_test_env.time.sleep", lambda *_: None)
        assert s.close() is False                      # still there: the caller must tell the person
    finally:
        monkeypatch.undo()
        import shutil; shutil.rmtree(s.dir, ignore_errors=True)
        os.environ.clear(); os.environ.update(saved_env)
        oauth.PROVIDERS["google"] = saved_google
        database.DB_PATH, database.USE_TURSO = saved_db, saved_turso


GOOD_ID = "123456789012-abcdefg1234567.apps.googleusercontent.com"


def test_credential_format_check_catches_paste_mistakes_without_echoing_values():
    from scripts.oauth_test_env import check_credential_format as chk
    assert chk(GOOD_ID, "GOCSPX-abcdefghijklmnop") == []
    assert any("quote" in p for p in chk('"' + GOOD_ID + '"', "GOCSPX-abc"))
    assert any("space" in p for p in chk(GOOD_ID, "GOCSPX-abc def"))
    assert any("does not look like" in p for p in chk("not-an-id", "GOCSPX-abc"))
    assert any("GOCSPX" in p for p in chk(GOOD_ID, "something-else"))
    probs = " ".join(chk("leaky-id-value", "leaky-secret-value"))
    assert "leaky-id-value" not in probs and "leaky-secret-value" not in probs


class _R:
    def __init__(self, body): self._b = body
    def json(self):
        if isinstance(self._b, Exception): raise self._b
        return self._b


def test_live_credential_check_interprets_googles_answer():
    from scripts.oauth_test_env import check_google_credentials as chk
    uri = "https://localhost:8444/auth/google/callback"
    sent = {}
    def post(body):
        def f(data):
            sent.update(data); return _R(body)
        return f
    assert chk(GOOD_ID, "s", uri, post({"error": "invalid_client"})) == ("rejected", "invalid_client")
    assert chk(GOOD_ID, "s", uri, post({"error": "invalid_grant"})) == ("accepted", "invalid_grant")
    assert chk(GOOD_ID, "s", uri, post({"error": "Free text, with secret"}))[1] == "unknown"
    def down(data): raise ConnectionError("no network")
    assert chk(GOOD_ID, "s", uri, down) == ("unreachable", "ConnectionError")
    assert sent["code"] == "loominous-credential-check" and sent["redirect_uri"] == uri   # deliberately invalid code
