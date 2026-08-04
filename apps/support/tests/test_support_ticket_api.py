from decimal import Decimal
from typing import cast

from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from apps.accounts.models import User
from apps.orders.models import Order
from apps.products.models import Category, Product
from apps.support.models import SupportTicket, TicketMessage


class SupportTicketAPITests(APITestCase):
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
        self.admin_user = self.create_test_user(
            phone="+989930000001",
            email="support_admin@example.com",
            full_name="Support Admin",
            is_staff=True,
            is_superuser=True,
        )

        self.support_staff = self.create_test_user(
            phone="+989930000002",
            email="support_staff@example.com",
            full_name="Support Staff",
            is_staff=True,
        )

        self.customer = self.create_test_user(
            phone="+989930000003",
            email="support_customer@example.com",
            full_name="Support Customer",
        )

        self.other_customer = self.create_test_user(
            phone="+989930000004",
            email="other_support_customer@example.com",
            full_name="Other Support Customer",
        )

        self.category = Category.objects.create(
            name="Support Category",
            description="Category for support tests",
            is_active=True,
        )

        self.product = Product.objects.create(
            seller=self.admin_user,
            category=self.category,
            name="Support Product",
            description="Product for support tests",
            price=Decimal("100000"),
            status=Product.StatusChoices.APPROVED,
            is_active=True,
            sku="SUPPORT-SKU-001",
        )

        self.order = Order.objects.create(
            user=self.customer,
            status=Order.StatusChoices.DELIVERED,
            payment_status=Order.PaymentStatusChoices.PAID,
            subtotal=Decimal("100000"),
            discount_amount=Decimal("0"),
            shipping_cost=Decimal("0"),
            tax_amount=Decimal("0"),
            receiver_name="Support Customer",
            receiver_phone="+989930000003",
            province="Tehran",
            city="Tehran",
            address="Support address",
            postal_code="1234567890",
        )

        self.other_order = Order.objects.create(
            user=self.other_customer,
            status=Order.StatusChoices.DELIVERED,
            payment_status=Order.PaymentStatusChoices.PAID,
            subtotal=Decimal("100000"),
            discount_amount=Decimal("0"),
            shipping_cost=Decimal("0"),
            tax_amount=Decimal("0"),
            receiver_name="Other Support Customer",
            receiver_phone="+989930000004",
            province="Tehran",
            city="Tehran",
            address="Other support address",
            postal_code="1234567890",
        )

    def get_api_client(self) -> APIClient:
        return cast(APIClient, self.client)

    def authenticate_customer(self):
        self.get_api_client().force_authenticate(user=self.customer)

    def authenticate_other_customer(self):
        self.get_api_client().force_authenticate(user=self.other_customer)

    def authenticate_staff(self):
        self.get_api_client().force_authenticate(user=self.support_staff)

    def create_ticket(self, *, customer=None, assigned_to=None):
        customer = customer or self.customer

        ticket = SupportTicket.objects.create(
            customer=customer,
            assigned_to=assigned_to,
            subject="Existing support ticket",
            category=SupportTicket.CategoryChoices.ORDER,
            priority=SupportTicket.PriorityChoices.NORMAL,
            order=self.order if customer == self.customer else self.other_order,
            product=self.product,
            last_message_at=None,
        )

        TicketMessage.objects.create(
            ticket=ticket,
            sender=customer,
            message="Initial message.",
        )

        return ticket

    def get_response_items(self, response):
        data = response.json()

        if isinstance(data, dict) and "results" in data:
            return data["results"]

        return data

    def test_customer_can_create_support_ticket(self):
        self.authenticate_customer()

        url = reverse("support-ticket-list")

        response = self.client.post(
            url,
            data={
                "subject": "Problem with my order",
                "category": SupportTicket.CategoryChoices.ORDER,
                "priority": SupportTicket.PriorityChoices.HIGH,
                "order": self.order.pk,
                "product": self.product.pk,
                "initial_message": "My package arrived damaged.",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        ticket = SupportTicket.objects.get(customer=self.customer)

        self.assertTrue(ticket.ticket_number.startswith("SUP-"))
        self.assertEqual(ticket.subject, "Problem with my order")
        self.assertEqual(ticket.status, SupportTicket.StatusChoices.OPEN)
        self.assertEqual(ticket.messages.count(), 1)

        message = ticket.messages.first()

        self.assertEqual(message.sender, self.customer)
        self.assertEqual(message.message, "My package arrived damaged.")

    def test_customer_cannot_create_ticket_for_other_customer_order(self):
        self.authenticate_customer()

        url = reverse("support-ticket-list")

        response = self.client.post(
            url,
            data={
                "subject": "Wrong order ticket",
                "category": SupportTicket.CategoryChoices.ORDER,
                "priority": SupportTicket.PriorityChoices.NORMAL,
                "order": self.other_order.pk,
                "initial_message": "This should fail.",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(SupportTicket.objects.count(), 0)

    def test_customer_only_sees_own_tickets(self):
        own_ticket = self.create_ticket(customer=self.customer)
        other_ticket = self.create_ticket(customer=self.other_customer)

        self.authenticate_customer()

        url = reverse("support-ticket-list")

        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        items = self.get_response_items(response)
        ids = {item["id"] for item in items}

        self.assertIn(own_ticket.id, ids)
        self.assertNotIn(other_ticket.id, ids)

    def test_customer_cannot_retrieve_other_customer_ticket(self):
        other_ticket = self.create_ticket(customer=self.other_customer)

        self.authenticate_customer()

        url = reverse("support-ticket-detail", args=[other_ticket.pk])

        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_staff_can_see_all_tickets(self):
        own_ticket = self.create_ticket(customer=self.customer)
        other_ticket = self.create_ticket(customer=self.other_customer)

        self.authenticate_staff()

        url = reverse("support-ticket-list")

        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        items = self.get_response_items(response)
        ids = {item["id"] for item in items}

        self.assertIn(own_ticket.id, ids)
        self.assertIn(other_ticket.id, ids)

    def test_customer_can_reply_to_own_ticket(self):
        ticket = self.create_ticket(customer=self.customer)

        self.authenticate_customer()

        url = reverse("support-ticket-reply", args=[ticket.pk])

        response = self.client.post(
            url,
            data={
                "message": "Here is more information.",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        ticket.refresh_from_db()

        self.assertEqual(ticket.status, SupportTicket.StatusChoices.OPEN)
        self.assertEqual(ticket.messages.count(), 2)
        self.assertEqual(ticket.messages.last().sender, self.customer)
        self.assertEqual(ticket.messages.last().message, "Here is more information.")

    def test_staff_reply_sets_ticket_to_pending(self):
        ticket = self.create_ticket(customer=self.customer)

        self.authenticate_staff()

        url = reverse("support-ticket-reply", args=[ticket.pk])

        response = self.client.post(
            url,
            data={
                "message": "We are checking this issue.",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        ticket.refresh_from_db()

        self.assertEqual(ticket.status, SupportTicket.StatusChoices.PENDING)
        self.assertEqual(ticket.messages.count(), 2)
        self.assertEqual(ticket.messages.last().sender, self.support_staff)

    def test_customer_cannot_create_internal_note(self):
        ticket = self.create_ticket(customer=self.customer)

        self.authenticate_customer()

        url = reverse("support-ticket-reply", args=[ticket.pk])

        response = self.client.post(
            url,
            data={
                "message": "Trying internal note.",
                "is_internal_note": True,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        self.assertEqual(ticket.messages.count(), 1)

    def test_staff_can_create_internal_note(self):
        ticket = self.create_ticket(customer=self.customer)

        self.authenticate_staff()

        url = reverse("support-ticket-reply", args=[ticket.pk])

        response = self.client.post(
            url,
            data={
                "message": "Internal investigation note.",
                "is_internal_note": True,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        ticket.refresh_from_db()

        self.assertEqual(ticket.messages.count(), 2)

        internal_note = ticket.messages.last()

        self.assertTrue(internal_note.is_internal_note)
        self.assertEqual(ticket.status, SupportTicket.StatusChoices.OPEN)

    def test_customer_does_not_see_internal_notes(self):
        ticket = self.create_ticket(customer=self.customer)

        TicketMessage.objects.create(
            ticket=ticket,
            sender=self.support_staff,
            message="Internal note for staff only.",
            is_internal_note=True,
        )

        self.authenticate_customer()

        url = reverse("support-ticket-detail", args=[ticket.pk])

        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        messages = response.json()["messages"]

        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0]["message"], "Initial message.")

    def test_staff_can_assign_ticket(self):
        ticket = self.create_ticket(customer=self.customer)

        self.authenticate_staff()

        url = reverse("support-ticket-assign", args=[ticket.pk])

        response = self.client.post(
            url,
            data={
                "assigned_to": self.support_staff.pk,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        ticket.refresh_from_db()

        self.assertEqual(ticket.assigned_to, self.support_staff)

    def test_customer_cannot_assign_ticket(self):
        ticket = self.create_ticket(customer=self.customer)

        self.authenticate_customer()

        url = reverse("support-ticket-assign", args=[ticket.pk])

        response = self.client.post(
            url,
            data={
                "assigned_to": self.support_staff.pk,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        ticket.refresh_from_db()

        self.assertIsNone(ticket.assigned_to)

    def test_staff_can_resolve_close_and_reopen_ticket(self):
        ticket = self.create_ticket(customer=self.customer)

        self.authenticate_staff()

        resolve_url = reverse("support-ticket-resolve", args=[ticket.pk])
        close_url = reverse("support-ticket-close", args=[ticket.pk])
        reopen_url = reverse("support-ticket-reopen", args=[ticket.pk])

        resolve_response = self.client.post(resolve_url, data={}, format="json")

        self.assertEqual(resolve_response.status_code, status.HTTP_200_OK)

        ticket.refresh_from_db()

        self.assertEqual(ticket.status, SupportTicket.StatusChoices.RESOLVED)
        self.assertIsNotNone(ticket.resolved_at)

        close_response = self.client.post(close_url, data={}, format="json")

        self.assertEqual(close_response.status_code, status.HTTP_200_OK)

        ticket.refresh_from_db()

        self.assertEqual(ticket.status, SupportTicket.StatusChoices.CLOSED)
        self.assertIsNotNone(ticket.closed_at)

        reopen_response = self.client.post(reopen_url, data={}, format="json")

        self.assertEqual(reopen_response.status_code, status.HTTP_200_OK)

        ticket.refresh_from_db()

        self.assertEqual(ticket.status, SupportTicket.StatusChoices.OPEN)
        self.assertIsNone(ticket.resolved_at)
        self.assertIsNone(ticket.closed_at)

    def test_cannot_reply_to_closed_ticket(self):
        ticket = self.create_ticket(customer=self.customer)
        ticket.close()

        self.authenticate_customer()

        url = reverse("support-ticket-reply", args=[ticket.pk])

        response = self.client.post(
            url,
            data={
                "message": "Can I still reply?",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        data = response.json()

        self.assertEqual(data["detail"], "Cannot reply to a closed ticket. Reopen it first.")

        ticket.refresh_from_db()

        self.assertEqual(ticket.messages.count(), 1)