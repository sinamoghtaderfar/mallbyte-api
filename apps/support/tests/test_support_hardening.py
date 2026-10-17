from typing import cast

from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from apps.accounts.models import User
from apps.support.models import SupportTag, SupportTicket
from apps.support.tests.helpers import (
    grant_support_agent,
    grant_support_manager,
)


class SupportHardeningTests(APITestCase):
    def setUp(self):
        self.customer = self.create_user(
            phone="+989910000001",
            email="support-hardening-customer@example.com",
            full_name="Support Customer",
        )

        self.regular_staff = self.create_user(
            phone="+989910000002",
            email="regular-staff@example.com",
            full_name="Regular Django Staff",
            is_staff=True,
        )

        self.support_agent = self.create_user(
            phone="+989910000003",
            email="support-agent@example.com",
            full_name="Support Agent",
        )
        grant_support_agent(self.support_agent)

        self.support_manager = self.create_user(
            phone="+989910000004",
            email="support-manager@example.com",
            full_name="Support Manager",
        )
        grant_support_manager(self.support_manager)

        self.ticket = SupportTicket.objects.create(
            customer=self.customer,
            subject="Existing support ticket",
            category=SupportTicket.CategoryChoices.OTHER,
        )

        self.tag = SupportTag.objects.create(
            name="Refund",
        )

    def create_user(
        self,
        *,
        phone,
        email,
        full_name,
        is_staff=False,
    ):
        user = User(
            phone=phone,
            email=email,
            full_name=full_name,
            is_active=True,
            is_staff=is_staff,
        )

        user.set_password("testpass123")
        user.save()

        return user

    def get_api_client(self) -> APIClient:
        return cast(
            APIClient,
            self.client,
        )

    def authenticate(self, user):
        self.get_api_client().force_authenticate(user=user)

    def test_regular_django_staff_is_not_support_staff(self):
        self.authenticate(self.regular_staff)

        url = reverse(
            "support-ticket-assign",
            args=[self.ticket.pk],
        )

        response = self.client.post(
            url,
            data={
                "assigned_to": self.support_manager.pk,
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN,
        )

        self.ticket.refresh_from_db()

        self.assertIsNone(self.ticket.assigned_to)

    def test_support_agent_cannot_assign_ticket(self):
        self.authenticate(self.support_agent)

        url = reverse(
            "support-ticket-assign",
            args=[self.ticket.pk],
        )

        response = self.client.post(
            url,
            data={
                "assigned_to": self.support_agent.pk,
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN,
        )

        self.ticket.refresh_from_db()

        self.assertIsNone(self.ticket.assigned_to)

    def test_support_manager_can_assign_ticket(self):
        self.authenticate(self.support_manager)

        url = reverse(
            "support-ticket-assign",
            args=[self.ticket.pk],
        )

        response = self.client.post(
            url,
            data={
                "assigned_to": self.support_agent.pk,
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )

        self.ticket.refresh_from_db()

        self.assertEqual(
            self.ticket.assigned_to,
            self.support_agent,
        )

    def test_customer_cannot_patch_ticket(self):
        self.authenticate(self.customer)

        url = reverse(
            "support-ticket-detail",
            args=[self.ticket.pk],
        )

        response = self.client.patch(
            url,
            data={
                "subject": "Changed subject",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_405_METHOD_NOT_ALLOWED,
        )

        self.ticket.refresh_from_db()

        self.assertEqual(
            self.ticket.subject,
            "Existing support ticket",
        )

    def test_customer_cannot_delete_ticket(self):
        self.authenticate(self.customer)

        url = reverse(
            "support-ticket-detail",
            args=[self.ticket.pk],
        )

        response = self.client.delete(url)

        self.assertEqual(
            response.status_code,
            status.HTTP_405_METHOD_NOT_ALLOWED,
        )

        self.assertTrue(SupportTicket.objects.filter(pk=self.ticket.pk).exists())

    def test_customer_cannot_choose_priority_when_creating_ticket(
        self,
    ):
        self.authenticate(self.customer)

        url = reverse("support-ticket-list")

        response = self.client.post(
            url,
            data={
                "subject": "Urgent please",
                "category": (SupportTicket.CategoryChoices.OTHER),
                "priority": (SupportTicket.PriorityChoices.URGENT),
                "initial_message": ("Please make this urgent."),
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_201_CREATED,
        )

        ticket = SupportTicket.objects.exclude(pk=self.ticket.pk).get()

        self.assertEqual(
            ticket.priority,
            SupportTicket.PriorityChoices.NORMAL,
        )

    def test_customer_cannot_assign_tags_during_ticket_creation(
        self,
    ):
        self.authenticate(self.customer)

        url = reverse("support-ticket-list")

        response = self.client.post(
            url,
            data={
                "subject": "Trying tags",
                "category": (SupportTicket.CategoryChoices.OTHER),
                "initial_message": ("Test message."),
                "tags": [
                    self.tag.pk,
                ],
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_201_CREATED,
        )

        ticket = SupportTicket.objects.exclude(pk=self.ticket.pk).get()

        self.assertFalse(ticket.tags.exists())

    def test_ticket_cannot_be_assigned_to_regular_staff_user(
        self,
    ):
        self.authenticate(self.support_manager)

        url = reverse(
            "support-ticket-assign",
            args=[self.ticket.pk],
        )

        response = self.client.post(
            url,
            data={
                "assigned_to": self.regular_staff.pk,
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )

        self.ticket.refresh_from_db()

        self.assertIsNone(self.ticket.assigned_to)
