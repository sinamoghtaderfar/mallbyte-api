import hashlib
import secrets
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from datetime import timedelta
from threading import Event
from unittest import skipUnless
from unittest.mock import patch

from django.core.cache import cache
from django.db import close_old_connections, connection, connections, transaction
from django.test import TransactionTestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from apps.accounts.cookies import get_refresh_cookie_name
from apps.accounts.mfa import _totp, encrypt_secret, issue_privileged_tokens, new_secret
from apps.accounts.mfa_models import AdminMFAChallenge, AdminMFADevice
from apps.accounts.models import OTP, User


@override_settings(MFA_FERNET_KEY="AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=")
class MFAChallengeRevocationTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.admin = User.objects.create_superuser(email="admin@example.com", password="OriginalPass123!", email_verified=True)
        self.secret = new_secret()
        self.device = AdminMFADevice.objects.create(user=self.admin, encrypted_secret=encrypt_secret(self.secret), enabled=True)

    def verify(self, challenge):
        return self.client.post("/api/auth/mfa/verify/", {"challenge": challenge, "code": _totp(self.secret, int(time.time()) // 30)}, format="json")

    def reset_password(self):
        otp = OTP.generate_otp(self.admin.email)
        response = self.client.post("/api/auth/password-reset/verify/", {
            "email": self.admin.email, "code": otp.code, "new_password": "RecoveredPass123!",
        }, format="json")
        self.assertEqual(response.status_code, 200, response.data)

    def assert_rejected(self, response):
        self.assertEqual(response.status_code, 400, response.data)
        self.assertNotIn("access", response.data)
        self.assertNotIn(get_refresh_cookie_name(), response.cookies)

    def test_unchanged_epoch_can_complete_mfa_normally(self):
        response = self.verify(AdminMFAChallenge.issue(self.admin))
        self.assertEqual(response.status_code, 200, response.data)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {response.data['access']}")
        self.assertEqual(self.client.get("/api/auth/profile/").status_code, 200)

    def test_pending_first_factor_is_revoked_by_cookie_logout(self):
        challenge = AdminMFAChallenge.issue(self.admin)
        self.client.cookies[get_refresh_cookie_name()] = str(issue_privileged_tokens(self.admin, self.device))
        self.assertEqual(self.client.post("/api/auth/logout/").status_code, 200)
        self.assert_rejected(self.verify(challenge))

    def test_pending_first_factor_is_revoked_by_password_change(self):
        challenge = AdminMFAChallenge.issue(self.admin)
        token = issue_privileged_tokens(self.admin, self.device)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.access_token}")
        response = self.client.post("/api/auth/change-password/", {
            "old_password": "OriginalPass123!", "new_password": "ChangedPass123!", "confirm_password": "ChangedPass123!",
        }, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.client.credentials()
        self.assert_rejected(self.verify(challenge))

    def test_pending_first_factor_is_revoked_by_password_recovery(self):
        challenge = AdminMFAChallenge.issue(self.admin)
        self.reset_password()
        self.assert_rejected(self.verify(challenge))

    def test_password_confirmed_enrollment_is_revoked_by_password_recovery(self):
        self.device.enabled = False
        self.device.save(update_fields=["enabled"])
        challenge = AdminMFAChallenge.issue(self.admin)
        response = self.client.post("/api/auth/mfa/setup/", {"challenge": challenge, "password": "OriginalPass123!"}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        secret = response.data["secret"]
        self.reset_password()
        response = self.client.post("/api/auth/mfa/complete/", {"challenge": challenge, "code": _totp(secret, int(time.time()) // 30)}, format="json")
        self.assert_rejected(response)
        self.device.refresh_from_db()
        self.assertFalse(self.device.enabled)

    def test_stale_account_instance_cannot_issue_a_valid_new_first_factor(self):
        stale = User.objects.get(pk=self.admin.pk)
        self.admin.invalidate_sessions()
        self.assert_rejected(self.verify(AdminMFAChallenge.issue(stale)))

    def test_legacy_unversioned_first_factors_are_invalidated(self):
        raw = secrets.token_urlsafe(32)
        AdminMFAChallenge.objects.create(user=self.admin, token_hash=hashlib.sha256(raw.encode()).hexdigest(), expires_at=timezone.now() + timedelta(minutes=5))
        self.assert_rejected(self.verify(raw))

    def test_changing_the_epoch_prefix_cannot_upgrade_an_old_challenge(self):
        challenge = AdminMFAChallenge.issue(self.admin)
        self.admin.invalidate_sessions()
        forged = f"{self.admin.auth_version}.{challenge.partition('.')[2]}"
        self.assert_rejected(self.verify(forged))


@skipUnless(connection.vendor == "postgresql", "PostgreSQL row-lock semantics required")
@override_settings(MFA_FERNET_KEY="AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=")
class MFAChallengeSecurityEventConcurrencyTests(TransactionTestCase):
    def test_verification_waits_for_security_change_and_rejects_the_old_epoch(self):
        cache.clear()
        admin = User.objects.create_superuser(email="admin@example.com", password="OriginalPass123!", email_verified=True)
        secret = new_secret()
        AdminMFADevice.objects.create(user=admin, encrypted_secret=encrypt_secret(secret), enabled=True)
        challenge = AdminMFAChallenge.issue(admin)
        security_written = Event()
        release_security = Event()
        verification_started = Event()
        from apps.accounts.mfa_views import _get_challenge

        def password_change():
            close_old_connections()
            try:
                with transaction.atomic():
                    actor = User.objects.select_for_update().get(pk=admin.pk)
                    actor.set_password("ChangedPass123!")
                    actor.save(update_fields=["password"])
                    security_written.set()
                    if not release_security.wait(timeout=10):
                        raise AssertionError("Security change was not released")
            finally:
                connections.close_all()

        def observed_challenge(raw):
            verification_started.set()
            return _get_challenge(raw)

        def verify():
            close_old_connections()
            try:
                return APIClient().post("/api/auth/mfa/verify/", {"challenge": challenge, "code": _totp(secret, int(time.time()) // 30)}, format="json").status_code
            finally:
                connections.close_all()

        with patch("apps.accounts.mfa_views._get_challenge", observed_challenge), ThreadPoolExecutor(max_workers=2) as executor:
            changing = executor.submit(password_change)
            self.assertTrue(security_written.wait(timeout=10))
            verifying = executor.submit(verify)
            self.assertTrue(verification_started.wait(timeout=10))
            try:
                with self.assertRaises(TimeoutError):
                    verifying.result(timeout=0.25)
            finally:
                release_security.set()
            changing.result(timeout=10)
            self.assertEqual(verifying.result(timeout=10), 400)
