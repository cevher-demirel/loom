# Release gates: Google sign-in

Local implementation complete does **not** mean production approved. Nothing in this stage touched production, DNS, Cloudflare, Render, Turso, or Google.
Status: **Verified** (shown by a local test) · **Blocked** (cannot proceed yet) · **Not tested** · **Owner action**.

## Code and security behaviour
| Gate | Status | Evidence / note |
|---|---|---|
| Browser-bound state, one-time, expiring, cookie attributes (HttpOnly, Secure on https, SameSite=Lax, Path=/auth, host-only, 10 min) | Verified (mock) | `tests/test_oauth.py`, https env test |
| Other-browser, missing/modified cookie, bad/expired/replayed state rejected | Verified (mock; unit + real Chromium) | |
| PKCE S256, nonce, iss/aud/exp/signature/sub checks | Verified (mock provider enforces PKCE) | |
| Linking safety, no email-only merge, unverified email refused, one identity per account | Verified | also holds if the unique index had to be skipped |
| Deletion: Google-only, password-only, both methods, wrong Google account, cancel, expiry, replay, expired session, final confirmation, data + identity cleanup | Verified (synthetic accounts, mock Google, real clicks) | |
| Settings/deletion reachable by real pointer input, 8 widths | Verified in Chromium (found and fixed an inert-app bug) | `INTERACTION_AUDIT.md` |
| Email/password login, signup, reset, deletion regressions | Verified | full suite |
| Secrets/codes not in logs; access log redacted | Verified | |
| Config fails safe; Google hidden until valid | Verified | |
| Login design unchanged | Verified by existing Stage 28 browser tests (34) | |
| **Real Google behaviour** (consent, `prompt=login`, `sub`, error pages) | **Not tested** | Phase B |
| **Safari / WebKit** (cookie handling on the redirect round trip, ITP) | **Not tested** | WebKit could not be installed here |
| **Real phones** (iOS Safari, Android Chrome) | **Not tested** | emulation only |
| Firefox | Not tested | |

## Data and migration
| Gate | Status | Note |
|---|---|---|
| Migration on synthetic clean/old/linked/duplicate/interrupted databases | Verified | `MIGRATION_SAFETY.md` |
| Startup survives pre-existing duplicate identities | Verified | index skipped with a counts-only warning |
| Production preflight run | **Owner action** | script ready, read-only, **not run** |
| Production has no conflicting identity rows | **Not tested** | depends on the preflight |
| Backup/restore point before first deploy | **Owner action** | take a Turso backup/branch before deploying |

## Deployment
| Gate | Status | Note |
|---|---|---|
| Cloudflare Pages source, build command, output directory | **Owner action** | cannot be read from the repo; see `DEPLOYMENT_AUDIT.md` |
| Pages publishes the repo root (backend source and docs public?) | **Owner action** | verify; optional `scripts/build_frontend.py` |
| `assets/login/` present on the live site | **Not tested** | tracked and relative; local build verified |
| Render deploy path while GitHub is suspended | **Blocked** | |
| Merge of the Stage 27d PR and Stage 28/29/30 branches | **Blocked** | GitHub account suspended |
| Callback hostname decision (Render hostname vs `api.loominous.org`) | **Owner action** | recommendation: A first |
| Google rejecting the Render host as an authorized domain | **Not tested** | a 5-minute console check |
| Render free-instance cold start (about a minute) during sign-in | **Not tested** | consider a paid/always-on instance before launch |
| Rate limits are per process (reset on restart, not shared) | Known limitation | |

## Google Cloud
| Gate | Status |
|---|---|
| Project, consent screen, test user, web client, exact redirect URI | **Owner action** (`GOOGLE_OWNER_SETUP.md`) |
| Credentials stored only as backend environment variables | **Owner action** |
| Separate test backend + throwaway database for Phase B | **Owner action** |
| Domain verification, privacy policy and terms, moving out of Testing | **Owner action**, only after the live test passes |

## Live Google test checklist (prepared, not performed)
Dedicated test Google account listed as a test user; separate Loominous test account; isolated backend and database.
- [ ] Startup `oauth_config` clean; button appears only then.
- [ ] Success (new user created once); repeat sign-in reuses it.
- [ ] Cancel at Google; error pages (revoked access, wrong redirect URI, wrong secret) show a generic message and leak nothing.
- [ ] Existing password account with the same email: link screen, wrong password rejected, correct password links.
- [ ] Callback URL opened in another browser/profile is rejected; reload/replay rejected.
- [ ] Logout and sign in again; session expiry.
- [ ] Deletion: Google-only (verify → final), cancel, wrong Google account; account with both methods.
- [ ] Desktop Chrome, Safari macOS, iPhone Safari, Android Chrome, a private window; cookie survives the round trip.
- [ ] Logs reviewed: no `code=`, `state=`, tokens or secrets.

## Known weaknesses carried forward (not Stage 30 scope)
Plaintext session tokens in the database; PBKDF2 at 200k iterations; one session per account; in-memory rate limits; account-enumeration messages; two older feeling-wheel browser tests use `force=True` on SVG paths. See `docs/stage29/SECURITY_AUDIT.md`.
