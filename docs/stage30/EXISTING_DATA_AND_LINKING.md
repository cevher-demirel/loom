# Existing data conditions vs. Google linking (reviewed 2026-11-09)

Real-backup copy check (owner-run, counts only): 65 accounts, 183 dreams, 45 accounts without an email, one email shared by several accounts, 0 identity conflicts, PASS.

| Condition | What Stage 30 does | Can it merge or take over the wrong account? |
|---|---|---|
| Account without an email (45) | `find_user_by_email` never matches a blank email; a Google email is never blank-matched. A Google sign-in becomes its own NEW account. | No. Side effect: the person ends up with two accounts (old password one, new Google one). They are never merged automatically. |
| One email on several accounts | Before this branch: the first row was offered for linking (arbitrary). Now: `email_ambiguous`, no link offered, no account created, nothing written. The person is told to sign in with username and password. | No. Test: `test_google_email_shared_by_several_accounts_is_refused_not_guessed`. |
| Email on exactly one account | Google gives a one-time link ticket; the link happens only after that account's password is entered (rate limited, ticket burns after repeated failures, single use). | No. A matching email alone never links. Test: `test_link_requires_the_existing_accounts_password` and others. |
| Google email not verified | Refused (`email_unverified`). | No. |
| Mixed-case stored email | Matched case-insensitively. | No. |
| A Google identity already linked elsewhere | `link_identity_safely` returns conflict (409), uniqueness enforced by the database. | No. |

Limits: legacy emails were never verified by Loominous, so an old account's email proves nothing by itself; that is exactly why the password is required to link. Whoever knows an old account's password can link their own Google to it (by design).
Open decision: whether to tell no-email users to add an email first (not built).
