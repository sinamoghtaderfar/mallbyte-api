from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal
from threading import Barrier, Event
from types import SimpleNamespace
from unittest import skipUnless
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db import close_old_connections, connection, transaction
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APITestCase, APITransactionTestCase

from apps.accounts.models import Seller
from apps.inventory.models import Stock, StockMovement, Warehouse
from apps.orders.models import Cart, CartItem, Order, OrderStatusHistory
from apps.orders.serializers import CheckoutSerializer
from apps.orders.tasks import expire_pending_orders
from apps.payments.models import Payment
from apps.products.models import Category, Product


class CheckoutIntegrityTests(APITestCase):
    def setUp(self):
        cache.clear()
        User = get_user_model()
        self.buyer = User.objects.create_user(email="checkout-buyer@example.com", password="StrongPass123!")
        self.seller = User.objects.create_user(email="checkout-seller@example.com", password="StrongPass123!", is_seller=True)
        self.profile = Seller.objects.create(user=self.seller, store_name="Checkout store", status=Seller.StatusChoices.APPROVED)
        self.product = Product.objects.create(
            seller=self.seller, category=Category.objects.create(name="Checkout"),
            name="Checkout product", sku="CHECKOUT-PRODUCT", price=100,
            status=Product.StatusChoices.APPROVED, is_active=True,
        )
        self.stock = Stock.objects.create(
            product=self.product, warehouse=Warehouse.objects.create(name="Checkout warehouse", code="CHECKOUT"), quantity=10,
        )
        self.cart = Cart.objects.create(user=self.buyer)
        CartItem.objects.create(cart=self.cart, product=self.product, quantity=2, unit_price=100)
        self.client.force_authenticate(self.buyer)
        self.payload = {
            "receiver_name": "Buyer", "receiver_phone": "1234567890",
            "province": "Berlin", "city": "Berlin", "address": "Test address",
            "postal_code": "12345",
        }

    def checkout(self, **changes):
        return self.client.post("/api/orders/orders/checkout/", {**self.payload, **changes}, format="json")

    def test_idempotent_replay_returns_one_order_and_one_reservation(self):
        first = self.checkout(idempotency_key="checkout-key-001")
        second = self.checkout(idempotency_key="checkout-key-001")
        self.assertEqual(first.status_code, 201, first.data)
        self.assertEqual(second.status_code, 201, second.data)
        self.assertEqual(first.data["id"], second.data["id"])
        self.assertEqual(Order.objects.count(), 1)
        self.stock.refresh_from_db()
        self.assertEqual(self.stock.reserved_quantity, 2)

    def test_idempotency_key_cannot_be_reused_for_changed_address(self):
        self.assertEqual(self.checkout(idempotency_key="checkout-key-002").status_code, 201)
        result = self.checkout(idempotency_key="checkout-key-002", address="A different address")
        self.assertEqual(result.status_code, 400)
        self.assertEqual(Order.objects.count(), 1)

    @override_settings(CHECKOUT_SHIPPING_COST="25")
    def test_shipping_charge_comes_from_server(self):
        result = self.checkout()
        self.assertEqual(result.status_code, 201, result.data)
        self.assertEqual(Decimal(result.data["shipping_cost"]), 25)
        self.assertEqual(Decimal(result.data["total_amount"]), 225)

    @override_settings(CHECKOUT_SHIPPING_COST="25")
    def test_customer_cannot_override_shipping_charge(self):
        result = self.checkout(shipping_cost="0")
        self.assertEqual(result.status_code, 400)
        self.assertFalse(Order.objects.exists())
        self.assertEqual(self.cart.items.count(), 1)

    def test_deactivated_product_is_rejected_at_checkout(self):
        Product.objects.filter(pk=self.product.pk).update(is_active=False)
        result = self.checkout()
        self.assertEqual(result.status_code, 400)
        self.assertFalse(Order.objects.exists())

    def test_suspended_seller_is_rejected_at_checkout(self):
        Seller.objects.filter(pk=self.profile.pk).update(status=Seller.StatusChoices.SUSPENDED)
        result = self.checkout()
        self.assertEqual(result.status_code, 400)
        self.assertFalse(Order.objects.exists())

    def test_insufficient_stock_rolls_back_order_and_keeps_cart(self):
        Stock.objects.filter(pk=self.stock.pk).update(quantity=1)
        result = self.checkout()
        self.assertEqual(result.status_code, 400)
        self.assertFalse(Order.objects.exists())
        self.assertEqual(self.cart.items.count(), 1)

    def test_expiration_is_idempotent_and_releases_reservations(self):
        result = self.checkout()
        self.assertEqual(result.status_code, 201, result.data)
        order = Order.objects.get(pk=result.data["id"])
        self.assertIsNotNone(order.reservation_expires_at)
        Payment.objects.create(order=order, user=self.buyer, amount=order.total_amount)
        Order.objects.filter(pk=order.pk).update(reservation_expires_at=timezone.now() - timedelta(seconds=1))
        self.assertEqual(expire_pending_orders()["expired"], 1)
        self.assertEqual(expire_pending_orders()["expired"], 0)
        self.stock.refresh_from_db()
        order.refresh_from_db()
        self.assertEqual(self.stock.reserved_quantity, 0)
        self.assertEqual(order.status, Order.StatusChoices.CANCELLED)
        self.assertEqual(order.payments.get().status, Payment.StatusChoices.CANCELLED)
        self.assertEqual(order.seller_fulfillments.get().status, Order.StatusChoices.CANCELLED)
        self.assertEqual(OrderStatusHistory.objects.filter(order=order, new_status="cancelled").count(), 1)

    def test_expired_order_refuses_payment_creation_and_capture(self):
        result = self.checkout()
        self.assertEqual(result.status_code, 201, result.data)
        order = Order.objects.get(pk=result.data["id"])
        payment = Payment.objects.create(order=order, user=self.buyer, amount=order.total_amount)
        Order.objects.filter(pk=order.pk).update(reservation_expires_at=timezone.now() - timedelta(seconds=1))
        response = self.client.post("/api/payments/payments/", {"order": order.pk}, format="json")
        self.assertEqual(response.status_code, 400)
        with self.assertRaises(ValidationError):
            payment.mark_success()
        self.stock.refresh_from_db()
        self.assertEqual(self.stock.quantity, 10)
        self.assertEqual(self.stock.reserved_quantity, 2)

    def test_customer_identity_scopes_idempotency_keys(self):
        first = self.checkout(idempotency_key="shared-intent-key")
        second_buyer = get_user_model().objects.create_user(email="second-checkout@example.com", password="StrongPass123!")
        cart = Cart.objects.create(user=second_buyer)
        CartItem.objects.create(cart=cart, product=self.product, quantity=1, unit_price=100)
        self.client.force_authenticate(second_buyer)
        second = self.checkout(idempotency_key="shared-intent-key")
        self.assertEqual(second.status_code, 201, second.data)
        self.assertNotEqual(first.data["id"], second.data["id"])


