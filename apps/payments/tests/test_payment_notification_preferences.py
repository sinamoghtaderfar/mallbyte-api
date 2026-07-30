from decimal import Decimal
from typing import cast

from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from apps.accounts.models import User
from apps.notifications.models import Notification, NotificationPreference
from apps.orders.models import Order
from apps.payments.models import Payment


class PaymentNotificationPreferenceIntegrationTests(APITestCase):
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
            phone="+989830000001",
            email="admin_payment_pref@example.com",
            full_name="Payment Preference Admin",
            is_staff=True,
            is_superuser=True,
        )

        self.customer = self.create_test_user(
            phone="+989830000002",
            email="customer_payment_pref@example.com",
            full_name="Payment Preference Customer",
        )

        NotificationPreference.objects.create(
            user=self.customer,
            muted_notification_types=[
                Notification.NotificationType.PAYMENT,
            ],
        )

    def get_api_client(self) -> APIClient:
        return cast(APIClient, self.client)

    def authenticate_customer(self):
        self.get_api_client().force_authenticate(user=self.customer)

    def create_order(self):
        return Order.objects.create(
            user=self.customer,
            status=Order.StatusChoices.PENDING_PAYMENT,
            payment_status=Order.PaymentStatusChoices.UNPAID,
            subtotal=Decimal("100000"),
            discount_amount=Decimal("0"),
            shipping_cost=Decimal("0"),
            tax_amount=Decimal("0"),
            total_amount=Decimal("100000"),
            receiver_name="Payment Preference Customer",
            receiver_phone="+989830000002",
            province="Tehran",
            city="Tehran",
            address="Customer test address",
            postal_code="1234567890",
            customer_note="",
            admin_note="",
        )

    def create_payment(self):
        order = self.create_order()

        return Payment.objects.create(
            order=order,
            user=self.customer,
            provider=Payment.ProviderChoices.MOCK,
            status=Payment.StatusChoices.PENDING,
            amount=order.total_amount,
            currency="IRR",
            created_by=self.customer,
        )

    def assert_payment_notification_does_not_exist(self, *, payment, title):
        self.assertFalse(
            Notification.objects.filter(
                user=self.customer,
                notification_type=Notification.NotificationType.PAYMENT,
                related_object_type="payment",
                related_object_id=str(payment.pk),
                title=title,
            ).exists()
        )

    def test_muted_payment_type_blocks_payment_successful_notification(self):
        payment = self.create_payment()

        self.authenticate_customer()

        url = reverse("payment-mark-success", args=[payment.pk])

        response = self.client.post(
            url,
            data={
                "gateway_reference": "MOCK-PAYMENT-PREF-001",
                "gateway_response": {
                    "status": "ok",
                },
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        payment.refresh_from_db()

        self.assertEqual(payment.status, Payment.StatusChoices.SUCCESS)

        self.assert_payment_notification_does_not_exist(
            payment=payment,
            title="Payment successful",
        )

    def test_muted_payment_type_blocks_payment_failed_notification(self):
        payment = self.create_payment()

        self.authenticate_customer()

        url = reverse("payment-mark-failed", args=[payment.pk])

        response = self.client.post(
            url,
            data={
                "reason": "Gateway declined payment.",
                "gateway_response": {
                    "status": "failed",
                },
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        payment.refresh_from_db()

        self.assertEqual(payment.status, Payment.StatusChoices.FAILED)

        self.assert_payment_notification_does_not_exist(
            payment=payment,
            title="Payment failed",
        )

    def test_muted_payment_type_blocks_payment_cancelled_notification(self):
        payment = self.create_payment()

        self.authenticate_customer()

        url = reverse("payment-cancel", args=[payment.pk])

        response = self.client.post(
            url,
            data={
                "reason": "Customer cancelled payment.",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        payment.refresh_from_db()

        self.assertEqual(payment.status, Payment.StatusChoices.CANCELLED)

        self.assert_payment_notification_does_not_exist(
            payment=payment,
            title="Payment cancelled",
        )
