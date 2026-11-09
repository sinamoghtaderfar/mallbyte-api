import hashlib
import secrets
from datetime import timedelta

from django.conf import settings
from django.db import models, router, transaction
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

    @classmethod
    def from_db(cls, db, field_names, values):
        instance = super().from_db(db, field_names, values)
        instance._loaded_security_state = {name: value for name, value in zip(field_names, values, strict=True) if name in {"encrypted_secret", "enabled"}}
        return instance

    def save(self, *args, **kwargs):
        update_fields = kwargs.get("update_fields")
        security_fields = {"encrypted_secret", "enabled"}
        if self._state.adding:
            result = super().save(*args, **kwargs)
            self._loaded_security_state = {field: getattr(self, field) for field in security_fields if field not in self.get_deferred_fields()}
            return result
        if update_fields is not None and not security_fields.intersection(update_fields):
            return super().save(*args, **kwargs)
        database = kwargs.get("using") or router.db_for_write(type(self), instance=self)
        with transaction.atomic(using=database):
            previous = type(self).objects.using(database).select_for_update().filter(pk=self.pk).values(*security_fields, "session_version").first()
            if previous is not None:
                relevant = security_fields if update_fields is None else security_fields.intersection(update_fields)
                loaded = getattr(self, "_loaded_security_state", {})
                changed = False
                for field in relevant:
                    explicitly_changed = field in loaded and getattr(self, field) != loaded[field]
                    if field not in loaded and update_fields is not None and field not in self.get_deferred_fields():
                        explicitly_changed = True
                    if explicitly_changed:
                        changed = changed or previous[field] != getattr(self, field)
                    else:
                        setattr(self, field, previous[field])
                self.session_version = secrets.token_hex() if changed else previous["session_version"]
                if changed and update_fields is not None:
                    kwargs["update_fields"] = set(update_fields) | {"session_version"}
            result = super().save(*args, **kwargs)
            self._loaded_security_state = {field: getattr(self, field) for field in security_fields if field not in self.get_deferred_fields()}
            return result


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
        # The full opaque value is hashed below. Binding its prefix to the
        # security epoch invalidates pending first factors after session
        # revocation without changing the database schema.
        token = f"{user.auth_version}.{secrets.token_urlsafe(32)}"
        cls.objects.create(
            user=user,
            token_hash=hashlib.sha256(token.encode("utf-8")).hexdigest(),
            expires_at=timezone.now() + timedelta(minutes=5),
        )
        return token
