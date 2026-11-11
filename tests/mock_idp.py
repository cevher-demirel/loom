"""
tests/mock_idp.py -- a small local OpenID Connect provider for the OAuth tests.

It is a real HTTP server on 127.0.0.1 (authorize, token, JWKS endpoints), so the
code under test makes genuine HTTP requests and verifies genuine RS256
signatures; only the provider itself is fake. It enforces what Google
enforces: single-use codes, PKCE S256, matching client id/secret/redirect URI.
Nothing here ever leaves the machine, and every credential is a placeholder.
"""

import base64
import hashlib
import json
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlencode, urlparse

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

CLIENT_ID = "test-google-id"
CLIENT_SECRET = "test-google-secret"
GOOGLE_ISSUER = "https://accounts.google.com"


class MockIdP:
    def __init__(self):
        self.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(self.key.public_key()))
        jwk.update({"kid": "mock-key", "alg": "RS256", "use": "sig"})
        self.jwks = {"keys": [jwk]}
        self.codes = {}
        self.authorize_requests = []
        self.token_requests = []
        # What the next sign-in looks like; tests change these.
        self.user = {"sub": "google-sub-1", "email": "dreamer@example.test",
                     "email_verified": True, "name": "Test Dreamer"}
        self.mode = "approve"            # or "cancel"
        self.claim_overrides = {}        # e.g. {"iss": "...", "aud": "..."}
        self.nonce_override = None
        self.exp_offset = 600
        self.auth_age = 0                # seconds since the person really signed in; None = omit the claim
        self.sign_with = self.key        # set to another key to forge
        idp = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, status, body=b"", headers=None, ctype="application/json"):
                self.send_response(status)
                self.send_header("Content-Type", ctype)
                for k, v in (headers or {}).items():
                    self.send_header(k, v)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                u = urlparse(self.path)
                q = {k: v[0] for k, v in parse_qs(u.query).items()}
                if u.path == "/jwks":
                    return self._send(200, json.dumps(idp.jwks).encode())
                if u.path == "/authorize":
                    idp.authorize_requests.append(q)
                    redirect = q["redirect_uri"]
                    if idp.mode == "cancel":
                        loc = redirect + "?" + urlencode({"error": "access_denied", "state": q["state"]})
                    else:
                        code = secrets.token_urlsafe(24)
                        idp.codes[code] = {"challenge": q["code_challenge"], "nonce": q["nonce"],
                                           "redirect_uri": redirect, "user": dict(idp.user), "used": False}
                        loc = redirect + "?" + urlencode({"code": code, "state": q["state"]})
                    return self._send(302, b"", {"Location": loc})
                self._send(404)

            def do_POST(self):
                if urlparse(self.path).path != "/token":
                    return self._send(404)
                body = self.rfile.read(int(self.headers.get("Content-Length", 0))).decode()
                f = {k: v[0] for k, v in parse_qs(body).items()}
                idp.token_requests.append(f)
                rec = idp.codes.get(f.get("code"))
                bad = (not rec or rec["used"] or f.get("client_id") != CLIENT_ID
                       or f.get("client_secret") != CLIENT_SECRET
                       or f.get("redirect_uri") != rec["redirect_uri"]
                       or f.get("grant_type") != "authorization_code")
                if not bad:
                    digest = base64.urlsafe_b64encode(
                        hashlib.sha256(f.get("code_verifier", "").encode()).digest()).rstrip(b"=").decode()
                    bad = digest != rec["challenge"]          # PKCE S256
                if bad:
                    return self._send(400, json.dumps({"error": "invalid_grant"}).encode())
                rec["used"] = True
                claims = {"iss": GOOGLE_ISSUER, "aud": CLIENT_ID, "iat": int(time.time()),
                          "exp": int(time.time()) + idp.exp_offset,
                          "nonce": idp.nonce_override if idp.nonce_override is not None else rec["nonce"]}
                if idp.auth_age is not None:
                    claims["auth_time"] = int(time.time()) - int(idp.auth_age)
                claims.update(rec["user"])
                claims.update(idp.claim_overrides)
                token = jwt.encode(claims, idp.sign_with, algorithm="RS256", headers={"kid": "mock-key"})
                self._send(200, json.dumps({"id_token": token, "access_token": "mock-access",
                                            "token_type": "Bearer"}).encode())

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def provider_config(self):
        return {"authorize": self.base + "/authorize", "token": self.base + "/token",
                "jwks": self.base + "/jwks", "issuers": (GOOGLE_ISSUER, "accounts.google.com"),
                "scope": "openid email profile", "algorithms": ["RS256"]}

    def close(self):
        self.server.shutdown()
        self.server.server_close()
