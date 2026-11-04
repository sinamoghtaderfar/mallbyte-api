import time

from django.test import override_settings
from django.core.cache import cache
from rest_framework import status
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.cookies import get_refresh_cookie_name
from apps.accounts.mfa import _totp, decrypt_secret, new_secret
from apps.accounts.mfa_models import AdminMFADevice
from apps.accounts.models import OTP, User


class PrivilegedMFATests(APITestCase):
    def setUp(self):
        cache.clear()
        self.admin = User.objects.create_superuser(
            email="mfa-admin@example.com", full_name="Admin",
            password="AdminPass123!",
        )
        self.buyer = User.objects.create_user(
            email="mfa-buyer@example.com", full_name="Buyer",
            password="BuyerPass123!",
        )

    def begin(self):
        otp = OTP.generate_otp(email=self.admin.email)
        response = self.client.post(
            "/api/auth/otp/verify/",
            {"email": self.admin.email, "code": otp.code},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertTrue(response.data["mfa_required"])
        self.assertNotIn("access", response.data)
        self.assertNotIn(get_refresh_cookie_name(), response.cookies)
        return response.data

    def setup(self, challenge):
        response = self.client.post(
            "/api/auth/mfa/setup/",
            {"challenge": challenge, "password": "AdminPass123!"},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        return response.data

    def complete(self, challenge, secret):
        response = self.client.post(
            "/api/auth/mfa/complete/",
            {"challenge": challenge, "code": _totp(secret, int(time.time()) // 30)},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        return response

    def test_first_factor_does_not_issue_privileged_session_and_setup_requires_password(self):
        challenge = self.begin()["challenge"]
        invalid = self.client.post("/api/auth/mfa/setup/", {
            "challenge": challenge, "password": "wrong",
        }, format="json")
        self.assertEqual(invalid.status_code, 400)
        setup = self.setup(challenge)
        self.assertTrue(setup["otpauth_uri"].startswith("otpauth://totp/"))
        device = AdminMFADevice.objects.get(user=self.admin)
        self.assertFalse(device.enabled)
        self.assertNotIn(setup["secret"], device.encrypted_secret)
        self.assertEqual(decrypt_secret(device.encrypted_secret), setup["secret"])
        response = self.complete(challenge, setup["secret"])
        self.assertIn("access", response.data)
        self.assertEqual(len(response.data["recovery_codes"]), 10)
        self.assertIn(get_refresh_cookie_name(), response.cookies)

    def test_challenge_one_time_and_totp_replay_protection(self):
        first = self.begin()
        setup = self.setup(first["challenge"])
        completed = self.complete(first["challenge"], setup["secret"])
        duplicate = self.client.post("/api/auth/mfa/complete/", {
            "challenge": first["challenge"], "code": _totp(setup["secret"], int(time.time()) // 30),
        }, format="json")
        self.assertEqual(duplicate.status_code, 400)

        enrolled = self.begin()
        self.assertTrue(enrolled["mfa_enrolled"])
        repeated = self.client.post("/api/auth/mfa/verify/", {
            "challenge": enrolled["challenge"], "code": _totp(setup["secret"], int(time.time()) // 30),
        }, format="json")
        self.assertEqual(repeated.status_code, 400)
        self.assertIn("access", completed.data)

    def test_recovery_code_is_single_use(self):
        first = self.begin()
        secret = self.setup(first["challenge"])["secret"]
        response = self.complete(first["challenge"], secret)
        code = response.data["recovery_codes"][0]
        other = self.begin()["challenge"]
        recovered = self.client.post("/api/auth/mfa/verify/", {
            "challenge": other, "code": code,
        }, format="json")
        self.assertEqual(recovered.status_code, 200, recovered.data)
        fresh = self.begin()["challenge"]
        duplicate = self.client.post("/api/auth/mfa/verify/", {
            "challenge": fresh, "code": code,
        }, format="json")
        self.assertEqual(duplicate.status_code, 400)

    def test_legacy_privileged_access_and_refresh_tokens_are_rejected(self):
        refresh = RefreshToken.for_user(self.admin)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")
        response = self.client.get("/api/auth/profile/")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.client.credentials()
        self.client.cookies[get_refresh_cookie_name()] = str(refresh)
        renewed = self.client.post("/api/auth/token/refresh/")
        self.assertEqual(renewed.status_code, 401)

    def test_successful_mfa_token_can_access_and_refresh_privileged_session(self):
        first = self.begin()
        secret = self.setup(first["challenge"])["secret"]
        result = self.complete(first["challenge"], secret)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {result.data['access']}")
        self.assertEqual(self.client.get("/api/auth/profile/").status_code, 200)
        self.client.credentials()
        self.client.cookies[get_refresh_cookie_name()] = result.cookies[get_refresh_cookie_name()].value
        self.assertEqual(self.client.post("/api/auth/token/refresh/").status_code, 200)

    def test_staff_and_superuser_password_only_api_login_is_blocked(self):
        res = self.client.post("/api/auth/token/", {
            "email": self.admin.email, "password": "AdminPass123!",
        }, format="json")
        self.assertEqual(res.status_code, 403)
        self.assertNotIn("access", res.data)

    def test_regular_customer_email_otp_login_unchanged(self):
        otp = OTP.generate_otp(email=self.buyer.email)
        response = self.client.post("/api/auth/otp/verify/", {
            "email": self.buyer.email, "code": otp.code,
        }, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertIn("access", response.data)
        self.assertNotIn("mfa_required", response.data)

    def test_invalid_codes_expire_challenge_after_five_attempts(self):
        first = self.begin()
        self.setup(first["challenge"])
        for _ in range(5):
            response = self.client.post("/api/auth/mfa/complete/", {
                "challenge": first["challenge"], "code": "000000",
            }, format="json")
            self.assertEqual(response.status_code, 400)
        locked = self.client.post("/api/auth/mfa/complete/", {
            "challenge": first["challenge"], "code": "123456",
        }, format="json")
        self.assertEqual(locked.status_code, 400)

    def test_encrypted_secret_key_is_required_in_production(self):
        with override_settings(DEBUG=False, MFA_FERNET_KEY=None):
            with self.assertRaises(RuntimeError):
                decrypt_secret("invalid")
