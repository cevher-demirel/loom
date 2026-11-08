#!/usr/bin/env python3
"""Isolated local Google-sign-in test environment (Stage 30).

Starts, all on 127.0.0.1:
  * the REAL FastAPI backend (main.app) on a throwaway SQLite file,
  * the REAL index.html (a temp copy whose API URL points at that backend),
  * a local MOCK OpenID Connect provider standing in for Google.
Nothing contacts Google, Render, Turso, Pinecone, Resend or any production
service, and no secret is read from or written to disk (credentials are
placeholders that exist only inside this process).

  python scripts/oauth_test_env.py            # http, Secure flag off (loopback only)
  python scripts/oauth_test_env.py --https    # self-signed https: Secure cookies behave as in production
  python scripts/oauth_test_env.py --seed     # also create synthetic password user  dreamer / Moonlit9pond
  python scripts/oauth_test_env.py --real-google   # REAL Google, local only (see below)
Stop with Ctrl+C: the test database and temp site are deleted.

REAL GOOGLE MODE (Phase B). Requires --https. Fixed addresses, so the redirect URI registered in
Google Cloud can be exact:
    frontend  https://127.0.0.1:8443/        backend  https://localhost:8444/
    redirect URI to register:  https://localhost:8444/auth/google/callback
The frontend (127.0.0.1) and backend (localhost) are different sites, like loominous.org and the
Render host. The client ID and secret are typed at a hidden prompt (getpass): never taken from
chat, arguments, files or the environment, held only in this process, never printed or logged.
Everything binds to loopback; the database is a throwaway file deleted on exit.

Fail-closed guard: the process refuses to start if any production credential
(TURSO_*, PINECONE_*, RESEND_*) is present in the environment, and it only ever
uses a database file whose name starts with `loom_stage30_test_`.
"""
import argparse
import datetime
import http.server
import os
import shutil
import ssl
import sys
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# --- fail closed BEFORE database/main are imported -------------------------------
import devsafety  # noqa: E402

for _k in devsafety.GUARDED_ENV_VARS:       # blank (not pop): python-dotenv never overrides a set variable
    if os.environ.get(_k):
        sys.exit(f"REFUSING TO START: {_k} is set. This environment must never see production credentials. "
                 "Unset it (or run in a clean shell) and try again.")
    os.environ[_k] = ""
devsafety.assert_isolated_environment()

TEST_DB_PREFIX = "loom_stage30_test_"


class Stack:
    """Programmatic handle, also used by the tests."""

    def __init__(self, https=False, seed=False, port_api=0, port_front=0, workdir=None, index_html=None,
                 api_host="127.0.0.1", front_host="127.0.0.1", real_google=None):
        import socket
        import uvicorn
        import database, main, oauth                      # noqa: F401  (imported only after the guard)
        from tests.mock_idp import CLIENT_ID, CLIENT_SECRET, MockIdP

        def free():
            s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p

        self.https = https
        scheme = "https" if https else "http"
        bport, fport = port_api or free(), port_front or free()
        self.api, self.front = f"{scheme}://{api_host}:{bport}", f"{scheme}://{front_host}:{fport}"
        self.real = real_google is not None
        if self.real:
            # Hard guards for the real-provider mode: https, loopback names only, never a production host.
            assert https, "real Google mode requires https"
            for h in (api_host, front_host):
                assert h in ("localhost", "127.0.0.1"), "real Google mode is loopback-only"
        self.dir = Path(workdir or tempfile.mkdtemp(prefix="loom_stage30_env_"))
        self.db_path = str(self.dir / f"{TEST_DB_PREFIX}{os.getpid()}.db")
        assert os.path.basename(self.db_path).startswith(TEST_DB_PREFIX)

        database.USE_TURSO = False                         # never Turso
        database.DB_PATH = self.db_path
        database.init_db()
        if seed:
            database.create_user("dreamer", "dreamer@example.test", "Moonlit9pond")

        if self.real:
            self.idp = None
            cid, secret = real_google
            os.environ.update({"GOOGLE_CLIENT_ID": cid, "GOOGLE_CLIENT_SECRET": secret,
                               "PUBLIC_API_BASE": self.api, "FRONTEND_URL": self.front})
            # Google's real endpoints stay exactly as defined in oauth.PROVIDERS (nothing is replaced).
        else:
            self.idp = MockIdP()
            os.environ.update({"GOOGLE_CLIENT_ID": CLIENT_ID, "GOOGLE_CLIENT_SECRET": CLIENT_SECRET,
                               "PUBLIC_API_BASE": self.api, "FRONTEND_URL": self.front,
                               "NO_PROXY": "127.0.0.1,localhost"})
            oauth.PROVIDERS["google"] = self.idp.provider_config()

        site = self.dir / "site"; site.mkdir()
        html = Path(index_html or ROOT / "index.html").read_text()
        needle = 'var API_BASE = "https://loom-phas.onrender.com";'
        assert needle in html, "API_BASE line changed; update oauth_test_env.py"
        (site / "index.html").write_text(html.replace("https://loom-phas.onrender.com", self.api))
        shutil.copytree(ROOT / "assets", site / "assets")

        cert = key = None
        if https:
            cert, key = self._self_signed()

        class H(http.server.SimpleHTTPRequestHandler):
            def __init__(s, *a, **k): super().__init__(*a, directory=str(site), **k)
            def log_message(s, *a): pass
        self._front = http.server.ThreadingHTTPServer(("127.0.0.1", fport), H)   # always loopback
        if https:
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER); ctx.load_cert_chain(cert, key)
            self._front.socket = ctx.wrap_socket(self._front.socket, server_side=True)
        threading.Thread(target=self._front.serve_forever, daemon=True).start()

        cfg = dict(host="127.0.0.1", port=bport, log_level="warning")      # always loopback
        if https:
            cfg.update(ssl_certfile=cert, ssl_keyfile=key)
        self._srv = uvicorn.Server(uvicorn.Config(main.app, **cfg))
        self._t = threading.Thread(target=self._srv.run, daemon=True); self._t.start()
        while not self._srv.started:
            pass

    def _self_signed(self):
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import NameOID
        import ipaddress
        k = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "loominous-local-test")])
        now = datetime.datetime.now(datetime.timezone.utc)
        c = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(k.public_key())
             .serial_number(x509.random_serial_number()).not_valid_before(now - datetime.timedelta(minutes=1))
             .not_valid_after(now + datetime.timedelta(days=1))
             .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost"), x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]), False)
             .sign(k, hashes.SHA256()))
        cert, key = str(self.dir / "test-cert.pem"), str(self.dir / "test-key.pem")   # throwaway, never committed
        Path(cert).write_bytes(c.public_bytes(serialization.Encoding.PEM))
        Path(key).write_bytes(k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL,
                                              serialization.NoEncryption()))
        return cert, key

    def close(self):
        self._srv.should_exit = True; self._t.join(5)
        self._front.shutdown()
        if self.idp:
            self.idp.close()
        shutil.rmtree(self.dir, ignore_errors=True)       # removes the test DB, cert, temp site


