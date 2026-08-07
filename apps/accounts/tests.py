from datetime import timedelta
from unittest.mock import patch

from django.core import mail
from django.core.cache import cache
from django.test import override_settings
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from apps.accounts.models import OTP, Address, Profile, Seller, User
from apps.accounts.otp_delivery import mask_email, normalize_email, send_otp_email
from apps.accounts.utils import generate_email_verification_token

EMAIL_TEST_SETTINGS = {
    "EMAIL_BACKEND": "django.core.mail.backends.locmem.EmailBackend",
    "EMAIL_HOST_USER": "test-user",
    "EMAIL_HOST_PASSWORD": "test-password",
    "DEFAULT_FROM_EMAIL": "MallByte <no-reply@mallbyte.test>",
    "OTP_CODE_EXPIRY_SECONDS": 600,
    "OTP_EMAIL_SUBJECT": "Your MallByte verification code",
    "FRONTEND_URL": "http://localhost:3000",
}


class AccountsTestMixin:
    def create_user(
        self,
        *,
        email="user@example.com",
        phone=None,
        full_name="Test User",
        password="TestPass123!",
        is_staff=False,
        is_superuser=False,
        is_active=True,
        email_verified=False,
    ):
        user = User(
            email=email,
            phone=phone,
            full_name=full_name,
            is_staff=is_staff,
            is_superuser=is_superuser,
            is_active=is_active,
            email_verified=email_verified,
        )
        user.set_password(password)
        user.save()
        return user

    def create_admin(self):
        return self.create_user(
            email="admin@example.com",
            full_name="Admin User",
            password="AdminPass123!",
            is_staff=True,
            is_superuser=True,
            email_verified=True,
        )

    def authenticate(self, user):
        self.client.force_authenticate(user=user)

    def seller_payload(self, store_name="MallByte Store"):
        return {
            "store_name": store_name,
            "description": "A test seller store.",
            "business_phone": "+989121234567",
            "business_email": "seller-business@example.com",
            "website": "https://example.com",
            "bank_info": {
                "iban": "IR000000000000000000000000",
                "owner": "Seller Owner",
            },
            "documents": [
                "business-license.pdf",
            ],
        }

    def address_payload(self, title="Home"):
        return {
            "title": title,
            "province": "Tehran",
            "city": "Tehran",
            "street": "Valiasr",
            "alley": "Test Alley",
            "building_number": "10",
            "floor": "2",
            "unit": "4",
            "postal_code": "1234567890",
            "receiver_name": "Test Receiver",
            "receiver_phone": "09123456789",
            "is_default": False,
        }


