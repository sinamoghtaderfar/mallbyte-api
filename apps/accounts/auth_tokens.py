"""JWT sessions are bound to a proved account identity and its security version."""

from rest_framework_simplejwt.tokens import RefreshToken


def issue_user_tokens(user):
    if not user.email_verified or not user.is_active or user.is_deleted:
        raise ValueError("A verified, active account is required.")
    refresh = RefreshToken.for_user(user)
    refresh["auth_version"] = user.auth_version
    return refresh


def identity_token_valid(user, token):
    return bool(
        user.email_verified
        and user.is_active
        and not user.is_deleted
        and token.get("auth_version") == user.auth_version
    )
