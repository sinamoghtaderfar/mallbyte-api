from django.core.cache import cache
from rest_framework.test import APITestCase

from apps.accounts.auth_tokens import issue_user_tokens
from apps.accounts.cookies import get_refresh_cookie_name
from apps.accounts.mfa import issue_privileged_tokens
from apps.accounts.mfa_models import AdminMFADevice
from apps.accounts.models import OTP, User


class SessionRevocationTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(email="session@example.com", password="OriginalPass123!", email_verified=True)
        self.refresh = issue_user_tokens(self.user)
        self.access = str(self.refresh.access_token)

    def assert_revoked(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.access}")
        self.assertEqual(self.client.get("/api/auth/profile/").status_code, 401)
        self.client.credentials()
        self.client.cookies[get_refresh_cookie_name()] = str(self.refresh)
        self.assertEqual(self.client.post("/api/auth/token/refresh/").status_code, 401)

    def test_cookie_logout_revokes_copied_access_and_refresh(self):
        self.client.cookies[get_refresh_cookie_name()] = str(self.refresh)
        self.assertEqual(self.client.post("/api/auth/logout/").status_code, 200)
        self.assert_revoked()

    def test_bearer_logout_revokes_sessions(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.access}")
        self.assertEqual(self.client.post("/api/auth/logout/").status_code, 200)
        self.assert_revoked()

    def test_invalid_logout_token_still_clears_cookie(self):
        self.client.credentials(HTTP_AUTHORIZATION="Bearer invalid")
        result = self.client.post("/api/auth/logout/")
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.cookies[get_refresh_cookie_name()]["max-age"], 0)

    def test_password_reset_revokes_existing_sessions(self):
        otp = OTP.generate_otp(self.user.email)
        result = self.client.post("/api/auth/password-reset/verify/", {
            "email": self.user.email, "code": otp.code, "new_password": "RecoveredPass123!",
        }, format="json")
        self.assertEqual(result.status_code, 200, result.data)
        self.assert_revoked()

    def test_password_change_revokes_existing_sessions(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.access}")
        result = self.client.post("/api/auth/change-password/", {
            "old_password": "OriginalPass123!", "new_password": "ChangedPass123!", "confirm_password": "ChangedPass123!",
        }, format="json")
        self.assertEqual(result.status_code, 200, result.data)
        self.assert_revoked()

    def test_security_updates_through_model_save_revoke_sessions(self):
        for field, value in [("password", "!unusable"), ("email", "changed@example.com"), ("is_staff", True)]:
            with self.subTest(field=field):
                self.user.refresh_from_db()
                before = self.user.auth_version
                setattr(self.user, field, value)
                self.user.save(update_fields=[field])
                self.assertEqual(self.user.auth_version, before + 1)
        self.assert_revoked()

    def test_profile_only_save_does_not_restore_a_stale_version(self):
        stale = User.objects.get(pk=self.user.pk)
        self.user.invalidate_sessions()
        stale.full_name = "Updated name"
        stale.save()
        stale.refresh_from_db()
        self.assertEqual(stale.auth_version, self.user.auth_version)
        self.assert_revoked()

    def test_stale_full_profile_save_preserves_newer_password_and_identity(self):
        stale = User.objects.get(pk=self.user.pk)
        self.user.set_password("NewerSecretPass123!")
        self.user.email = "newer-owner@example.com"
        self.user.save(update_fields=["password", "email"])
        stale.full_name = "Updated profile"
        stale.save()
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("NewerSecretPass123!"))
        self.assertEqual(self.user.email, "newer-owner@example.com")
        self.assertEqual(self.user.full_name, "Updated profile")
        self.assert_revoked()

    def test_password_reset_can_establish_verified_password_for_provisional_account(self):
        provisional = User.objects.create_user(email="pending@example.com", password="UnprovedPass123!")
        otp = OTP.generate_otp(provisional.email)
        result = self.client.post("/api/auth/password-reset/verify/", {
            "email": provisional.email, "code": otp.code, "new_password": "OwnerSelectedPass123!",
        }, format="json")
        self.assertEqual(result.status_code, 200, result.data)
        result = self.client.post("/api/auth/token/", {"email": provisional.email, "password": "OwnerSelectedPass123!"}, format="json")
        self.assertEqual(result.status_code, 200, result.data)

    def test_mfa_device_security_change_revokes_privileged_session(self):
        self.user.is_staff = True
        self.user.save(update_fields=["is_staff"])
        device = AdminMFADevice.objects.create(user=self.user, encrypted_secret="test-secret", enabled=True)
        self.refresh = issue_privileged_tokens(self.user, device)
        self.access = str(self.refresh.access_token)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.access}")
        self.assertEqual(self.client.get("/api/auth/profile/").status_code, 200)
        device.encrypted_secret = "replacement-test-secret"
        device.save(update_fields=["encrypted_secret"])
        self.assert_revoked()

    def test_stale_device_full_save_preserves_newer_authenticator_secret(self):
        device = AdminMFADevice.objects.create(user=self.user, encrypted_secret="old-secret", enabled=True)
        stale = AdminMFADevice.objects.get(pk=device.pk)
        device.encrypted_secret = "new-secret"
        device.save(update_fields=["encrypted_secret"])
        expected_version = device.session_version
        stale.last_counter = 123
        stale.save()
        device.refresh_from_db()
        self.assertEqual(device.encrypted_secret, "new-secret")
        self.assertEqual(device.session_version, expected_version)
