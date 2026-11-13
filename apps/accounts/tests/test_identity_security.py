from django.core.cache import cache
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.cookies import get_refresh_cookie_name
from apps.accounts.models import OTP, User


class AccountOwnershipSecurityTests(APITestCase):
    def setUp(self):
        cache.clear()

    def password_login(self, email, password="AttackerPass123!"):
        return self.client.post("/api/auth/token/", {"email": email, "password": password}, format="json")

    def verify(self, user):
        otp = OTP.generate_otp(user.email)
        return self.client.post("/api/auth/otp/verify/", {"email": user.email, "code": otp.code}, format="json")

    def test_registration_does_not_authorize_unproved_email(self):
        result = self.client.post("/api/auth/register/", {
            "email": "owner@example.com", "full_name": "Provisional",
            "password": "AttackerPass123!", "password2": "AttackerPass123!",
        }, format="json")
        self.assertEqual(result.status_code, 201, result.data)
        self.assertTrue(result.data["verification_required"])
        self.assertNotIn("access", result.data)
        self.assertNotIn(get_refresh_cookie_name(), result.cookies)
        self.assertEqual(self.password_login("owner@example.com").status_code, 401)

    def test_owner_claim_invalidates_provisional_password_and_existing_tokens(self):
        user = User.objects.create_user(email="legacy@example.com", password="AttackerPass123!")
        old_refresh = RefreshToken.for_user(user)
        old_refresh["auth_version"] = user.auth_version
        legacy_refresh = RefreshToken.for_user(user)
        old_access = str(old_refresh.access_token)

        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {old_access}")
        self.assertEqual(self.client.get("/api/auth/profile/").status_code, 401)
        self.client.credentials()
        result = self.verify(user)
        self.assertEqual(result.status_code, 200, result.data)
        user.refresh_from_db()
        self.assertTrue(user.email_verified)
        self.assertFalse(user.has_usable_password())
        self.assertEqual(self.password_login(user.email).status_code, 401)

        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {old_access}")
        self.assertEqual(self.client.get("/api/auth/profile/").status_code, 401)
        self.client.credentials()
        for token in (old_refresh, legacy_refresh):
            self.client.cookies[get_refresh_cookie_name()] = str(token)
            self.assertEqual(self.client.post("/api/auth/token/refresh/").status_code, 401)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {result.data['access']}")
        self.assertEqual(self.client.get("/api/auth/profile/").status_code, 200)

    def test_verified_password_login_issues_versioned_usable_session(self):
        user = User.objects.create_user(email="verified@example.com", password="AttackerPass123!", email_verified=True)
        result = self.password_login(user.email)
        self.assertEqual(result.status_code, 200, result.data)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {result.data['access']}")
        self.assertEqual(self.client.get("/api/auth/profile/").status_code, 200)

    def test_existing_verified_password_survives_normal_otp_login(self):
        user = User.objects.create_user(email="existing@example.com", password="AttackerPass123!", email_verified=True)
        self.assertEqual(self.verify(user).status_code, 200)
        user.refresh_from_db()
        self.assertTrue(user.check_password("AttackerPass123!"))
