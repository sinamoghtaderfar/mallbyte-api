import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse
from rest_framework.test import APITestCase

from apps.accounts.models import User
from apps.support.models import SupportTicket, TicketAttachment
from apps.support.tests.helpers import grant_support_manager


class PrivateSupportAttachmentsTests(APITestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.settings_override = override_settings(
            MEDIA_ROOT=Path(self.tmp) / "public",
            SUPPORT_PRIVATE_MEDIA_ROOT=Path(self.tmp) / "private",
        )
        self.settings_override.enable()
        self.addCleanup(self.settings_override.disable)
        self.customer = User.objects.create_user(
            email="private-support-customer@example.com", full_name="Owner"
        )
        self.stranger = User.objects.create_user(
            email="private-support-stranger@example.com", full_name="Stranger"
        )
        self.agent = User.objects.create_user(
            email="private-support-agent@example.com", full_name="Agent"
        )
        grant_support_manager(self.agent)
        self.ticket = SupportTicket.objects.create(
            customer=self.customer, subject="Sensitive information"
        )
        self.list_url = reverse("support-ticket-attachments", args=[self.ticket.pk])

    def upload(self, name, payload, content_type="application/octet-stream"):
        return self.client.post(
            self.list_url,
            {"file": SimpleUploadedFile(name, payload, content_type=content_type)},
            format="multipart",
        )

    def test_private_text_file_requires_authorized_download(self):
        self.client.force_authenticate(user=self.customer)
        response = self.upload("evidence.txt", b"secret evidence", "text/plain")
        self.assertEqual(response.status_code, 201, response.data)
        attachment = TicketAttachment.objects.get(ticket=self.ticket)
        self.assertNotIn("file", response.data)
        self.assertIn("download_url", response.data)
        self.assertTrue(str(attachment.file.path).startswith(str(Path(self.tmp) / "private")))
        self.assertFalse((Path(self.tmp) / "public" / attachment.file.name).exists())
        with self.assertRaises(ValueError):
            _ = attachment.file.url

        url = reverse("support-ticket-download-attachment", args=[self.ticket.pk, attachment.pk])
        self.client.force_authenticate(user=None)
        self.assertEqual(self.client.get(url).status_code, 401)
        self.client.force_authenticate(user=self.stranger)
        self.assertEqual(self.client.get(url).status_code, 404)
        self.client.force_authenticate(user=self.agent)
        allowed = self.client.get(url)
        self.assertEqual(allowed.status_code, 200)
        self.assertEqual(b"".join(allowed.streaming_content), b"secret evidence")
        self.assertIn("attachment", allowed["Content-Disposition"])
        self.assertEqual(allowed["Cache-Control"], "private, no-store")
        self.assertEqual(allowed["X-Content-Type-Options"], "nosniff")

    def test_wrong_ticket_cannot_download_attachment(self):
        self.client.force_authenticate(user=self.customer)
        self.assertEqual(self.upload("record.txt", b"safe text").status_code, 201)
        attachment = TicketAttachment.objects.get()
        other_ticket = SupportTicket.objects.create(customer=self.customer, subject="Other")
        url = reverse("support-ticket-download-attachment", args=[other_ticket.pk, attachment.pk])
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_rejects_executable_and_spoofed_files(self):
        self.client.force_authenticate(user=self.customer)
        for name, payload in [
            ("payload.exe", b"binary"),
            ("fake.pdf", b"not a PDF"),
            ("fake.png", b"not an image"),
            ("fake.jpg", b"not a photo"),
            ("binary.txt", b"hello\x00binary"),
        ]:
            with self.subTest(name=name):
                response = self.upload(name, payload)
                self.assertEqual(response.status_code, 400)
        self.assertEqual(TicketAttachment.objects.count(), 0)

    def test_rejects_oversized_attachment(self):
        self.client.force_authenticate(user=self.customer)
        response = self.upload("large.txt", b"a" * (8 * 1024 * 1024 + 1), "text/plain")
        self.assertEqual(response.status_code, 400)
        self.assertFalse(TicketAttachment.objects.exists())
