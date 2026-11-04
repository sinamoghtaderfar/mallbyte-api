import hashlib
import secrets
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone


class AdminMFADevice(models.Model):
    """Server-side MFA state for privileged accounts. TOTP secrets are encrypted."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="admin_mfa"
    )
    encrypted_secret = models.TextField()
    enabled = models.BooleanField(default=False)
    last_counter = models.BigIntegerField(default=-1)
    recovery_codes = models.JSONField(default=list, blank=True)
    session_version = models.CharField(max_length=64, default=secrets.token_hex, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class AdminMFAChallenge(models.Model):
    """A short-lived, single-use first-factor challenge, never a bearer API token."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="mfa_challenges"
    )
    token_hash = models.CharField(max_length=64, unique=True, editable=False)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    password_confirmed = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    @classmethod
    def issue(cls, user):
        token = secrets.token_urlsafe(32)
        cls.objects.create(
            user=user,
            token_hash=hashlib.sha256(token.encode("utf-8")).hexdigest(),
            expires_at=timezone.now() + timedelta(minutes=5),
        )
        return token