def main_cli():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--https", action="store_true")
    ap.add_argument("--seed", action="store_true")
    ap.add_argument("--api-port", type=int, default=0)
    ap.add_argument("--front-port", type=int, default=0)
    ap.add_argument("--real-google", action="store_true", help="talk to REAL Google (loopback only; needs --https)")
    a = ap.parse_args()
    creds = None
    if a.real_google:
        if not a.https or a.seed:
            sys.exit("--real-google requires --https and cannot be combined with --seed.")
        for k in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "PUBLIC_API_BASE", "FRONTEND_URL"):
            if os.environ.get(k):
                sys.exit(f"REFUSING TO START: {k} is set in the environment. Real-Google mode takes credentials only "
                         "from the hidden prompt, and fixes the addresses itself. Run in a clean shell.")
        a.api_port, a.front_port = a.api_port or 8444, a.front_port or 8443
        uri = f"https://localhost:{a.api_port}/auth/google/callback"
        print("REAL GOOGLE TEST (local only). Nothing here touches Loominous production, Render or Turso.")
        print("Redirect URI this run uses (must be registered in Google Cloud):\n  " + uri)
        if input("Type YES to continue: ").strip() != "YES":
            sys.exit("cancelled")
        import getpass
        cid = getpass.getpass("Google client ID (hidden): ").strip()
        secret = getpass.getpass("Google client secret (hidden): ").strip()
        if not cid or not secret:
            sys.exit("Both values are required.")
        if "onrender.com" in cid or "onrender.com" in secret:
            sys.exit("That does not look like Google credentials.")
        creds = (cid, secret)
    s = Stack(https=a.https, seed=a.seed, port_api=a.api_port, port_front=a.front_port,
              api_host="localhost" if creds else "127.0.0.1", real_google=creds)
    print(f"Frontend : {s.front}/\nBackend  : {s.api}\nTest DB  : {s.db_path}")
    if creds:
        import oauth
        print("Redirect URI in use: " + oauth.redirect_uri("google"))
        print("Before signing in: open " + s.api + "/auth/providers once and accept the certificate warning, "
              "then open the frontend URL above and accept its warning too.")
    else:
        print(f"Mock IdP : {s.idp.base}\nMock Google user: " + s.idp.user["email"] + "  (approves automatically)")
    if a.https:
        print("Self-signed certificate: accept the browser warning, or use a browser launched with ignore-certificate-errors.")
    print("Ctrl+C to stop and delete everything.")
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        pass
    finally:
        s.close(); print("stopped; test data deleted")


if __name__ == "__main__":
    main_cli()
