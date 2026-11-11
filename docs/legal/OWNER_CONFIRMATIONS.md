# Privacy Policy and Terms of Service: what the owner must confirm before merging

The pages (`privacy.html`, `terms.html`) were written from what the code does (see the audit below). They are a
good-faith plain-language draft, not legal advice. Please confirm or change each item below; have a lawyer review if you can.

## Please confirm
1. **Contact address.** Both pages use `support@loominous.org`, which the app already shows in Settings > Support.
   Cloudflare's DNS page reports no MX record for loominous.org, so mail to this address may not be received.
   Set up receiving (for example Cloudflare Email Routing) or give me another address.
2. **Who operates Loominous.** The pages say only "Loominous". If you want a name or business entity and location, give it to me.
3. **Statements that are commitments.** "We do not use your dreams to advertise to you or sell your data" and "Loominous does not
   use advertising or analytics trackers" are true of the current code. Keep them only if you intend to.
4. **Age.** The Terms say users must be old enough to enter an agreement where they live; the Privacy Policy says the app is not
   designed for young children. If you want a specific minimum age (for example 13 or 16), tell me.
5. **Backups.** The policy says encrypted backups may keep deleted data until replaced. No period is stated. Confirm that is accurate
   (your Nov 9 backup is an example) or give a period.
6. **Provider retention.** The policy says providers keep data under their own policies. Check each provider's account settings
   (for example Anthropic and Voyage data-retention or zero-retention options) if you want to promise more.
7. **Governing law, liability limits, dispute terms.** Deliberately not included; add only with legal advice.
8. **Logs.** Render keeps structured logs; the code was not found to log dream text. Confirm Render's log retention if you want to state it.
9. **Language and regions.** If you expect users in the EU, UK or California, a lawyer should check the rights, legal-basis and
   transfer wording those laws require.
10. **Date.** "Last updated 11 November 2026" is the draft date; change when you approve.

## What the audit found (from the code)
- Stored in Turso: username, optional email, salted password hash, dreams and AI readings and extracted tags, profile fields, symbol chats,
  personal meanings, Discovery feedback; Google identity (subject id, verified email) only if Google sign-in is used.
- Sent to Anthropic (Claude): dream text and relevant profile details. Sent to Voyage AI: dream text for embeddings.
  Pinecone stores the embedding plus user and dream ids only (no text).
- Resend: verification and password-reset emails. Google Fonts: loaded by the page. No analytics or ad scripts; no cookies except a short
  OAuth binding cookie during Google sign-in; sign-in token and username kept in localStorage (token lifetime 30 days).
- Deleting a dream removes its Pinecone vector; deleting the account removes dreams, profile, chats, meanings, feedback, sign-in links and
  the user row, and the Pinecone vectors. There is no undo. Backups are not touched by deletion.
