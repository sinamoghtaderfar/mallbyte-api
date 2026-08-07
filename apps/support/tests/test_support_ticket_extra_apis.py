import shutil
import tempfile
from typing import cast

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from apps.accounts.models import User
from apps.support.models import (
    SupportTag,
    SupportTicket,
    TicketAttachment,
    TicketAuditLog,
    TicketMessage,
)

TEST_MEDIA_ROOT = tempfile.mkdtemp()


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
class SupportTicketExtraAPITests(APITestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEST_MEDIA_ROOT, ignore_errors=True)

    def create_test_user(
        self,
        *,
        phone,
        email,
        full_name,
        password="testpass123",
        is_staff=False,
        is_superuser=False,
    ):
        user = User(
            phone=phone,
            email=email,
            full_name=full_name,
            is_active=True,
            is_staff=is_staff,
            is_superuser=is_superuser,
        )
        user.set_password(password)
        user.save()
        return user

    def setUp(self):
        self.support_staff = self.create_test_user(
            phone="+989970000001",
            email="support_extra_staff@example.com",
            full_name="Support Extra Staff",
            is_staff=True,
        )

        self.customer = self.create_test_user(
            phone="+989970000002",
            email="support_extra_customer@example.com",
            full_name="Support Extra Customer",
        )

        self.other_customer = self.create_test_user(
            phone="+989970000003",
            email="other_support_extra_customer@example.com",
            full_name="Other Support Extra Customer",
        )

        self.ticket = SupportTicket.objects.create(
            customer=self.customer,
            assigned_to=self.support_staff,
            subject="Support extra ticket",
            category=SupportTicket.CategoryChoices.ORDER,
            priority=SupportTicket.PriorityChoices.NORMAL,
            status=SupportTicket.StatusChoices.OPEN,
        )

        self.message = TicketMessage.objects.create(
            ticket=self.ticket,
            sender=self.customer,
            message="Initial support message.",
        )

        self.tag = SupportTag.objects.create(
            name="Refund Issue",
            color="#FFAA00",
        )

    def get_api_client(self) -> APIClient:
        return cast(APIClient, self.client)

    def authenticate_customer(self):
        self.get_api_client().force_authenticate(user=self.customer)

    def authenticate_staff(self):
        self.get_api_client().force_authenticate(user=self.support_staff)

    def test_staff_can_create_support_tag(self):
        self.authenticate_staff()

        url = reverse("support-tag-list")

        response = self.client.post(
            url,
            data={
                "name": "Delivery Problem",
                "color": "#00AAFF",
                "is_active": True,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        tag = SupportTag.objects.get(name="Delivery Problem")

        self.assertEqual(tag.slug, "delivery-problem")
        self.assertEqual(tag.color, "#00AAFF")

    def test_customer_cannot_create_support_tag(self):
        self.authenticate_customer()

        url = reverse("support-tag-list")

        response = self.client.post(
            url,
            data={
                "name": "Customer Tag",
                "color": "#FFFFFF",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(SupportTag.objects.filter(name="Customer Tag").exists())

    def test_authenticated_user_can_list_support_tags(self):
        self.authenticate_customer()

        url = reverse("support-tag-list")

        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()

        if isinstance(data, dict) and "results" in data:
            data = data["results"]

        tag_ids = {item["id"] for item in data}

        self.assertIn(self.tag.id, tag_ids)

    def test_staff_can_add_and_remove_tag_from_ticket(self):
        self.authenticate_staff()

        add_url = reverse("support-ticket-add-tag", args=[self.ticket.pk])

        add_response = self.client.post(
            add_url,
            data={
                "tag": self.tag.pk,
            },
            format="json",
        )

        self.assertEqual(add_response.status_code, status.HTTP_200_OK)

        self.ticket.refresh_from_db()

        self.assertTrue(self.ticket.tags.filter(pk=self.tag.pk).exists())

        self.assertTrue(
            TicketAuditLog.objects.filter(
                ticket=self.ticket,
                actor=self.support_staff,
                action=TicketAuditLog.ActionChoices.TAG_ADDED,
                metadata__tag_id=self.tag.pk,
            ).exists()
        )

        remove_url = reverse("support-ticket-remove-tag", args=[self.ticket.pk])

        remove_response = self.client.post(
            remove_url,
            data={
                "tag": self.tag.pk,
            },
            format="json",
        )

        self.assertEqual(remove_response.status_code, status.HTTP_200_OK)

        self.ticket.refresh_from_db()

        self.assertFalse(self.ticket.tags.filter(pk=self.tag.pk).exists())

        self.assertTrue(
            TicketAuditLog.objects.filter(
                ticket=self.ticket,
                actor=self.support_staff,
                action=TicketAuditLog.ActionChoices.TAG_REMOVED,
                metadata__tag_id=self.tag.pk,
            ).exists()
        )

    def test_customer_cannot_add_tag_to_ticket(self):
        self.authenticate_customer()

        url = reverse("support-ticket-add-tag", args=[self.ticket.pk])

        response = self.client.post(
            url,
            data={
                "tag": self.tag.pk,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        self.ticket.refresh_from_db()

        self.assertFalse(self.ticket.tags.filter(pk=self.tag.pk).exists())

    def test_customer_can_upload_attachment_to_own_ticket(self):
        self.authenticate_customer()

        url = reverse("support-ticket-attachments", args=[self.ticket.pk])

        uploaded_file = SimpleUploadedFile(
            "support-proof.txt",
            b"This is a support attachment.",
            content_type="text/plain",
        )

        response = self.client.post(
            url,
            data={
                "file": uploaded_file,
            },
            format="multipart",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        attachment = TicketAttachment.objects.get(ticket=self.ticket)

        self.assertEqual(attachment.uploaded_by, self.customer)
        self.assertEqual(attachment.original_filename, "support-proof.txt")
        self.assertEqual(attachment.content_type, "text/plain")
        self.assertGreater(attachment.size, 0)

        self.assertTrue(
            TicketAuditLog.objects.filter(
                ticket=self.ticket,
                actor=self.customer,
                action=TicketAuditLog.ActionChoices.ATTACHMENT_ADDED,
                metadata__attachment_id=attachment.pk,
            ).exists()
        )

    def test_customer_can_list_own_ticket_attachments(self):
        attachment = TicketAttachment.objects.create(
            ticket=self.ticket,
            message=self.message,
            uploaded_by=self.customer,
            file=SimpleUploadedFile(
                "existing-file.txt",
                b"Existing file content.",
                content_type="text/plain",
            ),
            original_filename="existing-file.txt",
            content_type="text/plain",
            size=22,
        )

        self.authenticate_customer()

        url = reverse("support-ticket-attachments", args=[self.ticket.pk])

        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        attachment_ids = {item["id"] for item in data}

        self.assertIn(attachment.id, attachment_ids)

    def test_customer_cannot_upload_attachment_to_other_customer_ticket(self):
        other_ticket = SupportTicket.objects.create(
            customer=self.other_customer,
            subject="Other customer ticket",
            category=SupportTicket.CategoryChoices.OTHER,
            priority=SupportTicket.PriorityChoices.NORMAL,
            status=SupportTicket.StatusChoices.OPEN,
        )

        self.authenticate_customer()

        url = reverse("support-ticket-attachments", args=[other_ticket.pk])

        uploaded_file = SimpleUploadedFile(
            "forbidden.txt",
            b"Forbidden attachment.",
            content_type="text/plain",
        )

        response = self.client.post(
            url,
            data={
                "file": uploaded_file,
            },
            format="multipart",
        )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

        self.assertFalse(TicketAttachment.objects.filter(ticket=other_ticket).exists())

    def test_staff_can_list_audit_logs(self):
        TicketAuditLog.log(
            ticket=self.ticket,
            actor=self.customer,
            action=TicketAuditLog.ActionChoices.CREATED,
            description="Support ticket created.",
        )

        self.authenticate_staff()

        url = reverse("support-ticket-audit-logs", args=[self.ticket.pk])

        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()

        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["action"], TicketAuditLog.ActionChoices.CREATED)

    def test_customer_cannot_list_audit_logs(self):
        TicketAuditLog.log(
            ticket=self.ticket,
            actor=self.customer,
            action=TicketAuditLog.ActionChoices.CREATED,
            description="Support ticket created.",
        )

        self.authenticate_customer()

        url = reverse("support-ticket-audit-logs", args=[self.ticket.pk])

        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)