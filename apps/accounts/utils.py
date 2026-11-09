import hashlib
import hmac
import secrets

from django.core.cache import cache


def generate_email_verification_token(user, email=None):
    """Bind proof to a destination and the current account security version."""
    token = secrets.token_urlsafe(32)
    cache.set(f"email_verify_{user.pk}", {
        "token_hash": hashlib.sha256(token.encode()).hexdigest(),
        "email": (email or user.email).strip().lower(),
        "auth_version": user.auth_version,
    }, timeout=3600)
    return token


def pending_email_for_token(user, token):
    pending = cache.get(f"email_verify_{user.pk}")
    if not isinstance(pending, dict) or pending.get("auth_version") != user.auth_version:
        return None
    digest = hashlib.sha256(str(token).encode()).hexdigest()
    if not hmac.compare_digest(pending.get("token_hash", ""), digest):
        return None
    return pending.get("email")


def verify_email_token(user, token):
    return bool(pending_email_for_token(user, token))


def clear_email_verification_token(user):
    cache.delete(f"email_verify_{user.pk}")
