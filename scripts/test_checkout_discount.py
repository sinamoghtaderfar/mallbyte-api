from decimal import Decimal

from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from apps.accounts.models import User
from apps.discounts.models import Discount, DiscountUsage
from apps.inventory.models import Stock, Warehouse
from apps.orders.models import Cart, CartItem, Order
from apps.products.models import Category, Product

import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.base")
django.setup()


class CheckoutDiscountIntegrationTests(APITestCase):
    def setUp(self):
        self.customer = User.objects.create_user(
            phone="+989222222222",
            email="customer@example.com",
            full_name="Test Customer",
            password="testpass123",
        )

        self.seller = User.objects.create_user(
            phone="+989111111111",
            email="seller@example.com",
            full_name="Test Seller",
            password="testpass123",
            is_seller=True,
        )

        self.category = Category.objects.create(
            name="Test Category",
            description="Test category",
            is_active=True,
        )

        self.product = Product.objects.create(
            seller=self.seller,
            category=self.category,
            name="Shipping Test Product",
            description="Test product description",
            price=Decimal("100000"),
            status=Product.StatusChoices.APPROVED,
            is_active=True,
            sku="TEST-SKU-001",
        )

        self.warehouse = Warehouse.objects.create(
            name="Main Test Warehouse",
            code="MAIN-TEST",
            type=Warehouse.TypeChoices.MAIN,
            province="Tehran",
            city="Tehran",
            address="Test warehouse address",
            postal_code="1234567890",
            phone="02112345678",
            manager_name="Warehouse Manager",
            manager_phone="09120000000",
            is_active=True,
            created_by=self.seller,
        )

        self.stock = Stock.objects.create(
            product=self.product,
            warehouse=self.warehouse,
            quantity=10,
            reserved_quantity=0,
        )

        self.cart = Cart.objects.create(user=self.customer)

        CartItem.objects.create(
            cart=self.cart,
            product=self.product,
            quantity=1,
            unit_price=self.product.final_price,
        )

        self.discount = Discount.objects.create(
            code="TEST10",
            title="Test 10 Percent",
            discount_type=Discount.DiscountTypeChoices.PERCENTAGE,
            value=Decimal("10"),
            min_order_amount=Decimal("0"),
            is_active=True,
            created_by=self.seller,
        )

        self.client.force_authenticate(user=self.customer)

    def test_checkout_applies_discount_to_order(self):
        url = reverse("order-checkout")

        response = self.client.post(
            url,
            data={
                "receiver_name": "Test Customer",
                "receiver_phone": "+989222222222",
                "province": "Tehran",
                "city": "Tehran",
                "address": "Test address",
                "postal_code": "1234567890",
                "shipping_cost": "0",
                "discount_code": "TEST10",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        order = Order.objects.get(user=self.customer)

        self.assertEqual(order.subtotal, Decimal("100000"))
        self.assertEqual(order.discount_amount, Decimal("10000"))
        self.assertEqual(order.shipping_cost, Decimal("0"))
        self.assertEqual(order.total_amount, Decimal("90000"))

        usage = DiscountUsage.objects.get(order=order)

        self.assertEqual(usage.discount, self.discount)
        self.assertEqual(usage.user, self.customer)
        self.assertEqual(usage.code_snapshot, "TEST10")
        self.assertEqual(usage.discount_amount, Decimal("10000"))

        self.discount.refresh_from_db()
        self.assertEqual(self.discount.used_count, 1)

        self.cart.refresh_from_db()
        self.assertEqual(self.cart.items.count(), 0)

        self.stock.refresh_from_db()
        self.assertEqual(self.stock.reserved_quantity, 1)

    def test_checkout_without_discount_still_works(self):
        url = reverse("order-checkout")

        response = self.client.post(
            url,
            data={
                "receiver_name": "Test Customer",
                "receiver_phone": "+989222222222",
                "province": "Tehran",
                "city": "Tehran",
                "address": "Test address",
                "postal_code": "1234567890",
                "shipping_cost": "0",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        order = Order.objects.get(user=self.customer)

        self.assertEqual(order.subtotal, Decimal("100000"))
        self.assertEqual(order.discount_amount, Decimal("0"))
        self.assertEqual(order.total_amount, Decimal("100000"))

        self.assertFalse(DiscountUsage.objects.filter(order=order).exists())

    def test_checkout_rejects_invalid_discount_code(self):
        url = reverse("order-checkout")

        response = self.client.post(
            url,
            data={
                "receiver_name": "Test Customer",
                "receiver_phone": "+989222222222",
                "province": "Tehran",
                "city": "Tehran",
                "address": "Test address",
                "postal_code": "1234567890",
                "shipping_cost": "0",
                "discount_code": "WRONGCODE",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(Order.objects.count(), 0)
        self.assertEqual(DiscountUsage.objects.count(), 0)

        self.cart.refresh_from_db()
        self.assertEqual(self.cart.items.count(), 1)