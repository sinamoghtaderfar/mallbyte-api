# Privileged MFA — rollout and recovery

The Next.js admin console uses email OTP as the **first factor** and TOTP as the **second factor**. Privileged includes all `is_staff` and `is_superuser` users.

## Deployment prerequisites

1. Deploy the Backend and Frontend MFA changes **together** in staging before a production rollout.
2. Configure a stable, separately backed-up `MFA_FERNET_KEY` in production. Generate one securely on the target host:
   ```sh
   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
   ```
   Keep this key only in a secrets manager; **never commit it**, log it or regenerate it on a restart. Losing it makes existing authenticator enrollments undecipherable.
3. Run `python manage.py migrate` before issuing privileged login challenges.
4. Ensure server clocks are synchronized (TOTP uses 30-second steps).
5. Complete staged account enrollment before opening privileged operations.

## First privileged login

1. Request email OTP at `/api/auth/otp/request/`.
2. Verify at `/api/auth/otp/verify/`: privileged users receive `{mfa_required:true,challenge,mfa_enrolled:false}`, **not a JWT**.
3. Verify the existing admin password at `/api/auth/mfa/setup/` using the 5-minute challenge.
4. Add the returned secret to a TOTP authenticator (manual secret entry).
5. Verify its current 6-digit code at `/api/auth/mfa/complete/`; store the **ten single-use recovery codes** in a password manager. Never store them in the app.
6. Subsequent logins use `/api/auth/mfa/verify/` after email OTP, supplying either a TOTP or an unused recovery code.

A challenge expires after five minutes, permits at most five attempts and is consumed on success. Replayed TOTP steps are rejected.

## Session enforcement

- Privileged access and refresh JWTs carry `mfa=true` and the current MFA session version.
- APIs reject privileged JWTs without those claims or a matching enabled MFA device.
- Password-only token login is blocked for staff and superusers.
- Legacy privileged tokens become invalid as soon as the deployment switches authentication classes.

## Django Admin

The password-only Django admin endpoint is **disabled in production** (`DJANGO_ADMIN_ENABLED=False`). It remains available in development for maintenance, but is **not** MFA-protected. A separate session-based MFA integration is required before production Django Admin is re-enabled.

## Recovery policy

- If a device is lost, sign in with an unused recovery code after email OTP.
- There is deliberately **no public self-service MFA reset** or bypass.
- Emergency reset must follow a documented, human-approved identity verification process, be performed by an authorized operator, and be audit logged.
- Restore a backed-up Fernet key along with the database in disaster recovery.
- Verify MFA is not bypassed by direct password JWT login, refresh cookies, or old tokens.

This module does not implement WebAuthn/passkeys, device revocation UI, or a production Django Admin MFA login form.
