# Revoke pending MFA first factors after account security events

An MFA first-factor challenge must not outlive the account security epoch in
which its email/password proof was accepted. Previously a pending challenge,
including a password-confirmed enrollment, could still complete after logout or
password recovery and issue new JWTs with the newer account epoch.

New challenges are opaque strings containing the current `auth_version` and a
cryptographically random nonce. The database stores only the SHA-256 hash of the
entire string. Verification first resolves that hash and compares the bound epoch
with the current user while locking both the challenge and its related user.
Changing the visible epoch prefix cannot upgrade a challenge because it changes
the stored-hash lookup. A stale user instance can only issue a challenge that is
rejected; it cannot restore an earlier security epoch.

A concurrent security event either commits before the check, causing rejection,
or commits after MFA issuance and revokes the issued session through the existing
JWT epoch guard. No schema migration is needed. Deploy with the session-revocation
change. Legacy unversioned pending challenges are rejected after rollout; they
expire after five minutes in any event. Already-issued sessions follow the
existing JWT revocation policy.

The API contract remains an opaque `challenge` string. Frontends should send it
unchanged and restart the OTP first factor when it expires or becomes invalid.
Do not persist or parse its internal format. No MFA UI or production Django admin
configuration is changed.
