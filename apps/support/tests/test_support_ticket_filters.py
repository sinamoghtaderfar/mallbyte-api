from typing import cast

from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from apps.accounts.models import User
from apps.support.models import SupportTicket


class SupportTicketFilterTests(APITestCase):
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
            phone="+989950000001",
            email="support_filter_staff@example.com",
            full_name="Support Filter Staff",
            is_staff=True,
        )

        self.other_staff = self.create_test_user(
            phone="+989950000002",
            email="other_support_filter_staff@example.com",
            full_name="Other Support Filter Staff",
            is_staff=True,
        )

        self.customer = self.create_test_user(
            phone="+989950000003",
            email="support_filter_customer@example.com",
            full_name="Support Filter Customer",
        )

        self.other_customer = self.create_test_user(
            phone="+989950000004",
            email="other_support_filter_customer@example.com",
            full_name="Other Support Filter Customer",
        )

        self.open_high_ticket = SupportTicket.objects.create(
            customer=self.customer,
            assigned_to=self.support_staff,
            subject="Open high order ticket",
            category=SupportTicket.CategoryChoices.ORDER,
            priority=SupportTicket.PriorityChoices.HIGH,
            status=SupportTicket.StatusChoices.OPEN,
        )

        self.pending_urgent_ticket = SupportTicket.objects.create(
            customer=self.customer,
            assigned_to=self.other_staff,
            subject="Pending urgent payment ticket",
            category=SupportTicket.CategoryChoices.PAYMENT,
            priority=SupportTicket.PriorityChoices.URGENT,
            status=SupportTicket.StatusChoices.PENDING,
        )

        self.resolved_low_ticket = SupportTicket.objects.create(
            customer=self.other_customer,
            assigned_to=self.support_staff,
            subject="Resolved low product ticket",
            category=SupportTicket.CategoryChoices.PRODUCT,
            priority=SupportTicket.PriorityChoices.LOW,
            status=SupportTicket.StatusChoices.RESOLVED,
        )

    def get_api_client(self) -> APIClient:
        return cast(APIClient, self.client)

    def authenticate_customer(self):
        self.get_api_client().force_authenticate(user=self.customer)

    def authenticate_staff(self):
        self.get_api_client().force_authenticate(user=self.support_staff)

    def get_response_items(self, response):
        data = response.json()

        if isinstance(data, dict) and "results" in data:
            return data["results"]

        return data

    def get_ids(self, response):
        return {item["id"] for item in self.get_response_items(response)}

    def test_customer_filters_only_own_tickets(self):
        self.authenticate_customer()

        url = reverse("support-ticket-list")

        response = self.client.get(
            url,
            data={
                "status": SupportTicket.StatusChoices.RESOLVED,
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        ids = self.get_ids(response)

        self.assertNotIn(self.resolved_low_ticket.id, ids)
        self.assertNotIn(self.open_high_ticket.id, ids)
        self.assertNotIn(self.pending_urgent_ticket.id, ids)

    def test_staff_can_filter_by_status(self):
        self.authenticate_staff()

        url = reverse("support-ticket-list")

        response = self.client.get(
            url,
            data={
                "status": SupportTicket.StatusChoices.OPEN,
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        ids = self.get_ids(response)

        self.assertIn(self.open_high_ticket.id, ids)
        self.assertNotIn(self.pending_urgent_ticket.id, ids)
        self.assertNotIn(self.resolved_low_ticket.id, ids)

    def test_staff_can_filter_by_priority(self):
        self.authenticate_staff()

        url = reverse("support-ticket-list")

        response = self.client.get(
            url,
            data={
                "priority": SupportTicket.PriorityChoices.URGENT,
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        ids = self.get_ids(response)

        self.assertIn(self.pending_urgent_ticket.id, ids)
        self.assertNotIn(self.open_high_ticket.id, ids)
        self.assertNotIn(self.resolved_low_ticket.id, ids)

    def test_staff_can_filter_by_category(self):
        self.authenticate_staff()

        url = reverse("support-ticket-list")

        response = self.client.get(
            url,
            data={
                "category": SupportTicket.CategoryChoices.PRODUCT,
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        ids = self.get_ids(response)

        self.assertIn(self.resolved_low_ticket.id, ids)
        self.assertNotIn(self.open_high_ticket.id, ids)
        self.assertNotIn(self.pending_urgent_ticket.id, ids)

    def test_staff_can_filter_by_assigned_to_me(self):
        self.authenticate_staff()

        url = reverse("support-ticket-list")

        response = self.client.get(
            url,
            data={
                "assigned_to": "me",
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        ids = self.get_ids(response)

        self.assertIn(self.open_high_ticket.id, ids)
        self.assertIn(self.resolved_low_ticket.id, ids)
        self.assertNotIn(self.pending_urgent_ticket.id, ids)

    def test_staff_can_filter_by_customer(self):
        self.authenticate_staff()

        url = reverse("support-ticket-list")

        response = self.client.get(
            url,
            data={
                "customer": self.other_customer.pk,
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        ids = self.get_ids(response)

        self.assertIn(self.resolved_low_ticket.id, ids)
        self.assertNotIn(self.open_high_ticket.id, ids)
        self.assertNotIn(self.pending_urgent_ticket.id, ids)

    def test_staff_can_order_by_created_at_desc(self):
        self.authenticate_staff()

        url = reverse("support-ticket-list")

        response = self.client.get(
            url,
            data={
                "ordering": "-created_at",
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        items = self.get_response_items(response)

        self.assertGreaterEqual(len(items), 3)