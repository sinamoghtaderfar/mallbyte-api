# Email ownership and provisional accounts

Apply migration `accounts.0016_user_auth_version` before deploying these views.
Every existing JWT must be replaced by a fresh login: legacy tokens have no
security version and are rejected even if their account is subsequently verified.

Registration now returns HTTP 201 with `verification_required: true` and a user
summary. It does not return an access token or set a refresh cookie. The frontend
must request/verify email OTP before opening an authenticated account session.

Passwords selected before email ownership is proved are provisional. The first
OTP claim of an existing unverified nonprivileged account removes that password
and invalidates its previous tokens. The email owner may establish a new password
through the email OTP password-reset flow. Subsequent OTP logins for already
verified accounts preserve their established password. Existing privileged
accounts retain their password for mandatory MFA enrollment.

Data created by legacy provisional accounts is retained; review any suspicious
legacy business records separately. A formerly verified account with a
compromised password still requires normal recovery; verification provenance
cannot be reconstructed from historic records.

Logout revokes all sessions for the account identified by a valid refresh cookie
or Bearer access token. Password reset/change and saved identity, privilege or
activation changes also invalidate both access and refresh JWTs. After changing
a password, the frontend must clear the old session and sign in again. This
includes passwords changed through Django admin. Role permissions are checked
separately on each request and have their own cache invalidation.
