from typing import cast

from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from apps.accounts.models import User
from apps.support.models import SupportTicket


class SupportTicketSummaryTests(APITestCase):
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
            phone="+989960000001",
            email="support_summary_staff@example.com",
            full_name="Support Summary Staff",
            is_staff=True,
        )

        self.other_staff = self.create_test_user(
            phone="+989960000002",
            email="other_support_summary_staff@example.com",
            full_name="Other Support Summary Staff",
            is_staff=True,
        )

        self.customer = self.create_test_user(
            phone="+989960000003",
            email="support_summary_customer@example.com",
            full_name="Support Summary Customer",
        )

        self.other_customer = self.create_test_user(
            phone="+989960000004",
            email="other_support_summary_customer@example.com",
            full_name="Other Support Summary Customer",
        )

        self.open_high_order_ticket = SupportTicket.objects.create(
            customer=self.customer,
            assigned_to=self.support_staff,
            subject="Open high order ticket",
            category=SupportTicket.CategoryChoices.ORDER,
            priority=SupportTicket.PriorityChoices.HIGH,
            status=SupportTicket.StatusChoices.OPEN,
        )

        self.pending_urgent_payment_ticket = SupportTicket.objects.create(
            customer=self.customer,
            assigned_to=None,
            subject="Pending urgent payment ticket",
            category=SupportTicket.CategoryChoices.PAYMENT,
            priority=SupportTicket.PriorityChoices.URGENT,
            status=SupportTicket.StatusChoices.PENDING,
        )

        self.resolved_low_product_ticket = SupportTicket.objects.create(
            customer=self.other_customer,
            assigned_to=self.support_staff,
            subject="Resolved low product ticket",
            category=SupportTicket.CategoryChoices.PRODUCT,
            priority=SupportTicket.PriorityChoices.LOW,
            status=SupportTicket.StatusChoices.RESOLVED,
        )

        self.closed_normal_account_ticket = SupportTicket.objects.create(
            customer=self.other_customer,
            assigned_to=self.other_staff,
            subject="Closed normal account ticket",
            category=SupportTicket.CategoryChoices.ACCOUNT,
            priority=SupportTicket.PriorityChoices.NORMAL,
            status=SupportTicket.StatusChoices.CLOSED,
        )

    def get_api_client(self) -> APIClient:
        return cast(APIClient, self.client)

    def authenticate_customer(self):
        self.get_api_client().force_authenticate(user=self.customer)

    def authenticate_staff(self):
        self.get_api_client().force_authenticate(user=self.support_staff)

    def test_customer_summary_only_counts_own_tickets(self):
        self.authenticate_customer()

        url = reverse("support-ticket-summary")

        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()

        self.assertEqual(data["status"]["total"], 2)
        self.assertEqual(data["status"]["open"], 1)
        self.assertEqual(data["status"]["pending"], 1)
        self.assertEqual(data["status"]["resolved"], 0)
        self.assertEqual(data["status"]["closed"], 0)

        self.assertEqual(data["priority"]["high"], 1)
        self.assertEqual(data["priority"]["urgent"], 1)
        self.assertEqual(data["priority"]["low"], 0)
        self.assertEqual(data["priority"]["normal"], 0)

        self.assertEqual(data["category"]["order"], 1)
        self.assertEqual(data["category"]["payment"], 1)
        self.assertEqual(data["category"]["product"], 0)
        self.assertEqual(data["category"]["account"], 0)

        self.assertEqual(data["unassigned"], 1)
        self.assertEqual(data["assigned_to_me"], 0)

    def test_staff_summary_counts_all_tickets(self):
        self.authenticate_staff()

        url = reverse("support-ticket-summary")

        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()

        self.assertEqual(data["status"]["total"], 4)
        self.assertEqual(data["status"]["open"], 1)
        self.assertEqual(data["status"]["pending"], 1)
        self.assertEqual(data["status"]["resolved"], 1)
        self.assertEqual(data["status"]["closed"], 1)

        self.assertEqual(data["priority"]["high"], 1)
        self.assertEqual(data["priority"]["urgent"], 1)
        self.assertEqual(data["priority"]["low"], 1)
        self.assertEqual(data["priority"]["normal"], 1)

        self.assertEqual(data["category"]["order"], 1)
        self.assertEqual(data["category"]["payment"], 1)
        self.assertEqual(data["category"]["product"], 1)
        self.assertEqual(data["category"]["account"], 1)

        self.assertEqual(data["unassigned"], 1)
        self.assertEqual(data["assigned_to_me"], 2)

    def test_summary_respects_status_filter(self):
        self.authenticate_staff()

        url = reverse("support-ticket-summary")

        response = self.client.get(
            url,
            data={
                "status": SupportTicket.StatusChoices.OPEN,
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()

        self.assertEqual(data["status"]["total"], 1)
        self.assertEqual(data["status"]["open"], 1)
        self.assertEqual(data["status"]["pending"], 0)
        self.assertEqual(data["status"]["resolved"], 0)
        self.assertEqual(data["status"]["closed"], 0)

    def test_summary_respects_assigned_to_me_filter(self):
        self.authenticate_staff()

        url = reverse("support-ticket-summary")

        response = self.client.get(
            url,
            data={
                "assigned_to": "me",
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()

        self.assertEqual(data["status"]["total"], 2)
        self.assertEqual(data["status"]["open"], 1)
        self.assertEqual(data["status"]["resolved"], 1)
        self.assertEqual(data["assigned_to_me"], 2)
        self.assertEqual(data["unassigned"], 0)

    def test_anonymous_user_cannot_access_summary(self):
        url = reverse("support-ticket-summary")

        response = self.client.get(url)

        self.assertIn(
            response.status_code,
            [
                status.HTTP_401_UNAUTHORIZED,
                status.HTTP_403_FORBIDDEN,
            ],
        )