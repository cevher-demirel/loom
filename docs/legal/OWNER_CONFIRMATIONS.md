# Privacy Policy and Terms of Service: what the owner must confirm before merging

The pages (`privacy.html`, `terms.html`) were written from what the code does (see the audit below). They are a
good-faith plain-language draft, not legal advice. Please confirm or change each item below; have a lawyer review if you can.

## Status after the 11 November review
- **Done:** support@loominous.org forwards (Cloudflare Email Routing) to the approved mailbox; apex MX and SPF plus the Cloudflare DKIM record were
  added. Existing Resend records (send, rsend, resend._domainkey) were not changed. Actual delivery still needs one real test mail.
- **Done:** commitments (no selling dream data, no use of dreams for advertising, no advertising trackers) are now explicit in the Privacy Policy.
- **Done:** minimum age 16 in Terms and Privacy Policy.
- **Done:** backup wording now says backups kept by the database provider may hold deleted data until they expire (no period promised,
  and "encrypted" removed because it was not verified). Deletion code checked: it does not touch backups.
- **Done:** Anthropic retention sentence added (API inputs and outputs deleted within 30 days, limited exceptions, per Anthropic).
  Voyage AI, Pinecone, Resend, Turso and Render retention were NOT verified; the policy defers to their own policies.
- **Done:** public about page (`about.html`) describing the app and linking the policy and terms.

## Still needed from the owner
1. **Operator.** The pages say "operated by a business entity". Provide the legal name and country, then use:
   "Loominous is operated by <legal name>, a <company type> registered in <country>."
2. **Homepage for Google.** loominous.org currently opens the login screen. Google requires a homepage that describes the app and is not
   only a login page. Options: (a) show a short public intro above the login for signed-out visitors, (b) make about.html the root and move
   the app to /app. Not changed, since it affects the approved login design.
3. **Google Search Console** domain verification for loominous.org, and the same privacy URL on the consent screen.
4. Governing law, liability limits and dispute terms are deliberately omitted; add only with legal advice.
5. EU/UK/California users: a lawyer should check required rights and transfer wording.
6. Date "Last updated 11 November 2026" is a draft date.

## What the audit found (from the code)
- Stored in Turso: username, optional email, salted password hash, dreams and AI readings and extracted tags, profile fields, symbol chats,
  personal meanings, Discovery feedback; Google identity (subject id, verified email) only if Google sign-in is used.
- Sent to Anthropic (Claude): dream text and relevant profile details. Sent to Voyage AI: dream text for embeddings.
  Pinecone stores the embedding plus user and dream ids only (no text).
- Resend: verification and password-reset emails. Google Fonts: loaded by the page. No analytics or ad scripts; no cookies except a short
  OAuth binding cookie during Google sign-in; sign-in token and username kept in localStorage (token lifetime 30 days).
- Deleting a dream removes its Pinecone vector; deleting the account removes dreams, profile, chats, meanings, feedback, sign-in links and
  the user row, and the Pinecone vectors. There is no undo. Backups are not touched by deletion.
