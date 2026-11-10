from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest import skipUnless
from unittest.mock import patch

from django.core.cache import cache
from django.db import IntegrityError, close_old_connections, connection, connections, transaction
from django.db.models.query import QuerySet
from django.test import TransactionTestCase
from rest_framework.test import APITestCase

from apps.accounts.auth_tokens import issue_user_tokens
from apps.accounts.models import OTP, User
from apps.accounts.utils import generate_email_verification_token, pending_email_for_token


class IdentityWorkflowTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(email="owner@example.com", password="OriginalPass123!", email_verified=True)
        self.access = str(issue_user_tokens(self.user).access_token)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.access}")

    def test_change_password_rejects_common_numeric_password(self):
        result = self.client.post("/api/auth/change-password/", {
            "old_password": "OriginalPass123!", "new_password": "12345678", "confirm_password": "12345678",
        }, format="json")
        self.assertEqual(result.status_code, 400, result.data)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("OriginalPass123!"))

    def test_email_target_is_pending_until_proved_and_old_session_is_revoked(self):
        result = self.client.post("/api/auth/email/verify-request/", {"email": "NEW@example.com"}, format="json")
        self.assertEqual(result.status_code, 200, result.data)
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "owner@example.com")
        token = generate_email_verification_token(self.user, email="new@example.com")
        result = self.client.post("/api/auth/email/verify-confirm/", {"token": token}, format="json")
        self.assertEqual(result.status_code, 200, result.data)
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "new@example.com")
        self.assertEqual(self.client.get("/api/auth/profile/").status_code, 401)
        self.assertIsNone(pending_email_for_token(self.user, token))

    def test_unverified_and_deleted_email_collisions_are_validated(self):
        for deleted in (False, True):
            target = User.objects.create_user(email=f"taken-{deleted}@example.com", is_deleted=deleted)
            result = self.client.post("/api/auth/email/verify-request/", {"email": target.email.upper()}, format="json")
            self.assertEqual(result.status_code, 400, result.data)
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "owner@example.com")

    @patch("apps.accounts.views.send_mail", side_effect=RuntimeError("private upstream detail"))
    def test_email_delivery_failure_preserves_identity_and_hides_details(self, send):
        result = self.client.post("/api/auth/email/verify-request/", {"email": "new@example.com"}, format="json")
        self.assertEqual(result.status_code, 503)
        self.assertNotIn("private upstream detail", str(result.data))
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "owner@example.com")

    def test_proof_cannot_survive_a_security_version_change(self):
        token = generate_email_verification_token(self.user, email="new@example.com")
        self.user.invalidate_sessions()
        self.assertIsNone(pending_email_for_token(self.user, token))

    def test_email_claimed_after_request_returns_validation_error_without_identity_change(self):
        token = generate_email_verification_token(self.user, email="claimed@example.com")
        User.objects.create_user(email="claimed@example.com")
        result = self.client.post("/api/auth/email/verify-confirm/", {"token": token}, format="json")
        self.assertEqual(result.status_code, 400, result.data)
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "owner@example.com")

    def test_rejected_reset_password_does_not_consume_otp(self):
        otp = OTP.generate_otp(self.user.email)
        self.client.credentials()
        result = self.client.post("/api/auth/password-reset/verify/", {
            "email": self.user.email, "code": otp.code, "new_password": "12345678",
        }, format="json")
        self.assertEqual(result.status_code, 400, result.data)
        otp.refresh_from_db()
        self.assertFalse(otp.is_used)

    def test_email_unique_constraint_is_case_insensitive(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            User.objects.bulk_create([User(email="OWNER@example.com", full_name="Duplicate")])

    def test_otp_cannot_be_consumed_twice(self):
        otp = OTP.generate_otp("owner@example.com")
        self.assertTrue(OTP.verify_otp("owner@example.com", otp.code)[0])
        self.assertFalse(OTP.verify_otp("owner@example.com", otp.code)[0])

    def test_two_unused_challenges_for_one_email_are_rejected_by_database(self):
        otp = OTP.generate_otp("owner@example.com")
        with self.assertRaises(IntegrityError), transaction.atomic():
            OTP.objects.create(email=otp.email, code="123456", expires_at=otp.expires_at)


@skipUnless(connection.vendor == "postgresql", "PostgreSQL row/unique-index concurrency semantics required")
class OTPConcurrencyTests(TransactionTestCase):
    def in_thread(self, callback):
        close_old_connections()
        try:
            return callback()
        finally:
            connections.close_all()

    def test_concurrent_consumption_succeeds_once_after_both_read_the_unused_code(self):
        otp = OTP.generate_otp("race@example.com")
        barrier = Barrier(2)
        original = QuerySet.latest

        def simultaneous_read(queryset, *args, **kwargs):
            result = original(queryset, *args, **kwargs)
            if queryset.model is OTP:
                barrier.wait(timeout=10)
            return result

        with patch.object(QuerySet, "latest", simultaneous_read), ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(self.in_thread, lambda: OTP.verify_otp(otp.email, otp.code)[0]) for _ in range(2)]
            self.assertEqual(sorted(f.result(timeout=15) for f in futures), [False, True])

    def test_concurrent_first_issuance_leaves_one_unused_challenge(self):
        barrier = Barrier(2)

        def issue():
            barrier.wait(timeout=10)
            return OTP.generate_otp("new-race@example.com").pk

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(self.in_thread, issue) for _ in range(2)]
            self.assertEqual(len({future.result(timeout=15) for future in futures}), 2)
        self.assertEqual(OTP.objects.filter(email="new-race@example.com", is_used=False).count(), 1)