@skipUnless(connection.vendor == "postgresql", "Requires PostgreSQL row locks")
class CheckoutConcurrencyTests(APITransactionTestCase):
    setUp = CheckoutIntegrityTests.setUp

    def test_concurrent_same_key_creates_one_order(self):
        barrier = Barrier(2)

        def checkout():
            close_old_connections()
            try:
                request = SimpleNamespace(user=self.buyer, headers={})
                serializer = CheckoutSerializer(
                    data={**self.payload, "idempotency_key": "concurrent-checkout-key"},
                    context={"request": request},
                )
                serializer.is_valid(raise_exception=True)
                barrier.wait(timeout=5)
                return serializer.save().pk
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(checkout) for _ in range(2)]
            order_ids = [future.result(timeout=10) for future in futures]
        self.assertEqual(order_ids[0], order_ids[1])
        self.assertEqual(Order.objects.count(), 1)
        self.stock.refresh_from_db()
        self.assertEqual(self.stock.reserved_quantity, 2)

    def test_eligibility_locks_allow_concurrent_inventory_foreign_keys(self):
        eligibility_locked = Event()
        movement_completed = Event()

        def pause_after_eligibility():
            eligibility_locked.set()
            if not movement_completed.wait(timeout=5):
                raise AssertionError("Inventory FK checks blocked behind eligibility locks")
            return Decimal("0")

        def checkout():
            close_old_connections()
            try:
                serializer = CheckoutSerializer(
                    data=self.payload,
                    context={"request": SimpleNamespace(user=self.buyer, headers={})},
                )
                serializer.is_valid(raise_exception=True)
                return serializer.save().pk
            finally:
                close_old_connections()

        def add_stock():
            close_old_connections()
            try:
                if not eligibility_locked.wait(timeout=5):
                    raise AssertionError("Checkout did not reach eligibility boundary")
                with transaction.atomic():
                    with connection.cursor() as cursor:
                        cursor.execute("SET LOCAL lock_timeout = '1500ms'")
                    movement = StockMovement.objects.create(
                        product=self.product, warehouse=self.stock.warehouse,
                        movement_type=StockMovement.MovementType.PURCHASE,
                        quantity=1, created_by=self.seller,
                    )
                return movement.pk
            finally:
                movement_completed.set()
                close_old_connections()

        with patch("apps.orders.serializers.shipping_charge", side_effect=pause_after_eligibility):
            with ThreadPoolExecutor(max_workers=2) as pool:
                checkout_future = pool.submit(checkout)
                movement_future = pool.submit(add_stock)
                self.assertTrue(movement_future.result(timeout=10))
                self.assertTrue(checkout_future.result(timeout=10))
        self.stock.refresh_from_db()
        self.assertEqual(self.stock.quantity, 11)
        self.assertEqual(self.stock.reserved_quantity, 2)