class AccountsModelTestCase(AccountsTestMixin, APITestCase):
    def test_user_is_email_based_and_phone_is_optional(self):
        user = User.objects.create_user(
            email="email-login@example.com",
            full_name="Email Login",
            password="TestPass123!",
        )

        self.assertEqual(user.email, "email-login@example.com")
        self.assertIsNone(user.phone)
        self.assertTrue(user.check_password("TestPass123!"))
        self.assertEqual(User.USERNAME_FIELD, "email")

    def test_create_superuser_sets_admin_flags(self):
        admin = User.objects.create_superuser(
            email="superuser@example.com",
            full_name="Super User",
            password="AdminPass123!",
        )

        self.assertTrue(admin.is_staff)
        self.assertTrue(admin.is_superuser)
        self.assertTrue(admin.is_active)

    def test_soft_deleted_users_are_hidden_from_default_manager(self):
        user = self.create_user(email="deleted@example.com")

        user.is_deleted = True
        user.deleted_at = timezone.now()
        user.is_active = False
        user.save()

        self.assertFalse(User.objects.filter(id=user.id).exists())
        self.assertTrue(User.objects.all_with_deleted().filter(id=user.id).exists())

    @override_settings(**EMAIL_TEST_SETTINGS)
    def test_generate_otp_marks_old_codes_as_used(self):
        first_otp = OTP.generate_otp(email="otp@example.com")
        second_otp = OTP.generate_otp(email="otp@example.com")

        first_otp.refresh_from_db()

        self.assertTrue(first_otp.is_used)
        self.assertFalse(second_otp.is_used)
        self.assertEqual(second_otp.email, "otp@example.com")
        self.assertEqual(len(second_otp.code), 6)
        self.assertFalse(second_otp.is_expired)

    @override_settings(**EMAIL_TEST_SETTINGS)
    def test_verify_otp_success_marks_code_as_used(self):
        otp = OTP.generate_otp(email="verify@example.com")

        success, message, verified_otp = OTP.verify_otp_and_get_instance(
            email="verify@example.com",
            code=otp.code,
        )

        otp.refresh_from_db()

        self.assertTrue(success)
        self.assertEqual(message, "OTP verified successfully")
        self.assertEqual(verified_otp.id, otp.id)
        self.assertTrue(otp.is_used)

    @override_settings(**EMAIL_TEST_SETTINGS)
    def test_verify_otp_rejects_invalid_code(self):
        OTP.generate_otp(email="invalid@example.com")

        success, message, verified_otp = OTP.verify_otp_and_get_instance(
            email="invalid@example.com",
            code="000000",
        )

        self.assertFalse(success)
        self.assertEqual(message, "Invalid OTP code")
        self.assertIsNone(verified_otp)

    @override_settings(**EMAIL_TEST_SETTINGS)
    def test_verify_otp_rejects_expired_code(self):
        otp = OTP.generate_otp(email="expired@example.com")
        OTP.objects.filter(id=otp.id).update(
            expires_at=timezone.now() - timedelta(minutes=1)
        )
        otp.refresh_from_db()

        success, message, verified_otp = OTP.verify_otp_and_get_instance(
            email="expired@example.com",
            code=otp.code,
        )

        self.assertFalse(success)
        self.assertEqual(message, "OTP has expired")
        self.assertIsNone(verified_otp)


class OTPDeliveryTestCase(APITestCase):
    def setUp(self):
        mail.outbox = []

    def test_normalize_email(self):
        self.assertEqual(
            normalize_email("  TEST@Example.COM  "),
            "test@example.com",
        )

    def test_mask_email(self):
        self.assertEqual(mask_email("test@example.com"), "te***@example.com")
        self.assertEqual(mask_email("ab@example.com"), "a***@example.com")

    @override_settings(**EMAIL_TEST_SETTINGS)
    def test_send_otp_email_sends_text_and_html_email(self):
        send_otp_email(
            to_email="receiver@example.com",
            code="123456",
            expires_in_seconds=600,
        )

        self.assertEqual(len(mail.outbox), 1)

        email = mail.outbox[0]

        self.assertEqual(email.to, ["receiver@example.com"])
        self.assertEqual(email.subject, "Your MallByte verification code")
        self.assertIn("123456", email.body)
        self.assertEqual(len(email.alternatives), 1)
        self.assertIn("123456", email.alternatives[0][0])


