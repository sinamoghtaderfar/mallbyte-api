"""Integration coverage across seller moderation, public catalog, cart and checkout."""

from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from apps.accounts.models import Seller, User
from apps.inventory.models import Stock, Warehouse
from apps.orders.models import Order, SellerOrderFulfillment
from apps.products.models import Category, Product


class MarketplaceCheckoutJourneyTests(APITestCase):
    def setUp(self):
        self.seller = User.objects.create_user(
            email="e2e-seller@example.com",
            full_name="Seller",
            password="TestPass123!",
            is_seller=True,
        )
        Seller.objects.create(
            user=self.seller,
            store_name="Journey Shop",
            store_slug="journey-shop",
            business_email="shop@example.com",
            business_phone="123456789",
            status=Seller.StatusChoices.APPROVED,
        )
        self.customer = User.objects.create_user(
            email="e2e-buyer@example.com", full_name="Buyer", password="TestPass123!"
        )
        self.admin = User.objects.create_superuser(
            email="e2e-admin@example.com",
            full_name="Admin",
            password="TestPass123!",
        )
        self.category = Category.objects.create(name="Journey", slug="journey")
        self.warehouse = Warehouse.objects.create(
            name="Journey Warehouse",
            code="E2E",
            province="Tehran",
            city="Tehran",
            address="Test address",
            postal_code="1234567890",
            phone="123456789",
            manager_name="Operator",
            manager_phone="123456789",
        )

    def test_seller_submission_to_customer_checkout_and_cancellation(self):
        self.client.force_authenticate(user=self.seller)
        create = self.client.post(
            reverse("product-list"),
            {
                "name": "Journey Keyboard",
                "description": "Mechanical keyboard for the integration test",
                "short_description": "Keyboard",
                "category": self.category.pk,
                "price": "250000",
                "sku": "journey-keyboard-1",
            },
            format="json",
        )
        self.assertEqual(create.status_code, status.HTTP_201_CREATED, create.data)
        product = Product.objects.get(sku="journey-keyboard-1")
        self.assertEqual(product.status, Product.StatusChoices.PENDING)

        Stock.objects.create(
            product=product,
            warehouse=self.warehouse,
            quantity=5,
            reserved_quantity=0,
        )
        stock = Stock.objects.get(product=product, warehouse=self.warehouse)

        # A pending product must not enter the public catalog or the cart.
        self.client.force_authenticate(user=self.customer)
        public_before = self.client.get(reverse("product-list"), {"search": "Journey Keyboard"})
        self.assertNotIn(product.pk, [row["id"] for row in public_before.data["results"]])
        blocked = self.client.post(
            reverse("cart-add-item"),
            {"product": product.pk, "quantity": 2},
            format="json",
        )
        self.assertEqual(blocked.status_code, status.HTTP_400_BAD_REQUEST)

        self.client.force_authenticate(user=self.admin)
        approve = self.client.post(reverse("product-approve", args=[product.pk]))
        self.assertEqual(approve.status_code, status.HTTP_200_OK, approve.data)

        self.client.force_authenticate(user=self.customer)
        public_after = self.client.get(reverse("product-list"), {"search": "Journey Keyboard"})
        self.assertIn(product.pk, [row["id"] for row in public_after.data["results"]])

        added = self.client.post(
            reverse("cart-add-item"),
            {"product": product.pk, "quantity": 2},
            format="json",
        )
        self.assertEqual(added.status_code, status.HTTP_200_OK, added.data)

        checkout = self.client.post(
            reverse("order-checkout"),
            {
                "receiver_name": "Buyer",
                "receiver_phone": "123456789",
                "province": "Tehran",
                "city": "Tehran",
                "address": "Test delivery address",
                "postal_code": "1234567890",
            },
            format="json",
        )
        self.assertEqual(checkout.status_code, status.HTTP_201_CREATED, checkout.data)
        order = Order.objects.get(pk=checkout.data["id"])
        self.assertEqual(order.user, self.customer)
        self.assertEqual(order.status, Order.StatusChoices.PENDING_PAYMENT)
        self.assertTrue(SellerOrderFulfillment.objects.filter(order=order, seller=self.seller).exists())
        stock.refresh_from_db()
        self.assertEqual(stock.reserved_quantity, 2)

        # A seller can see its own resulting order; a customer cannot.
        self.client.force_authenticate(user=self.seller)
        seller_orders = self.client.get(reverse("order-seller-orders"))
        self.assertEqual(seller_orders.status_code, status.HTTP_200_OK, seller_orders.data)
        self.assertIn(order.pk, [row["id"] for row in seller_orders.data])

        self.client.force_authenticate(user=self.customer)
        seller_blocked = self.client.get(reverse("order-seller-orders"))
        self.assertEqual(seller_blocked.status_code, status.HTTP_403_FORBIDDEN)

        cancelled = self.client.post(reverse("order-cancel", args=[order.pk]))
        self.assertEqual(cancelled.status_code, status.HTTP_200_OK, cancelled.data)
        stock.refresh_from_db()
        self.assertEqual(stock.reserved_quantity, 0)
