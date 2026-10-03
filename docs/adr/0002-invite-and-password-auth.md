# 0002 — Invite links and passwords, no external identity provider

- **Status:** accepted · 2026-09-23 (supersedes an earlier Microsoft Entra design)

## Context
Members have Comillas Microsoft accounts, but the team has no access to the university tenant and doesn't want to depend on it. Email sending is not available yet (the domain is migrating). The app holds quiz scores, not sensitive data, so the security bar is "solid and simple", not "enterprise".

## Decision
- Sign-up only through a single-use invite link created by an admin (7-day expiry); the invite is the approval.
- The member picks an email (login identifier, visible to admins only), a display name and a password.
- Passwords are hashed with Argon2id (argon2-cffi), minimum 10 characters, common passwords rejected, rehashed when parameters change, never logged.
- Brute force is limited at Nginx (`limit_req` on `/auth/`) and per account (5 failures → 15-minute lock).
- Forgotten passwords: an admin issues a single-use reset link (24 h). No email needed.
- Sessions are opaque random IDs in a `__Host-` cookie (HttpOnly, Secure, SameSite=Lax); only a hash is stored; 12 h idle / 30 d absolute; rotated at login. Local development over plain http uses a `sid` cookie without Secure, since Safari refuses Secure cookies on http://localhost; deployed environments must be https.

## Consequences
- The app stores password hashes, so it owns their protection (above). Admin TOTP can be added later.
- No dependency on the university, Google or an email provider.
- Onboarding needs an admin to send invites; acceptable for a team of this size.
