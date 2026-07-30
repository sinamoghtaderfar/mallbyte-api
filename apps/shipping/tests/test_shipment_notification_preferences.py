from decimal import Decimal
from typing import cast

from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from apps.accounts.models import User
from apps.notifications.models import Notification, NotificationPreference
from apps.orders.models import Order
from apps.shipping.models import Shipment


class ShipmentNotificationPreferenceIntegrationTests(APITestCase):
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
            phone="+989840000001",
            email="admin_shipping_pref@example.com",
            full_name="Shipping Preference Admin",
            is_staff=True,
            is_superuser=True,
        )

        self.customer = self.create_test_user(
            phone="+989840000002",
            email="customer_shipping_pref@example.com",
            full_name="Shipping Preference Customer",
        )

        self.order = Order.objects.create(
            user=self.customer,
            status=Order.StatusChoices.PAID,
            payment_status=Order.PaymentStatusChoices.PAID,
            subtotal=Decimal("100000"),
            discount_amount=Decimal("0"),
            shipping_cost=Decimal("10000"),
            tax_amount=Decimal("0"),
            receiver_name="Shipping Preference Customer",
            receiver_phone="+989840000002",
            province="Tehran",
            city="Tehran",
            address="Customer shipping address",
            postal_code="1234567890",
        )

        NotificationPreference.objects.create(
            user=self.customer,
            muted_notification_types=[
                Notification.NotificationType.SHIPPING,
            ],
        )

    def get_api_client(self) -> APIClient:
        return cast(APIClient, self.client)

    def authenticate_admin(self):
        self.get_api_client().force_authenticate(user=self.admin_user)

    def create_shipment(self):
        return Shipment.create_from_order(
            order=self.order,
            created_by=self.admin_user,
            carrier=Shipment.CarrierChoices.DHL,
        )

    def assert_shipment_notification_does_not_exist(self, *, shipment, title):
        self.assertFalse(
            Notification.objects.filter(
                user=self.customer,
                notification_type=Notification.NotificationType.SHIPPING,
                related_object_type="shipment",
                related_object_id=str(shipment.pk),
                title=title,
            ).exists()
        )

    def test_muted_shipping_type_blocks_shipment_created_notification(self):
        self.authenticate_admin()

        url = reverse("shipment-list")

        response = self.client.post(
            url,
            data={
                "order": self.order.pk,
                "carrier": Shipment.CarrierChoices.DHL,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        shipment = Shipment.objects.get(order=self.order)

        self.assert_shipment_notification_does_not_exist(
            shipment=shipment,
            title="Shipment created",
        )

    def test_muted_shipping_type_blocks_shipment_ready_notification(self):
        self.authenticate_admin()

        shipment = self.create_shipment()

        url = reverse("shipment-mark-ready", args=[shipment.pk])

        response = self.client.post(
            url,
            data={
                "note": "Package prepared.",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        shipment.refresh_from_db()

        self.assertEqual(shipment.status, Shipment.StatusChoices.READY_TO_SHIP)

        self.assert_shipment_notification_does_not_exist(
            shipment=shipment,
            title="Shipment ready",
        )

    def test_muted_shipping_type_blocks_shipment_shipped_notification(self):
        self.authenticate_admin()

        shipment = self.create_shipment()

        url = reverse("shipment-mark-shipped", args=[shipment.pk])

        response = self.client.post(
            url,
            data={
                "tracking_number": "DHL123456",
                "tracking_url": "https://tracking.example.com/DHL123456",
                "note": "Package handed to carrier.",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        shipment.refresh_from_db()
        self.order.refresh_from_db()

        self.assertEqual(shipment.status, Shipment.StatusChoices.SHIPPED)
        self.assertEqual(self.order.status, Order.StatusChoices.SHIPPED)

        self.assert_shipment_notification_does_not_exist(
            shipment=shipment,
            title="Shipment shipped",
        )

    def test_muted_shipping_type_blocks_shipment_delivered_notification(self):
        self.authenticate_admin()

        shipment = self.create_shipment()

        shipment.mark_shipped(
            tracking_number="DHL123456",
            tracking_url="https://tracking.example.com/DHL123456",
            user=self.admin_user,
            note="Package shipped.",
        )

        shipment.refresh_from_db()

        url = reverse("shipment-mark-delivered", args=[shipment.pk])

        response = self.client.post(
            url,
            data={
                "note": "Delivered to customer.",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        shipment.refresh_from_db()
        self.order.refresh_from_db()

        self.assertEqual(shipment.status, Shipment.StatusChoices.DELIVERED)
        self.assertEqual(self.order.status, Order.StatusChoices.DELIVERED)

        self.assert_shipment_notification_does_not_exist(
            shipment=shipment,
            title="Shipment delivered",
        )

    def test_muted_shipping_type_blocks_shipment_cancelled_notification(self):
        self.authenticate_admin()

        shipment = self.create_shipment()

        url = reverse("shipment-cancel", args=[shipment.pk])

        response = self.client.post(
            url,
            data={
                "note": "Shipment cancelled by admin.",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        shipment.refresh_from_db()

        self.assertEqual(shipment.status, Shipment.StatusChoices.CANCELLED)

        self.assert_shipment_notification_does_not_exist(
            shipment=shipment,
            title="Shipment cancelled",
        )
