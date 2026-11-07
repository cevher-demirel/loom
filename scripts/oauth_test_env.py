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
Stop with Ctrl+C: the test database and temp site are deleted.

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

    def __init__(self, https=False, seed=False, port_api=0, port_front=0, workdir=None, index_html=None):
        import socket
        import uvicorn
        import database, main, oauth                      # noqa: F401  (imported only after the guard)
        from tests.mock_idp import CLIENT_ID, CLIENT_SECRET, MockIdP

        def free():
            s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p

        self.https = https
        scheme = "https" if https else "http"
        bport, fport = port_api or free(), port_front or free()
        self.api, self.front = f"{scheme}://127.0.0.1:{bport}", f"{scheme}://127.0.0.1:{fport}"
        self.dir = Path(workdir or tempfile.mkdtemp(prefix="loom_stage30_env_"))
        self.db_path = str(self.dir / f"{TEST_DB_PREFIX}{os.getpid()}.db")
        assert os.path.basename(self.db_path).startswith(TEST_DB_PREFIX)

        database.USE_TURSO = False                         # never Turso
        database.DB_PATH = self.db_path
        database.init_db()
        if seed:
            database.create_user("dreamer", "dreamer@example.test", "Moonlit9pond")

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
        self._front = http.server.ThreadingHTTPServer(("127.0.0.1", fport), H)
        if https:
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER); ctx.load_cert_chain(cert, key)
            self._front.socket = ctx.wrap_socket(self._front.socket, server_side=True)
        threading.Thread(target=self._front.serve_forever, daemon=True).start()

        cfg = dict(host="127.0.0.1", port=bport, log_level="warning")
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
             .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]), False)
             .sign(k, hashes.SHA256()))
        cert, key = str(self.dir / "test-cert.pem"), str(self.dir / "test-key.pem")   # throwaway, never committed
        Path(cert).write_bytes(c.public_bytes(serialization.Encoding.PEM))
        Path(key).write_bytes(k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL,
                                              serialization.NoEncryption()))
        return cert, key

    def close(self):
        self._srv.should_exit = True; self._t.join(5)
        self._front.shutdown(); self.idp.close()
        shutil.rmtree(self.dir, ignore_errors=True)       # removes the test DB, cert, temp site


def main_cli():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--https", action="store_true")
    ap.add_argument("--seed", action="store_true")
    ap.add_argument("--api-port", type=int, default=0)
    ap.add_argument("--front-port", type=int, default=0)
    a = ap.parse_args()
    s = Stack(https=a.https, seed=a.seed, port_api=a.api_port, port_front=a.front_port)
    print(f"Frontend : {s.front}/\nBackend  : {s.api}\nMock IdP : {s.idp.base}\nTest DB  : {s.db_path}")
    print("Mock Google user: " + s.idp.user["email"] + "  (approves automatically)")
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
