
from decimal import Decimal

from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APITestCase

from apps.orders.models import Order, OrderItem
from apps.products.models import Brand, Category, Product

User = get_user_model()


class SellerOrderAPITests(APITestCase):
    def setUp(self):
        self.customer = User.objects.create_user(
            email="customer@example.com",
            password="pass12345",
        )
        self.seller = User.objects.create_user(
            email="seller@example.com",
            password="pass12345",
            is_seller=True,
        )
        self.other_seller = User.objects.create_user(
            email="other-seller@example.com",
            password="pass12345",
            is_seller=True,
        )

        self.category = Category.objects.create(
            name="Electronics",
            slug="electronics",
        )
        self.brand = Brand.objects.create(
            name="MallByte",
            slug="mallbyte",
        )

        self.seller_product = Product.objects.create(
            seller=self.seller,
            category=self.category,
            brand=self.brand,
            name="Seller Product",
            slug="seller-product",
            description="Seller product description",
            price=Decimal("1000"),
            sku="SELLER-001",
            status=Product.StatusChoices.APPROVED,
            is_active=True,
        )
        self.other_product = Product.objects.create(
            seller=self.other_seller,
            category=self.category,
            brand=self.brand,
            name="Other Seller Product",
            slug="other-seller-product",
            description="Other seller product description",
            price=Decimal("2000"),
            sku="OTHER-001",
            status=Product.StatusChoices.APPROVED,
            is_active=True,
        )

    def create_order(self, status_value=Order.StatusChoices.PAID, payment_status=Order.PaymentStatusChoices.PAID):
        order = Order.objects.create(
            user=self.customer,
            status=status_value,
            payment_status=payment_status,
            subtotal=Decimal("3000"),
            discount_amount=Decimal("0"),
            shipping_cost=Decimal("0"),
            tax_amount=Decimal("0"),
            receiver_name="Sina Moghtader Far",
            receiver_phone="+49123456789",
            province="Bavaria",
            city="Bamberg",
            address="Example street 1",
            postal_code="96047",
            customer_note="Please deliver carefully.",
        )

        OrderItem.objects.create(
            order=order,
            product=self.seller_product,
            product_name=self.seller_product.name,
            product_sku=self.seller_product.sku,
            quantity=1,
            unit_price=Decimal("1000"),
            total_price=Decimal("1000"),
        )
        OrderItem.objects.create(
            order=order,
            product=self.other_product,
            product_name=self.other_product.name,
            product_sku=self.other_product.sku,
            quantity=1,
            unit_price=Decimal("2000"),
            total_price=Decimal("2000"),
        )

        return order

    def test_seller_can_list_orders_that_include_own_products(self):
        order = self.create_order()

        other_order = Order.objects.create(
            user=self.customer,
            status=Order.StatusChoices.PAID,
            payment_status=Order.PaymentStatusChoices.PAID,
            subtotal=Decimal("2000"),
            receiver_name="Customer",
            receiver_phone="+49123456789",
            province="Bavaria",
            city="Bamberg",
            address="Other street 1",
            postal_code="96047",
        )
        OrderItem.objects.create(
            order=other_order,
            product=self.other_product,
            product_name=self.other_product.name,
            product_sku=self.other_product.sku,
            quantity=1,
            unit_price=Decimal("2000"),
            total_price=Decimal("2000"),
        )

        self.client.force_authenticate(user=self.seller)

        response = self.client.get("/api/orders/orders/seller/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["id"], order.id)
        self.assertEqual(response.data[0]["seller_items_count"], 1)
        self.assertEqual(Decimal(str(response.data[0]["seller_total_amount"])), Decimal("1000"))

    def test_seller_detail_only_returns_own_items(self):
        order = self.create_order()

        self.client.force_authenticate(user=self.seller)

        response = self.client.get(f"/api/orders/orders/{order.id}/seller-detail/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["id"], order.id)
        self.assertEqual(response.data["seller_items_count"], 1)
        self.assertEqual(len(response.data["items"]), 1)
        self.assertEqual(response.data["items"][0]["product"], self.seller_product.id)

    def test_non_seller_cannot_access_seller_orders(self):
        self.client.force_authenticate(user=self.customer)

        response = self.client.get("/api/orders/orders/seller/")

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_seller_can_move_paid_order_to_processing(self):
        order = self.create_order()

        self.client.force_authenticate(user=self.seller)

        response = self.client.post(
            f"/api/orders/orders/{order.id}/seller-status/",
            {
                "status": Order.StatusChoices.PROCESSING,
                "note": "Seller started preparing the order.",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        order.refresh_from_db()
        self.assertEqual(order.status, Order.StatusChoices.PROCESSING)
        self.assertEqual(order.status_history.last().new_status, Order.StatusChoices.PROCESSING)

    def test_seller_cannot_skip_fulfillment_status(self):
        order = self.create_order()

        self.client.force_authenticate(user=self.seller)

        response = self.client.post(
            f"/api/orders/orders/{order.id}/seller-status/",
            {
                "status": Order.StatusChoices.DELIVERED,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_seller_cannot_update_unpaid_order(self):
        order = self.create_order(
            status_value=Order.StatusChoices.PENDING_PAYMENT,
            payment_status=Order.PaymentStatusChoices.UNPAID,
        )

        self.client.force_authenticate(user=self.seller)

        response = self.client.post(
            f"/api/orders/orders/{order.id}/seller-status/",
            {
                "status": Order.StatusChoices.PROCESSING,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_other_seller_cannot_access_order_without_own_items(self):
        order = self.create_order()

        seller_without_items = User.objects.create_user(
            email="empty-seller@example.com",
            password="pass12345",
            is_seller=True,
        )

        self.client.force_authenticate(user=seller_without_items)

        response = self.client.get(f"/api/orders/orders/{order.id}/seller-detail/")

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
