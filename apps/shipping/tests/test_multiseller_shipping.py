from decimal import Decimal

from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from apps.orders.models import (
    Order,
    OrderItem,
    OrderStatusHistory,
    SellerOrderFulfillment,
    SellerOrderFulfillmentHistory,
)
from apps.products.models import Brand, Category, Product
from apps.shipping.models import Shipment, ShipmentEvent

User = get_user_model()


class MultiSellerShippingTests(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            phone="+989100003001",
            email="multiseller-shipping-admin@example.com",
            full_name="Shipping Admin",
            password="TestPassword123!",
        )
        self.customer = User.objects.create_user(
            phone="+989100003002",
            email="multiseller-shipping-customer@example.com",
            full_name="Shipping Customer",
            password="TestPassword123!",
        )
        self.first_seller = User.objects.create_user(
            phone="+989100003003",
            email="shipping-first-seller@example.com",
            full_name="First Seller",
            password="TestPassword123!",
            is_seller=True,
        )
        self.second_seller = User.objects.create_user(
            phone="+989100003004",
            email="shipping-second-seller@example.com",
            full_name="Second Seller",
            password="TestPassword123!",
            is_seller=True,
        )
        self.unrelated_seller = User.objects.create_user(
            phone="+989100003005",
            email="shipping-unrelated-seller@example.com",
            full_name="Unrelated Seller",
            password="TestPassword123!",
            is_seller=True,
        )

        category = Category.objects.create(
            name="Shipping test products", slug="shipping-test-products"
        )
        brand = Brand.objects.create(
            name="Shipping test brand", slug="shipping-test-brand"
        )
        self.first_product = Product.objects.create(
            seller=self.first_seller,
            category=category,
            brand=brand,
            name="First seller product",
            slug="shipping-first-seller-product",
            description="First seller item",
            price=Decimal("1000"),
            sku="SHIPPING-SELLER-ONE",
            status=Product.StatusChoices.APPROVED,
            is_active=True,
        )
        self.second_product = Product.objects.create(
            seller=self.second_seller,
            category=category,
            brand=brand,
            name="Second seller product",
            slug="shipping-second-seller-product",
            description="Second seller item",
            price=Decimal("2000"),
            sku="SHIPPING-SELLER-TWO",
            status=Product.StatusChoices.APPROVED,
            is_active=True,
        )

        self.order = Order.objects.create(
            user=self.customer,
            status=Order.StatusChoices.PAID,
            payment_status=Order.PaymentStatusChoices.PAID,
            subtotal=Decimal("3000"),
            shipping_cost=Decimal("200"),
            receiver_name="Shipping Customer",
            receiver_phone="+989100003002",
            province="Tehran",
            city="Tehran",
            address="Shipping test address",
            postal_code="1234567890",
        )
        for product, price in (
            (self.first_product, Decimal("1000")),
            (self.second_product, Decimal("2000")),
        ):
            OrderItem.objects.create(
                order=self.order,
                product=product,
                product_name=product.name,
                product_sku=product.sku,
                quantity=1,
                unit_price=price,
                total_price=price,
            )

        self.first_fulfillment = SellerOrderFulfillment.objects.create(
            order=self.order,
            seller=self.first_seller,
            status=Order.StatusChoices.PAID,
        )
        self.second_fulfillment = SellerOrderFulfillment.objects.create(
            order=self.order,
            seller=self.second_seller,
            status=Order.StatusChoices.PAID,
        )
        self.client.force_authenticate(user=self.admin)

    def create_shipment(self, seller, expected_status=status.HTTP_201_CREATED):
        response = self.client.post(
            reverse("shipment-list"),
            {
                "order": self.order.pk,
                "seller": seller.pk,
                "carrier": Shipment.CarrierChoices.DHL,
            },
            format="json",
        )
        self.assertEqual(response.status_code, expected_status, response.data)
        if expected_status != status.HTTP_201_CREATED:
            return response
        return Shipment.objects.get(pk=response.data["id"])

    def ship(self, shipment):
        response = self.client.post(
            reverse("shipment-mark-shipped", args=[shipment.pk]),
            {"tracking_number": f"DHL-{shipment.pk}"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        return response

    def deliver(self, shipment):
        response = self.client.post(
            reverse("shipment-mark-delivered", args=[shipment.pk]),
            {"note": "Delivered to the buyer."},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        return response

    def test_eligible_order_lists_both_sellers(self):
        response = self.client.get(reverse("shipment-eligible-orders"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        order_data = next(item for item in response.data if item["id"] == self.order.pk)
        self.assertTrue(order_data["requires_seller_selection"])
        self.assertEqual(
            {seller["id"] for seller in order_data["eligible_sellers"]},
            {self.first_seller.pk, self.second_seller.pk},
        )

    def test_multi_seller_order_requires_seller_selection(self):
        response = self.client.post(
            reverse("shipment-list"),
            {"order": self.order.pk, "carrier": "dhl"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(Shipment.objects.filter(order=self.order).count(), 0)

    def test_cannot_create_shipment_for_seller_without_items(self):
        self.create_shipment(
            self.unrelated_seller,
            expected_status=status.HTTP_400_BAD_REQUEST,
        )
        self.assertFalse(Shipment.objects.filter(order=self.order).exists())

    def test_each_seller_can_have_one_active_shipment(self):
        first = self.create_shipment(self.first_seller)
        second = self.create_shipment(self.second_seller)
        self.assertNotEqual(first.pk, second.pk)
        self.assertEqual(first.seller_fulfillment_id, self.first_fulfillment.pk)
        self.assertEqual(second.seller_fulfillment_id, self.second_fulfillment.pk)
        self.assertEqual(Shipment.objects.filter(order=self.order).count(), 2)
        # The order's shipping charge is not charged once for each seller.
        self.assertEqual(first.shipping_cost, Decimal("0"))
        self.assertEqual(second.shipping_cost, Decimal("0"))

    def test_first_shipment_does_not_hide_second_seller_from_eligible_orders(self):
        self.create_shipment(self.first_seller)
        response = self.client.get(reverse("shipment-eligible-orders"))
        order_data = next(item for item in response.data if item["id"] == self.order.pk)
        self.assertEqual(
            [seller["id"] for seller in order_data["eligible_sellers"]],
            [self.second_seller.pk],
        )
        self.create_shipment(self.second_seller)
        response = self.client.get(reverse("shipment-eligible-orders"))
        self.assertNotIn(self.order.pk, {item["id"] for item in response.data})

    def test_same_seller_cannot_have_two_active_shipments(self):
        self.create_shipment(self.first_seller)
        self.create_shipment(
            self.first_seller,
            expected_status=status.HTTP_400_BAD_REQUEST,
        )
        self.assertEqual(Shipment.objects.filter(order=self.order).count(), 1)

    def test_mark_ready_updates_only_the_selected_seller(self):
        first = self.create_shipment(self.first_seller)
        response = self.client.post(
            reverse("shipment-mark-ready", args=[first.pk]),
            {"note": "Packed and ready."},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.first_fulfillment.refresh_from_db()
        self.second_fulfillment.refresh_from_db()
        self.order.refresh_from_db()
        self.assertEqual(self.first_fulfillment.status, Order.StatusChoices.PROCESSING)
        self.assertEqual(self.second_fulfillment.status, Order.StatusChoices.PAID)
        self.assertEqual(self.order.status, Order.StatusChoices.PROCESSING)
        self.assertTrue(
            SellerOrderFulfillmentHistory.objects.filter(
                fulfillment=self.first_fulfillment,
                new_status=Order.StatusChoices.PROCESSING,
            ).exists()
        )

    def test_shipping_one_seller_does_not_ship_the_whole_order(self):
        first = self.create_shipment(self.first_seller)
        self.ship(first)
        self.first_fulfillment.refresh_from_db()
        self.second_fulfillment.refresh_from_db()
        self.order.refresh_from_db()
        self.assertEqual(self.first_fulfillment.status, Order.StatusChoices.SHIPPED)
        self.assertEqual(self.second_fulfillment.status, Order.StatusChoices.PAID)
        self.assertEqual(self.order.status, Order.StatusChoices.PROCESSING)
        self.assertIsNone(self.order.delivered_at)
        self.assertTrue(
            ShipmentEvent.objects.filter(
                shipment=first, new_status=Shipment.StatusChoices.SHIPPED
            ).exists()
        )

    def test_delivering_one_seller_does_not_deliver_the_whole_order(self):
        first = self.create_shipment(self.first_seller)
        self.ship(first)
        self.deliver(first)
        self.first_fulfillment.refresh_from_db()
        self.second_fulfillment.refresh_from_db()
        self.order.refresh_from_db()
        self.assertEqual(self.first_fulfillment.status, Order.StatusChoices.DELIVERED)
        self.assertEqual(self.second_fulfillment.status, Order.StatusChoices.PAID)
        self.assertEqual(self.order.status, Order.StatusChoices.PROCESSING)
        self.assertIsNone(self.order.delivered_at)

    def test_whole_order_becomes_shipped_after_both_sellers_ship(self):
        first = self.create_shipment(self.first_seller)
        second = self.create_shipment(self.second_seller)
        self.ship(first)
        self.ship(second)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.StatusChoices.SHIPPED)
        self.assertTrue(
            OrderStatusHistory.objects.filter(
                order=self.order, new_status=Order.StatusChoices.SHIPPED
            ).exists()
        )

    def test_whole_order_delivers_only_after_both_sellers_deliver(self):
        first = self.create_shipment(self.first_seller)
        second = self.create_shipment(self.second_seller)
        self.ship(first)
        self.ship(second)
        self.deliver(first)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.StatusChoices.SHIPPED)
        self.assertIsNone(self.order.delivered_at)
        self.deliver(second)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.StatusChoices.DELIVERED)
        self.assertIsNotNone(self.order.delivered_at)

    def test_cancelled_shipment_allows_a_replacement_for_same_seller(self):
        first = self.create_shipment(self.first_seller)
        self.ship(first)
        response = self.client.post(
            reverse("shipment-cancel", args=[first.pk]),
            {"note": "Replacement shipment required."},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.first_fulfillment.refresh_from_db()
        self.second_fulfillment.refresh_from_db()
        self.order.refresh_from_db()
        self.assertEqual(self.first_fulfillment.status, Order.StatusChoices.PAID)
        self.assertEqual(self.second_fulfillment.status, Order.StatusChoices.PAID)
        self.assertEqual(self.order.status, Order.StatusChoices.PAID)
        replacement = self.create_shipment(self.first_seller)
        self.assertNotEqual(first.pk, replacement.pk)

    def test_shipment_details_expose_the_correct_seller(self):
        first = self.create_shipment(self.first_seller)
        response = self.client.get(reverse("shipment-detail", args=[first.pk]))
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data["seller"], self.first_seller.pk)
        self.assertEqual(response.data["seller_name"], self.first_seller.full_name)
        self.assertEqual(response.data["seller_status"], Order.StatusChoices.PAID)

    def test_buyer_cannot_create_or_manage_shipments(self):
        first = self.create_shipment(self.first_seller)
        self.client.force_authenticate(user=self.customer)
        response = self.client.post(
            reverse("shipment-list"),
            {"order": self.order.pk, "seller": self.second_seller.pk},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        response = self.client.post(
            reverse("shipment-mark-shipped", args=[first.pk]),
            {},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_seller_cannot_mark_shipped_outside_shipping_workflow(self):
        self.client.force_authenticate(user=self.first_seller)
        response = self.client.post(
            f"/api/orders/orders/{self.order.pk}/seller-status/",
            {"status": Order.StatusChoices.SHIPPED},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.first_fulfillment.refresh_from_db()
        self.assertEqual(self.first_fulfillment.status, Order.StatusChoices.PAID)
