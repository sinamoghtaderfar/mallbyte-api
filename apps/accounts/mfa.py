"""Privileged account second-factor helpers (RFC 6238 TOTP)."""

import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote

from cryptography.fernet import Fernet
from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from rest_framework_simplejwt.tokens import RefreshToken

from .mfa_models import AdminMFADevice


def is_privileged(user):
    return bool(user and (user.is_staff or user.is_superuser))


def _cipher():
    # Deployments MUST set a stable MFA_FERNET_KEY independent of SECRET_KEY.
    configured = getattr(settings, "MFA_FERNET_KEY", None)
    if configured:
        return Fernet(configured.encode("ascii"))
    if not settings.DEBUG:
        raise RuntimeError("MFA_FERNET_KEY must be configured in production")
    derived = hashlib.sha256((settings.SECRET_KEY + ":mallbyte-admin-mfa").encode()).digest()
    return Fernet(base64.urlsafe_b64encode(derived))


def encrypt_secret(secret):
    return _cipher().encrypt(secret.encode("ascii")).decode("ascii")


def decrypt_secret(encrypted):
    return _cipher().decrypt(encrypted.encode("ascii")).decode("ascii")


def new_secret():
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")


def provisioning_uri(user, secret):
    issuer = "MallByte"
    account = quote(f"{issuer}:{user.email}", safe="")
    return f"otpauth://totp/{account}?secret={secret}&issuer={quote(issuer)}&digits=6&period=30"


def _totp(secret, counter):
    key = base64.b32decode(secret + "=" * (-len(secret) % 8))
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 15
    value = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return f"{value % 1000000:06d}"


def match_totp(secret, code, last_counter=-1):
    if not isinstance(code, str) or len(code) != 6 or not code.isascii() or not code.isdigit():
        return None
    counter = int(time.time()) // 30
    for delta in (-1, 0, 1):
        candidate = counter + delta
        if candidate > last_counter and hmac.compare_digest(_totp(secret, candidate), code):
            return candidate
    return None


def new_recovery_codes():
    codes = [secrets.token_hex(6).upper() for _ in range(10)]
    return codes, [make_password(code) for code in codes]


def consume_recovery_code(device, candidate):
    normalized = str(candidate).strip().replace("-", "").upper()
    if len(normalized) != 12 or not all(c in "0123456789ABCDEF" for c in normalized):
        return False
    for index, encoded in enumerate(device.recovery_codes):
        if check_password(normalized, encoded):
            device.recovery_codes.pop(index)
            return True
    return False


def issue_privileged_tokens(user, device):
    if not (device.enabled and is_privileged(user)):
        raise ValueError("MFA enrollment required")
    refresh = RefreshToken.for_user(user)
    refresh["mfa"] = True
    refresh["mfa_version"] = device.session_version
    return refresh


def privileged_token_valid(user, token):
    if not is_privileged(user):
        return True
    if not token.get("mfa"):
        return False
    device = AdminMFADevice.objects.filter(user=user, enabled=True).first()
    return bool(device and token.get("mfa_version") == device.session_version)
