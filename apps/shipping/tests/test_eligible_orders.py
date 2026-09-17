from decimal import Decimal
from typing import cast

from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from apps.accounts.models import User
from apps.orders.models import Order
from apps.shipping.models import Shipment


class EligibleShipmentOrdersTests(APITestCase):
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

    def create_order(
        self,
        *,
        user,
        status=Order.StatusChoices.PAID,
        payment_status=Order.PaymentStatusChoices.PAID,
        receiver_name="Test Customer",
    ):
        return Order.objects.create(
            user=user,
            status=status,
            payment_status=payment_status,
            subtotal=Decimal("100000"),
            discount_amount=Decimal("0"),
            shipping_cost=Decimal("10000"),
            tax_amount=Decimal("0"),
            total_amount=Decimal("110000"),
            receiver_name=receiver_name,
            receiver_phone="+989120000001",
            province="Tehran",
            city="Tehran",
            address="Test shipping address",
            postal_code="1234567890",
        )

    def get_api_client(self) -> APIClient:
        return cast(APIClient, self.client)

    def setUp(self):
        self.admin_user = self.create_test_user(
            phone="+989850000001",
            email="admin_eligible_shipping@example.com",
            full_name="Shipping Admin",
            is_staff=True,
            is_superuser=True,
        )

        self.customer = self.create_test_user(
            phone="+989850000002",
            email="customer_eligible_shipping@example.com",
            full_name="Shipping Customer",
        )

        # Eligible: paid and no shipment.
        self.eligible_order = self.create_order(
            user=self.customer,
            receiver_name="Eligible Customer",
        )

        # Not eligible: order is not paid.
        self.pending_order = self.create_order(
            user=self.customer,
            status=Order.StatusChoices.PENDING_PAYMENT,
            payment_status=Order.PaymentStatusChoices.UNPAID,
            receiver_name="Pending Customer",
        )

        # Not eligible: paid order already has an active shipment.
        self.order_with_active_shipment = self.create_order(
            user=self.customer,
            receiver_name="Active Shipment Customer",
        )

        Shipment.create_from_order(
            order=self.order_with_active_shipment,
            created_by=self.admin_user,
            carrier=Shipment.CarrierChoices.DHL,
        )

        # Eligible again: cancelled shipment must not block a new shipment.
        self.order_with_cancelled_shipment = self.create_order(
            user=self.customer,
            receiver_name="Cancelled Shipment Customer",
        )

        cancelled_shipment = Shipment.create_from_order(
            order=self.order_with_cancelled_shipment,
            created_by=self.admin_user,
            carrier=Shipment.CarrierChoices.POST,
        )

        cancelled_shipment.cancel(
            user=self.admin_user,
            note="Cancelled for test.",
        )

    def authenticate_admin(self):
        self.get_api_client().force_authenticate(
            user=self.admin_user,
        )

    def authenticate_customer(self):
        self.get_api_client().force_authenticate(
            user=self.customer,
        )

    def test_admin_can_list_eligible_paid_orders(self):
        self.authenticate_admin()

        url = reverse("shipment-eligible-orders")

        response = self.client.get(url)

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )

        returned_ids = {item["id"] for item in response.data}

        self.assertIn(
            self.eligible_order.id,
            returned_ids,
        )

        self.assertIn(
            self.order_with_cancelled_shipment.id,
            returned_ids,
        )

        self.assertNotIn(
            self.pending_order.id,
            returned_ids,
        )

        self.assertNotIn(
            self.order_with_active_shipment.id,
            returned_ids,
        )

    def test_eligible_order_contains_required_admin_fields(self):
        self.authenticate_admin()

        url = reverse("shipment-eligible-orders")

        response = self.client.get(url)

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )

        order_data = next(
            item for item in response.data if item["id"] == self.eligible_order.id
        )

        self.assertEqual(
            order_data["order_number"],
            self.eligible_order.order_number,
        )

        self.assertEqual(
            order_data["user_email"],
            self.customer.email,
        )

        self.assertEqual(
            order_data["user_full_name"],
            self.customer.full_name,
        )

        self.assertEqual(
            order_data["receiver_name"],
            "Eligible Customer",
        )

        self.assertIn(
            "shipping_cost",
            order_data,
        )

        self.assertIn(
            "total_amount",
            order_data,
        )

        self.assertIn(
            "paid_at",
            order_data,
        )

    def test_normal_customer_cannot_access_eligible_orders(self):
        self.authenticate_customer()

        url = reverse("shipment-eligible-orders")

        response = self.client.get(url)

        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN,
        )

        self.assertEqual(
            response.data["detail"],
            "Only staff users can manage shipments.",
        )

    def test_created_shipment_removes_order_from_eligible_orders(self):
        self.authenticate_admin()

        eligible_url = reverse(
            "shipment-eligible-orders",
        )

        response = self.client.get(
            eligible_url,
        )

        initial_ids = {item["id"] for item in response.data}

        self.assertIn(
            self.eligible_order.id,
            initial_ids,
        )

        create_url = reverse(
            "shipment-list",
        )

        create_response = self.client.post(
            create_url,
            data={
                "order": self.eligible_order.id,
                "carrier": Shipment.CarrierChoices.DHL,
            },
            format="json",
        )

        self.assertEqual(
            create_response.status_code,
            status.HTTP_201_CREATED,
        )

        response = self.client.get(
            eligible_url,
        )

        final_ids = {item["id"] for item in response.data}

        self.assertNotIn(
            self.eligible_order.id,
            final_ids,
        )
