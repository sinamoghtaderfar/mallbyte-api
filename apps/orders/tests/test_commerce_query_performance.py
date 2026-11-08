from django.contrib.auth import get_user_model
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.inventory.models import Stock, Warehouse
from apps.orders.models import Cart, CartItem, Order, OrderItem, OrderStatusHistory, SellerOrderFulfillment
from apps.products.models import Category, Product
from apps.returns.models import ReturnAttachment, ReturnItem, ReturnRequest, ReturnStatusHistory


class CommerceQueryPerformanceTests(APITestCase):
    def setUp(self):
        User = get_user_model()
        self.customer = User.objects.create_user(email="query-customer@example.com", password="Test123!")
        self.seller = User.objects.create_user(email="query-seller@example.com", password="Test123!", is_seller=True)
        self.admin = User.objects.create_superuser(email="query-admin@example.com", password="Test123!")
        self.category = Category.objects.create(name="Query category")
        self.warehouse = Warehouse.objects.create(name="Query warehouse", code="QUERY")
        self.product = self.create_product("initial")

    def create_product(self, suffix):
        product = Product.objects.create(
            name=f"Query product {suffix}", sku=f"QUERY-{suffix}", seller=self.seller,
            category=self.category, price=100, status=Product.StatusChoices.APPROVED,
        )
        Stock.objects.create(product=product, warehouse=self.warehouse, quantity=10)
        return product

    def create_order(self):
        order = Order.objects.create(
            user=self.customer, subtotal=100, status=Order.StatusChoices.PAID,
            payment_status=Order.PaymentStatusChoices.PAID, paid_at=timezone.now(),
            receiver_name="Query customer", receiver_phone="12345", province="Test",
            city="Test", address="Test address", postal_code="12345",
        )
        OrderItem.objects.create(order=order, product=self.product, warehouse=self.warehouse, quantity=1, unit_price=100)
        SellerOrderFulfillment.objects.create(order=order, seller=self.seller, status=Order.StatusChoices.PAID)
        OrderStatusHistory.objects.create(order=order, new_status="paid", changed_by=self.admin)
        return order

    def measured_get(self, url):
        with CaptureQueriesContext(connection) as queries:
            response = self.client.get(url)
        self.assertEqual(response.status_code, 200, response.data)
        return response, len(queries)

    def test_seller_list_query_count_does_not_grow_per_order(self):
        self.create_order()
        self.client.force_authenticate(self.seller)
        first, initial_queries = self.measured_get(reverse("order-seller-orders"))
        self.assertEqual(first.data["count"], 1)
        for _ in range(5):
            self.create_order()
        more, more_queries = self.measured_get(reverse("order-seller-orders"))
        self.assertEqual(more.data["count"], 6)
        self.assertLessEqual(more_queries, initial_queries + 1)
        self.assertTrue(all(row["seller_items_count"] == 1 for row in more.data["results"]))

    def test_seller_list_is_paginated(self):
        for _ in range(26):
            self.create_order()
        self.client.force_authenticate(self.seller)
        response = self.client.get(reverse("order-seller-orders"))
        self.assertEqual(response.data["count"], 26)
        self.assertEqual(len(response.data["results"]), 20)
        self.assertIsNotNone(response.data["next"])
        second = self.client.get(reverse("order-seller-orders"), {"page": 2})
        self.assertEqual(len(second.data["results"]), 6)
        self.assertFalse({row["id"] for row in response.data["results"]} & {row["id"] for row in second.data["results"]})

    def test_eligible_shipments_query_count_does_not_grow_per_order(self):
        self.create_order()
        self.client.force_authenticate(self.admin)
        first, initial_queries = self.measured_get(reverse("shipment-eligible-orders"))
        self.assertEqual(first.data["count"], 1)
        for _ in range(5):
            self.create_order()
        more, more_queries = self.measured_get(reverse("shipment-eligible-orders"))
        self.assertEqual(more.data["count"], 6)
        self.assertLessEqual(more_queries, initial_queries + 1)

    def test_eligible_shipments_filter_before_pagination(self):
        for _ in range(26):
            self.create_order()
        blocked = self.create_order()
        SellerOrderFulfillment.objects.filter(order=blocked).update(status=Order.StatusChoices.DELIVERED)
        self.client.force_authenticate(self.admin)
        response = self.client.get(reverse("shipment-eligible-orders"))
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["count"], 26)
        self.assertEqual(len(response.data["results"]), 20)
        self.assertNotIn(blocked.pk, [row["id"] for row in response.data["results"]])
        self.assertIsNotNone(response.data["next"])

    def test_cart_queries_do_not_grow_per_product(self):
        cart = Cart.objects.create(user=self.customer)
        CartItem.objects.create(cart=cart, product=self.product, quantity=2, unit_price=100)
        self.client.force_authenticate(self.customer)
        first, initial_queries = self.measured_get(reverse("cart-list"))
        self.assertEqual(first.data["items"][0]["available_stock"], 10)
        for index in range(5):
            CartItem.objects.create(cart=cart, product=self.create_product(str(index)), quantity=1, unit_price=100)
        more, more_queries = self.measured_get(reverse("cart-list"))
        self.assertEqual(len(more.data["items"]), 6)
        self.assertEqual(more.data["total_items"], 7)
        self.assertEqual(more.data["subtotal"], "700")
        self.assertLessEqual(more_queries, initial_queries + 1)

    def test_return_item_input_is_bounded_and_nonempty(self):
        order = self.create_order()
        self.client.force_authenticate(self.customer)
        line = {"order_item": order.items.get().pk, "quantity": 1}
        for items in [[], [line] * 101]:
            response = self.client.post(reverse("return-request-list"), {"order": order.pk, "items": items}, format="json")
            self.assertEqual(response.status_code, 400, response.data)
            self.assertIn("items", response.data)

    def test_return_detail_queries_do_not_grow_per_attachment_or_history(self):
        order = self.create_order()
        claim = ReturnRequest.objects.create(order=order, customer=self.customer, total_requested_amount=100)
        ReturnItem.objects.create(return_request=claim, order_item=order.items.get(), quantity=1, requested_refund_amount=100)

        def related(number):
            ReturnAttachment.objects.create(return_request=claim, uploaded_by=self.admin, file=f"tests/evidence-{number}.txt")
            ReturnStatusHistory.objects.create(return_request=claim, new_status="submitted", changed_by=self.admin)

        related(0)
        self.client.force_authenticate(self.admin)
        url = reverse("return-request-detail", args=[claim.pk])
        _, initial_queries = self.measured_get(url)
        for index in range(1, 6):
            related(index)
        more, more_queries = self.measured_get(url)
        self.assertEqual(len(more.data["attachments"]), 6)
        self.assertEqual(len(more.data["status_history"]), 6)
        self.assertLessEqual(more_queries, initial_queries + 1)
