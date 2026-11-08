import tempfile
from pathlib import Path

from django.core.files.base import ContentFile
from django.test import override_settings
from django.urls import reverse
from rest_framework.test import APITestCase

from apps.returns.models import ReturnShipment
from apps.returns.serializers import ReturnAttachmentSerializer, ReturnShipmentSerializer
from apps.returns.tests import test_multiseller_returns_security as fixtures


class PrivateReturnMediaTests(APITestCase):
    setUp = fixtures.MultiSellerReturnsSecurityTests.setUp

    def test_attachment_download_enforces_customer_seller_and_internal_visibility(self):
        with tempfile.TemporaryDirectory() as root, override_settings(SUPPORT_PRIVATE_MEDIA_ROOT=root):
            attachments = list(self.claim.attachments.order_by("pk"))
            own, other, shared, internal = attachments
            for attachment in attachments:
                attachment.file.save(f"evidence-{attachment.pk}.txt", ContentFile(b"private evidence"))
            matrix = [
                (self.buyer, [200, 200, 200, 404]),
                (self.other_buyer, [404, 404, 404, 404]),
                (self.first_seller, [200, 404, 404, 404]),
                (self.second_seller, [404, 200, 404, 404]),
                (self.unrelated_seller, [404, 404, 404, 404]),
                (self.admin, [200, 200, 200, 200]),
            ]
            for user, expected in matrix:
                self.client.force_authenticate(user=user)
                for attachment, code in zip((own, other, shared, internal), expected, strict=True):
                    with self.subTest(user=user.pk, attachment=attachment.pk):
                        response = self.client.get(reverse("return-attachment-download", args=[attachment.pk]))
                        self.assertEqual(response.status_code, code)
                        if code == 200:
                            self.assertEqual(b"".join(response.streaming_content), b"private evidence")
                            self.assertEqual(response["Cache-Control"], "private, no-store")
                            self.assertEqual(response["X-Content-Type-Options"], "nosniff")
            self.client.force_authenticate(user=None)
            self.assertEqual(self.client.get(reverse("return-attachment-download", args=[own.pk])).status_code, 401)

    def test_shipping_label_is_private_and_urls_never_expose_storage(self):
        with tempfile.TemporaryDirectory() as root, override_settings(SUPPORT_PRIVATE_MEDIA_ROOT=root):
            shipment, _ = ReturnShipment.objects.get_or_create(return_request=self.claim)
            shipment.shipping_label.save("label.pdf", ContentFile(b"%PDF-private"))
            attachment = self.claim.attachments.first()
            self.assertEqual(ReturnAttachmentSerializer(attachment).data["file"], reverse("return-attachment-download", args=[attachment.pk]))
            url = reverse("return-shipping-label-download", args=[shipment.pk])
            self.assertEqual(ReturnShipmentSerializer(shipment).data["shipping_label"], url)
            self.assertTrue(Path(shipment.shipping_label.path).is_relative_to(Path(root)))
            with self.assertRaises(ValueError):
                _ = shipment.shipping_label.url
            for user, expected in ((self.buyer, 200), (self.first_seller, 404), (self.other_buyer, 404), (self.admin, 200)):
                self.client.force_authenticate(user=user)
                response = self.client.get(url)
                self.assertEqual(response.status_code, expected)
                if expected == 200:
                    self.assertEqual(b"".join(response.streaming_content), b"%PDF-private")

    def test_plain_staff_cannot_download_another_customers_evidence(self):
        self.other_buyer.is_staff = True
        self.other_buyer.save(update_fields=["is_staff"])
        self.client.force_authenticate(user=self.other_buyer)
        attachment = self.claim.attachments.first()
        self.assertEqual(self.client.get(reverse("return-attachment-download", args=[attachment.pk])).status_code, 404)
