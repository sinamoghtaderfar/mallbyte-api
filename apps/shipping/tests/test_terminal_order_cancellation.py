"""Cancelling stale parcels must not reopen a financially closed order."""
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.orders.models import Order, OrderStatusHistory, SellerOrderFulfillmentHistory
from apps.shipping.models import Shipment, ShipmentEvent
from apps.shipping.tests import test_multiseller_shipping as multiseller


class TerminalOrderShipmentCancellationTests(APITestCase):
    setUp = multiseller.MultiSellerShippingTests.setUp

    def cancel_stale_parcel(self, order_status, payment_status):
        shipment = Shipment.create_from_order(
            order=self.order, seller=self.first_seller, created_by=self.admin,
        )
        # A legacy/stale parcel can retain a pending status after another
        # workflow has closed the order. Physical parcel cleanup is still valid.
        delivered_at = timezone.now()
        Order.objects.filter(pk=self.order.pk).update(
            status=order_status, payment_status=payment_status, delivered_at=delivered_at,
        )
        self.first_fulfillment.status = Order.StatusChoices.DELIVERED
        self.first_fulfillment.save(update_fields=["status", "updated_at"])
        histories = (OrderStatusHistory.objects.count(), SellerOrderFulfillmentHistory.objects.count())

        response = self.client.post(reverse("shipment-cancel", args=[shipment.pk]), {}, format="json")

        self.assertEqual(response.status_code, 200, response.data)
        shipment.refresh_from_db()
        self.order.refresh_from_db()
        self.first_fulfillment.refresh_from_db()
        self.assertEqual(shipment.status, Shipment.StatusChoices.CANCELLED)
        self.assertIsNotNone(shipment.cancelled_at)
        self.assertEqual(ShipmentEvent.objects.filter(shipment=shipment, new_status="cancelled").count(), 1)
        self.assertEqual(self.order.status, order_status)
        self.assertEqual(self.order.payment_status, payment_status)
        self.assertEqual(self.order.delivered_at, delivered_at)
        self.assertEqual(self.first_fulfillment.status, Order.StatusChoices.DELIVERED)
        self.assertEqual((OrderStatusHistory.objects.count(), SellerOrderFulfillmentHistory.objects.count()), histories)

    def test_refunded_order_and_seller_snapshot_survive_parcel_cancellation(self):
        self.cancel_stale_parcel(Order.StatusChoices.REFUNDED, Order.PaymentStatusChoices.REFUNDED)

    def test_cancelled_order_survives_parcel_cancellation(self):
        self.cancel_stale_parcel(Order.StatusChoices.CANCELLED, Order.PaymentStatusChoices.UNPAID)

    def test_delivered_order_keeps_delivery_timestamp_and_seller_state(self):
        self.cancel_stale_parcel(Order.StatusChoices.DELIVERED, Order.PaymentStatusChoices.PAID)

    def test_unpaid_order_is_not_changed_to_paid(self):
        self.cancel_stale_parcel(Order.StatusChoices.PENDING_PAYMENT, Order.PaymentStatusChoices.UNPAID)

    def test_failed_payment_order_is_not_changed_to_paid(self):
        self.cancel_stale_parcel(Order.StatusChoices.PENDING_PAYMENT, Order.PaymentStatusChoices.FAILED)

    def test_active_paid_order_still_resets_cancelled_seller_preparation(self):
        shipment = Shipment.create_from_order(
            order=self.order, seller=self.first_seller, created_by=self.admin,
        )
        shipment.mark_ready(user=self.admin)
        response = self.client.post(reverse("shipment-cancel", args=[shipment.pk]), {}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.order.refresh_from_db()
        self.first_fulfillment.refresh_from_db()
        self.assertEqual(self.order.status, Order.StatusChoices.PAID)
        self.assertEqual(self.order.payment_status, Order.PaymentStatusChoices.PAID)
        self.assertEqual(self.first_fulfillment.status, Order.StatusChoices.PAID)
        duplicate = self.client.post(reverse("shipment-cancel", args=[shipment.pk]), {}, format="json")
        self.assertEqual(duplicate.status_code, 400)
        self.assertEqual(ShipmentEvent.objects.filter(shipment=shipment, new_status="cancelled").count(), 1)