class AuthFlowAPITestCase(AccountsTestMixin, APITestCase):
    def setUp(self):
        self.client = APIClient()
        mail.outbox = []

    @override_settings(**EMAIL_TEST_SETTINGS)
    def test_register_user_with_email_and_optional_phone(self):
        response = self.client.post(
            "/api/auth/register/",
            {
                "email": "register@example.com",
                "phone": "+989121111111",
                "full_name": "Register User",
                "password": "RegisterPass123!",
                "password2": "RegisterPass123!",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn("access", response.data)
        self.assertIn("refresh", response.data)
        self.assertEqual(response.data["user"]["email"], "register@example.com")

        user = User.objects.get(email="register@example.com")

        self.assertEqual(user.phone, "+989121111111")
        self.assertTrue(user.check_password("RegisterPass123!"))

    @override_settings(**EMAIL_TEST_SETTINGS)
    def test_register_rejects_password_mismatch(self):
        response = self.client.post(
            "/api/auth/register/",
            {
                "email": "mismatch@example.com",
                "full_name": "Mismatch User",
                "password": "RegisterPass123!",
                "password2": "WrongPass123!",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(User.objects.filter(email="mismatch@example.com").exists())

    def test_token_login_uses_email(self):
        self.create_user(
            email="jwt@example.com",
            full_name="JWT User",
            password="JwtPass123!",
            email_verified=True,
        )

        response = self.client.post(
            "/api/auth/token/",
            {
                "email": "jwt@example.com",
                "password": "JwtPass123!",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("access", response.data)
        self.assertIn("refresh", response.data)

    def test_token_login_rejects_wrong_password(self):
        self.create_user(
            email="wrong-password@example.com",
            password="CorrectPass123!",
        )

        response = self.client.post(
            "/api/auth/token/",
            {
                "email": "wrong-password@example.com",
                "password": "WrongPass123!",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    @override_settings(**EMAIL_TEST_SETTINGS)
    def test_otp_request_sends_email_and_does_not_expose_code(self):
        response = self.client.post(
            "/api/auth/otp/request/",
            {
                "email": "otp-request@example.com",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["delivery_channel"], "email")
        self.assertEqual(response.data["email"], "ot***@example.com")
        self.assertNotIn("code", response.data)

        otp = OTP.objects.get(email="otp-request@example.com")

        self.assertFalse(otp.is_used)
        self.assertEqual(len(otp.code), 6)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(otp.code, mail.outbox[0].body)

    @override_settings(**EMAIL_TEST_SETTINGS)
    def test_otp_request_normalizes_email(self):
        response = self.client.post(
            "/api/auth/otp/request/",
            {
                "email": "  Normalize@Example.COM  ",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(OTP.objects.filter(email="normalize@example.com").exists())

    @override_settings(**EMAIL_TEST_SETTINGS)
    def test_otp_verify_creates_new_user_and_returns_tokens(self):
        otp = OTP.generate_otp(email="new-otp-user@example.com")

        response = self.client.post(
            "/api/auth/otp/verify/",
            {
                "email": "new-otp-user@example.com",
                "code": otp.code,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["is_new"])
        self.assertIn("access", response.data)
        self.assertIn("refresh", response.data)
        self.assertEqual(response.data["user"]["email"], "new-otp-user@example.com")
        self.assertTrue(response.data["user"]["email_verified"])

        user = User.objects.get(email="new-otp-user@example.com")

        self.assertTrue(user.email_verified)
        self.assertIsNotNone(user.email_verified_at)

        otp.refresh_from_db()

        self.assertTrue(otp.is_used)

    @override_settings(**EMAIL_TEST_SETTINGS)
    def test_otp_verify_existing_user_marks_email_verified(self):
        user = self.create_user(
            email="existing-otp-user@example.com",
            email_verified=False,
        )
        otp = OTP.generate_otp(email="existing-otp-user@example.com")

        response = self.client.post(
            "/api/auth/otp/verify/",
            {
                "email": "existing-otp-user@example.com",
                "code": otp.code,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.data["is_new"])

        user.refresh_from_db()

        self.assertTrue(user.email_verified)
        self.assertIsNotNone(user.email_verified_at)

    @override_settings(**EMAIL_TEST_SETTINGS)
    def test_otp_verify_rejects_invalid_code(self):
        OTP.generate_otp(email="invalid-verify@example.com")

        response = self.client.post(
            "/api/auth/otp/verify/",
            {
                "email": "invalid-verify@example.com",
                "code": "000000",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["error"], "Invalid OTP code")

    @override_settings(**EMAIL_TEST_SETTINGS)
    def test_otp_verify_rejects_expired_code(self):
        otp = OTP.generate_otp(email="expired-verify@example.com")
        OTP.objects.filter(id=otp.id).update(
            expires_at=timezone.now() - timedelta(minutes=1)
        )
        otp.refresh_from_db()

        response = self.client.post(
            "/api/auth/otp/verify/",
            {
                "email": "expired-verify@example.com",
                "code": otp.code,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["error"], "OTP has expired")

    @override_settings(**EMAIL_TEST_SETTINGS)
    def test_password_reset_request_sends_email(self):
        self.create_user(
            email="reset@example.com",
            password="OldPass123!",
        )

        response = self.client.post(
            "/api/auth/password-reset/request/",
            {
                "email": "reset@example.com",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["delivery_channel"], "email")
        self.assertNotIn("code", response.data)

        otp = OTP.objects.get(email="reset@example.com")

        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(otp.code, mail.outbox[0].body)

    @override_settings(**EMAIL_TEST_SETTINGS)
    def test_password_reset_request_rejects_unknown_email(self):
        response = self.client.post(
            "/api/auth/password-reset/request/",
            {
                "email": "unknown@example.com",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @override_settings(**EMAIL_TEST_SETTINGS)
    def test_password_reset_verify_changes_password(self):
        user = self.create_user(
            email="reset-verify@example.com",
            password="OldPass123!",
        )
        otp = OTP.generate_otp(email="reset-verify@example.com")

        response = self.client.post(
            "/api/auth/password-reset/verify/",
            {
                "email": "reset-verify@example.com",
                "code": otp.code,
                "new_password": "NewPass123!",
                "confirm_password": "NewPass123!",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        user.refresh_from_db()

        self.assertTrue(user.check_password("NewPass123!"))

    def test_change_password_requires_authentication(self):
        response = self.client.post(
            "/api/auth/change-password/",
            {
                "old_password": "OldPass123!",
                "new_password": "NewPass123!",
                "confirm_password": "NewPass123!",
            },
            format="json",
        )

        self.assertIn(
            response.status_code,
            [
                status.HTTP_401_UNAUTHORIZED,
                status.HTTP_403_FORBIDDEN,
            ],
        )

    def test_change_password_success(self):
        user = self.create_user(
            email="change-password@example.com",
            password="OldPass123!",
        )
        self.authenticate(user)

        response = self.client.post(
            "/api/auth/change-password/",
            {
                "old_password": "OldPass123!",
                "new_password": "NewPass123!",
                "confirm_password": "NewPass123!",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        user.refresh_from_db()

        self.assertTrue(user.check_password("NewPass123!"))

    def test_change_password_rejects_wrong_old_password(self):
        user = self.create_user(
            email="wrong-old-password@example.com",
            password="OldPass123!",
        )
        self.authenticate(user)

        response = self.client.post(
            "/api/auth/change-password/",
            {
                "old_password": "WrongOldPass123!",
                "new_password": "NewPass123!",
                "confirm_password": "NewPass123!",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class ProfileAndAddressAPITestCase(AccountsTestMixin, APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = self.create_user(email="profile@example.com")
        self.authenticate(self.user)

    def test_profile_get_creates_profile_if_missing(self):
        self.assertFalse(Profile.objects.filter(user=self.user).exists())

        response = self.client.get("/api/auth/profile/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(Profile.objects.filter(user=self.user).exists())

    def test_profile_update(self):
        response = self.client.patch(
            "/api/auth/profile/",
            {
                "birth_date": "1998-01-01",
                "gender": "M",
                "national_code": "1234567890",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        profile = Profile.objects.get(user=self.user)

        self.assertEqual(str(profile.birth_date), "1998-01-01")
        self.assertEqual(profile.gender, "M")
        self.assertEqual(profile.national_code, "1234567890")

    def test_address_create_list_and_owner_scope(self):
        other_user = self.create_user(email="other-address-owner@example.com")
        Address.objects.create(
            user=other_user,
            **self.address_payload(title="Other User Address"),
        )

        response = self.client.post(
            "/api/auth/addresses/",
            self.address_payload(title="My Home"),
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        address_id = response.data["id"]

        response = self.client.get("/api/auth/addresses/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        results = response.data.get("results", response.data)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["id"], address_id)
        self.assertEqual(results[0]["title"], "My Home")

    def test_address_rejects_invalid_postal_code(self):
        payload = self.address_payload()
        payload["postal_code"] = "123"

        response = self.client.post(
            "/api/auth/addresses/",
            payload,
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_address_rejects_invalid_receiver_phone(self):
        payload = self.address_payload()
        payload["receiver_phone"] = "+989121234567"

        response = self.client.post(
            "/api/auth/addresses/",
            payload,
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_set_default_address_unsets_previous_default(self):
        first = Address.objects.create(
            user=self.user,
            **self.address_payload(title="First"),
        )
        second_payload = self.address_payload(title="Second")
        second_payload["is_default"] = True
        second = Address.objects.create(
            user=self.user,
            **second_payload,
        )

        url = f"/api/auth/addresses/{first.id}/set_default/"

        response = self.client.patch(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        first.refresh_from_db()
        second.refresh_from_db()

        self.assertTrue(first.is_default)
        self.assertFalse(second.is_default)


class AccountDeleteAPITestCase(AccountsTestMixin, APITestCase):
    def setUp(self):
        self.client = APIClient()

    def test_delete_account_requires_confirmation(self):
        user = self.create_user(email="delete-confirm@example.com")
        self.authenticate(user)

        response = self.client.delete(
            "/api/auth/delete-account/",
            {
                "confirm": False,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_delete_account_soft_deletes_user(self):
        user = self.create_user(email="delete@example.com")
        self.authenticate(user)

        response = self.client.delete(
            "/api/auth/delete-account/",
            {
                "confirm": True,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        user = User.objects.all_with_deleted().get(id=user.id)

        self.assertTrue(user.is_deleted)
        self.assertFalse(user.is_active)
        self.assertIsNotNone(user.deleted_at)

    @patch("apps.rbac.utils.log_admin_action")
    def test_admin_can_soft_delete_other_user(self, mocked_log_admin_action):
        admin = self.create_admin()
        target = self.create_user(email="admin-delete-target@example.com")
        self.authenticate(admin)

        response = self.client.delete(
            f"/api/auth/admin/users/{target.id}/delete/",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        target = User.objects.all_with_deleted().get(id=target.id)

        self.assertTrue(target.is_deleted)
        self.assertFalse(target.is_active)
        mocked_log_admin_action.assert_called_once()

    @patch("apps.rbac.utils.log_admin_action")
    def test_admin_cannot_delete_self(self, mocked_log_admin_action):
        admin = self.create_admin()
        self.authenticate(admin)

        response = self.client.delete(
            f"/api/auth/admin/users/{admin.id}/delete/",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        mocked_log_admin_action.assert_not_called()

    @patch("apps.rbac.utils.log_admin_action")
    def test_admin_cannot_delete_superuser(self, mocked_log_admin_action):
        admin = self.create_admin()
        other_admin = self.create_user(
            email="other-superuser@example.com",
            is_staff=True,
            is_superuser=True,
        )
        self.authenticate(admin)

        response = self.client.delete(
            f"/api/auth/admin/users/{other_admin.id}/delete/",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        mocked_log_admin_action.assert_not_called()


class SellerAPITestCase(AccountsTestMixin, APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = self.create_user(email="seller-user@example.com")
        self.admin = self.create_admin()

    def test_seller_apply_requires_authentication(self):
        response = self.client.post(
            "/api/auth/seller/apply/",
            self.seller_payload(),
            format="json",
        )

        self.assertIn(
            response.status_code,
            [
                status.HTTP_401_UNAUTHORIZED,
                status.HTTP_403_FORBIDDEN,
            ],
        )

    def test_authenticated_user_can_apply_as_seller(self):
        self.authenticate(self.user)

        response = self.client.post(
            "/api/auth/seller/apply/",
            self.seller_payload(store_name="My Seller Store"),
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        seller = Seller.objects.get(user=self.user)

        self.assertEqual(seller.store_name, "My Seller Store")
        self.assertEqual(seller.status, Seller.StatusChoices.PENDING)

    def test_user_cannot_apply_twice_as_seller(self):
        Seller.objects.create(
            user=self.user,
            **self.seller_payload(store_name="Existing Store"),
        )
        self.authenticate(self.user)

        response = self.client.post(
            "/api/auth/seller/apply/",
            self.seller_payload(store_name="Second Store"),
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_seller_status_returns_404_when_no_seller_profile(self):
        self.authenticate(self.user)

        response = self.client.get("/api/auth/seller/status/")

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_seller_status_returns_current_user_seller(self):
        seller = Seller.objects.create(
            user=self.user,
            **self.seller_payload(store_name="Status Store"),
        )
        self.authenticate(self.user)

        response = self.client.get("/api/auth/seller/status/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["id"], seller.id)
        self.assertEqual(response.data["store_name"], "Status Store")

    def test_admin_can_list_sellers_and_filter_by_status(self):
        Seller.objects.create(
            user=self.user,
            **self.seller_payload(store_name="Pending Store"),
        )
        approved_user = self.create_user(email="approved-seller-user@example.com")
        approved_seller = Seller.objects.create(
            user=approved_user,
            **self.seller_payload(store_name="Approved Store"),
        )
        approved_seller.status = Seller.StatusChoices.APPROVED
        approved_seller.save(update_fields=["status"])

        self.authenticate(self.admin)

        response = self.client.get(
            "/api/auth/admin/sellers/",
            {
                "status": Seller.StatusChoices.APPROVED,
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        results = response.data.get("results", response.data)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["store_name"], "Approved Store")

    def test_non_admin_cannot_list_sellers(self):
        self.authenticate(self.user)

        response = self.client.get("/api/auth/admin/sellers/")

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_admin_can_view_seller_detail(self):
        seller = Seller.objects.create(
            user=self.user,
            **self.seller_payload(store_name="Detail Store"),
        )
        self.authenticate(self.admin)

        response = self.client.get(f"/api/auth/admin/sellers/{seller.id}/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["id"], seller.id)
        self.assertEqual(response.data["store_name"], "Detail Store")


class EmailVerificationAPITestCase(AccountsTestMixin, APITestCase):
    def setUp(self):
        self.client = APIClient()
        mail.outbox = []
        cache.clear()

    @override_settings(**EMAIL_TEST_SETTINGS)
    def test_email_verify_request_sends_verification_email(self):
        user = self.create_user(
            email="old-email@example.com",
            email_verified=False,
        )
        self.authenticate(user)

        response = self.client.post(
            "/api/auth/email/verify-request/",
            {
                "email": "new-email@example.com",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["email"], "new-email@example.com")
        self.assertEqual(len(mail.outbox), 1)

        user.refresh_from_db()

        self.assertEqual(user.email, "new-email@example.com")

    @override_settings(**EMAIL_TEST_SETTINGS)
    def test_email_verify_request_rejects_already_verified_user(self):
        user = self.create_user(
            email="verified@example.com",
            email_verified=True,
        )
        self.authenticate(user)

        response = self.client.post(
            "/api/auth/email/verify-request/",
            {
                "email": "another@example.com",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @override_settings(**EMAIL_TEST_SETTINGS)
    def test_email_verify_confirm_success(self):
        user = self.create_user(
            email="confirm-email@example.com",
            email_verified=False,
        )
        self.authenticate(user)

        token = generate_email_verification_token(user)

        response = self.client.post(
            "/api/auth/email/verify-confirm/",
            {
                "token": token,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        user.refresh_from_db()

        self.assertTrue(user.email_verified)
        self.assertIsNotNone(user.email_verified_at)

    @override_settings(**EMAIL_TEST_SETTINGS)
    def test_email_verify_confirm_rejects_invalid_token(self):
        user = self.create_user(
            email="invalid-token@example.com",
            email_verified=False,
        )
        self.authenticate(user)

        response = self.client.post(
            "/api/auth/email/verify-confirm/",
            {
                "token": "invalid-token",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)