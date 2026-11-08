import tempfile

from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse
from rest_framework.test import APITestCase

from apps.returns.models import ReturnItem, ReturnRequest, ReturnShipment
from apps.returns.tests import test_multiseller_returns_security as fixtures


class CustomerReturnWorkflowTests(APITestCase):
    setUp = fixtures.MultiSellerReturnsSecurityTests.setUp

    def evidence(self):
        return SimpleUploadedFile("private evidence.txt", b"return evidence", content_type="text/plain")

    def test_customer_upload_is_private_and_actor_is_server_assigned(self):
        cache.clear()
        self.client.force_authenticate(self.buyer)
        with tempfile.TemporaryDirectory() as root, override_settings(SUPPORT_PRIVATE_MEDIA_ROOT=root):
            response = self.client.post(reverse("return-evidence-upload", args=[self.claim.pk]),
                                        {"file": self.evidence(), "return_item": self.claim_a.pk,
                                         "uploaded_by": self.admin.pk}, format="multipart")
            self.assertEqual(response.status_code, 201, response.data)
            attachment = self.claim.attachments.get(pk=response.data["id"])
            self.assertEqual(attachment.uploaded_by_id, self.buyer.pk)
            self.assertTrue(attachment.file.storage.exists(attachment.file.name))
            self.assertNotIn("private evidence", attachment.file.name)
            self.assertIn("/attachments/", response.data["file"])
            with self.assertRaises(ValueError):
                _ = attachment.file.url

    def test_unrelated_users_cannot_upload(self):
        cache.clear()
        for user in (self.other_buyer, self.first_seller, self.admin):
            self.client.force_authenticate(user)
            response = self.client.post(reverse("return-evidence-upload", args=[self.claim.pk]),
                                        {"file": self.evidence()}, format="multipart")
            self.assertEqual(response.status_code, 404)

    def test_unsafe_files_foreign_items_and_closed_claims_are_rejected(self):
        cache.clear()
        self.client.force_authenticate(self.buyer)
        url = reverse("return-evidence-upload", args=[self.claim.pk])
        response = self.client.post(url, {"file": SimpleUploadedFile("bad.html", b"<script>x</script>")}, format="multipart")
        self.assertEqual(response.status_code, 400)
        other = ReturnRequest.objects.create(order=self.order, customer=self.other_buyer)
        foreign = ReturnItem.objects.create(return_request=other, order_item=self.first_item,
                                            quantity=1, requested_refund_amount=100)
        response = self.client.post(url, {"file": self.evidence(), "return_item": foreign.pk}, format="multipart")
        self.assertEqual(response.status_code, 400)
        self.claim.status = ReturnRequest.Status.CLOSED
        self.claim.save(update_fields=["status"])
        self.assertEqual(self.client.post(url, {"file": self.evidence()}, format="multipart").status_code, 409)

    def test_tracking_requires_approval_and_is_idempotent(self):
        self.client.force_authenticate(self.buyer)
        url = reverse("return-customer-shipment", args=[self.claim.pk])
        payload = {"carrier": "Test carrier", "tracking_number": "TEST-123", "tracking_url": "https://example.test/track/TEST-123"}
        self.assertEqual(self.client.post(url, payload, format="json").status_code, 409)
        self.claim.status = ReturnRequest.Status.APPROVED
        self.claim.save(update_fields=["status"])
        first = self.client.post(url, {**payload, "received_at": "2020-01-01"}, format="json")
        self.assertEqual(first.status_code, 200, first.data)
        history_count = self.claim.status_history.count()
        self.assertEqual(self.client.post(url, payload, format="json").status_code, 200)
        self.assertEqual(self.claim.status_history.count(), history_count)
        shipment = ReturnShipment.objects.get(return_request=self.claim)
        self.assertIsNone(shipment.received_at)
        self.assertIsNotNone(shipment.shipped_at)
        self.claim.refresh_from_db()
        self.assertEqual(self.claim.status, ReturnRequest.Status.WAITING_FOR_ITEM)
        self.assertEqual(self.client.post(url, {**payload, "tracking_number": "different"}, format="json").status_code, 409)

    def test_foreign_tracking_submission_is_hidden(self):
        self.client.force_authenticate(self.other_buyer)
        response = self.client.post(reverse("return-customer-shipment", args=[self.claim.pk]),
                                    {"carrier": "Test", "tracking_number": "FOREIGN"}, format="json")
        self.assertEqual(response.status_code, 404)
