from decimal import Decimal
from typing import cast

from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from apps.accounts.models import User
from apps.notifications.models import Notification, NotificationPreference
from apps.orders.models import Order
from apps.products.models import Category, Product
from apps.support.models import SupportTicket, TicketMessage


class SupportTicketNotificationTests(APITestCase):
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
            phone="+989940000001",
            email="support_notification_admin@example.com",
            full_name="Support Notification Admin",
            is_staff=True,
            is_superuser=True,
        )

        self.support_staff = self.create_test_user(
            phone="+989940000002",
            email="support_notification_staff@example.com",
            full_name="Support Notification Staff",
            is_staff=True,
        )

        self.customer = self.create_test_user(
            phone="+989940000003",
            email="support_notification_customer@example.com",
            full_name="Support Notification Customer",
        )

        self.category = Category.objects.create(
            name="Support Notification Category",
            description="Category for support notification tests",
            is_active=True,
        )

        self.product = Product.objects.create(
            seller=self.admin_user,
            category=self.category,
            name="Support Notification Product",
            description="Product for support notification tests",
            price=Decimal("100000"),
            status=Product.StatusChoices.APPROVED,
            is_active=True,
            sku="SUPPORT-NOTIFICATION-SKU-001",
        )

        self.order = Order.objects.create(
            user=self.customer,
            status=Order.StatusChoices.DELIVERED,
            payment_status=Order.PaymentStatusChoices.PAID,
            subtotal=Decimal("100000"),
            discount_amount=Decimal("0"),
            shipping_cost=Decimal("0"),
            tax_amount=Decimal("0"),
            receiver_name="Support Notification Customer",
            receiver_phone="+989940000003",
            province="Tehran",
            city="Tehran",
            address="Support notification address",
            postal_code="1234567890",
        )

    def get_api_client(self) -> APIClient:
        return cast(APIClient, self.client)

    def authenticate_customer(self):
        self.get_api_client().force_authenticate(user=self.customer)

    def authenticate_staff(self):
        self.get_api_client().force_authenticate(user=self.support_staff)

    def create_ticket(self, *, assigned_to=None):
        ticket = SupportTicket.objects.create(
            customer=self.customer,
            assigned_to=assigned_to,
            subject="Support notification ticket",
            category=SupportTicket.CategoryChoices.ORDER,
            priority=SupportTicket.PriorityChoices.NORMAL,
            order=self.order,
            product=self.product,
        )

        TicketMessage.objects.create(
            ticket=ticket,
            sender=self.customer,
            message="Initial support message.",
        )

        return ticket

    def assert_support_notification_exists(self, *, user, ticket, title, template_key):
        self.assertTrue(
            Notification.objects.filter(
                user=user,
                notification_type=Notification.NotificationType.SUPPORT,
                related_object_type="support_ticket",
                related_object_id=str(ticket.pk),
                title=title,
                metadata__template_key=template_key,
            ).exists()
        )

    def test_ticket_creation_creates_customer_notification(self):
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
                "initial_message": "My order arrived damaged.",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        ticket = SupportTicket.objects.get(customer=self.customer)

        self.assert_support_notification_exists(
            user=self.customer,
            ticket=ticket,
            title="Support ticket created",
            template_key="support_ticket_created",
        )

    def test_staff_reply_creates_customer_notification(self):
        ticket = self.create_ticket(assigned_to=self.support_staff)

        self.authenticate_staff()

        url = reverse("support-ticket-reply", args=[ticket.pk])

        response = self.client.post(
            url,
            data={
                "message": "We are checking your issue.",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        self.assert_support_notification_exists(
            user=self.customer,
            ticket=ticket,
            title="Support replied",
            template_key="support_ticket_staff_replied",
        )

    def test_customer_reply_creates_assigned_staff_notification(self):
        ticket = self.create_ticket(assigned_to=self.support_staff)

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

        self.assert_support_notification_exists(
            user=self.support_staff,
            ticket=ticket,
            title="Customer replied",
            template_key="support_ticket_customer_replied",
        )

    def test_internal_note_does_not_create_notification(self):
        ticket = self.create_ticket(assigned_to=self.support_staff)

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

        self.assertFalse(
            Notification.objects.filter(
                related_object_type="support_ticket",
                related_object_id=str(ticket.pk),
                title__in=[
                    "Support replied",
                    "Customer replied",
                ],
            ).exists()
        )

    def test_assign_ticket_creates_staff_notification(self):
        ticket = self.create_ticket()

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

        self.assert_support_notification_exists(
            user=self.support_staff,
            ticket=ticket,
            title="Support ticket assigned",
            template_key="support_ticket_assigned",
        )

    def test_resolve_close_and_reopen_create_customer_notifications(self):
        ticket = self.create_ticket(assigned_to=self.support_staff)

        self.authenticate_staff()

        resolve_url = reverse("support-ticket-resolve", args=[ticket.pk])
        close_url = reverse("support-ticket-close", args=[ticket.pk])
        reopen_url = reverse("support-ticket-reopen", args=[ticket.pk])

        resolve_response = self.client.post(resolve_url, data={}, format="json")
        self.assertEqual(resolve_response.status_code, status.HTTP_200_OK)

        self.assert_support_notification_exists(
            user=self.customer,
            ticket=ticket,
            title="Support ticket resolved",
            template_key="support_ticket_resolved",
        )

        close_response = self.client.post(close_url, data={}, format="json")
        self.assertEqual(close_response.status_code, status.HTTP_200_OK)

        self.assert_support_notification_exists(
            user=self.customer,
            ticket=ticket,
            title="Support ticket closed",
            template_key="support_ticket_closed",
        )

        reopen_response = self.client.post(reopen_url, data={}, format="json")
        self.assertEqual(reopen_response.status_code, status.HTTP_200_OK)

        self.assert_support_notification_exists(
            user=self.customer,
            ticket=ticket,
            title="Support ticket reopened",
            template_key="support_ticket_reopened",
        )

    def test_muted_support_notifications_block_ticket_creation_notification(self):
        NotificationPreference.objects.create(
            user=self.customer,
            muted_notification_types=[
                Notification.NotificationType.SUPPORT,
            ],
        )

        self.authenticate_customer()

        url = reverse("support-ticket-list")

        response = self.client.post(
            url,
            data={
                "subject": "Muted support ticket",
                "category": SupportTicket.CategoryChoices.ORDER,
                "priority": SupportTicket.PriorityChoices.NORMAL,
                "order": self.order.pk,
                "product": self.product.pk,
                "initial_message": "This should not create a notification.",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        ticket = SupportTicket.objects.get(customer=self.customer)

        self.assertFalse(
            Notification.objects.filter(
                user=self.customer,
                related_object_type="support_ticket",
                related_object_id=str(ticket.pk),
                title="Support ticket created",
            ).exists()
        )