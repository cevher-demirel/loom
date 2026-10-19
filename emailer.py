"""
emailer.py -- sends transactional email via Resend's HTTP API.

Only used for password-reset links right now. Resend was picked over
running an SMTP server or wiring up a heavier SDK because it's a single
HTTPS POST with an API key -- no mail server to run, no SPF/DKIM to
hand-configure beyond verifying one sending domain in their dashboard,
and a free tier that's plenty for a project at this scale. Sent over
httpx, already a transitive dependency of the anthropic SDK, rather
than adding a new one just for this.

Degrades gracefully by design, same as vectorstore.py's relationship
with Pinecone: every function here is a no-op if RESEND_API_KEY isn't
set, so an environment that hasn't been given one yet (a fresh local
dev setup, say) still runs the whole app fine -- it just can't actually
deliver a reset email yet. is_configured() is how a caller would check
which situation it's in, though main.py's /forgot-password doesn't
actually need to: it gives the exact same response either way, since
telling the person "that didn't work, email isn't set up" would also
tell them, by omission, when an email *does* have a real account.
"""

import os
import httpx
from dotenv import load_dotenv

load_dotenv()

RESEND_API_KEY = os.environ.get("RESEND_API_KEY")
# Resend requires sending from a domain you've verified in their
# dashboard. "onboarding@resend.dev" works immediately with zero setup,
# but Resend only actually delivers mail sent from it to the account's
# own email address -- fine for testing this yourself, not for real
# users. Set RESEND_FROM_EMAIL once a real sending domain is verified.
RESEND_FROM = os.environ.get("RESEND_FROM_EMAIL", "Loom <onboarding@resend.dev>")


def is_configured():
    return bool(RESEND_API_KEY)


def _send(to_email, subject, html):
    """Shared send path for both email types below -- same client, same
    failure handling, just a different subject/body."""
    if not RESEND_API_KEY:
        return False
    try:
        response = httpx.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {RESEND_API_KEY}"},
            json={"from": RESEND_FROM, "to": [to_email], "subject": subject, "html": html},
            timeout=10,
        )
        return response.status_code < 300
    except Exception:
        return False


def send_password_reset_email(to_email, reset_url):
    """
    Returns True if Resend accepted the email for delivery, False on
    any failure -- including simply not being configured. Never raises:
    a failed reset email shouldn't turn into a 500 on the request that
    triggered it, since from the caller's side the reset token was
    already created successfully either way.
    """
    return _send(
        to_email,
        "Reset your Loom password",
        "<p>Someone asked to reset the password on this Loom account.</p>"
        f'<p><a href="{reset_url}">Click here to set a new password</a>. '
        "This link works for 1 hour and only once.</p>"
        "<p>If this wasn't you, you can ignore this email -- your password hasn't changed.</p>",
    )


def send_verification_email(to_email, verify_url):
    """
    Same contract as send_password_reset_email: True if accepted for
    delivery, False on any failure (including not being configured),
    never raises.
    """
    return _send(
        to_email,
        "Confirm your email for Loom",
        "<p>Welcome to Loom -- click below to confirm this is your email address.</p>"
        f'<p><a href="{verify_url}">Confirm my email</a>. This link works for 24 hours.</p>'
        "<p>If you didn't create a Loom account, you can ignore this email.</p>",
    )
