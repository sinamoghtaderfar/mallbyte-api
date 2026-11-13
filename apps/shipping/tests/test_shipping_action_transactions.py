from unittest.mock import patch

from django.urls import reverse
from rest_framework.test import APITestCase

from apps.orders.models import Order, OrderStatusHistory, SellerOrderFulfillmentHistory
from apps.shipping.models import Shipment, ShipmentEvent
from apps.shipping.tests import test_multiseller_shipping as multiseller


class ShippingActionTransactionTests(APITestCase):
    setUp = multiseller.MultiSellerShippingTests.setUp

    def shipment(self):
        return Shipment.create_from_order(order=self.order, seller=self.first_seller, created_by=self.admin)

    def assert_snapshot_unchanged(self, shipment, action):
        old_shipment_status = shipment.status
        self.order.refresh_from_db()
        self.first_fulfillment.refresh_from_db()
        old_order_status = self.order.status
        old_fulfillment_status = self.first_fulfillment.status
        counts = (ShipmentEvent.objects.count(), SellerOrderFulfillmentHistory.objects.count(), OrderStatusHistory.objects.count())
        with patch("apps.shipping.views.create_shipment_notification", side_effect=RuntimeError("Notification unavailable")):
            with self.assertRaises(RuntimeError):
                self.client.post(reverse(f"shipment-{action}", args=[shipment.pk]), {}, format="json")
        shipment.refresh_from_db()
        self.order.refresh_from_db()
        self.first_fulfillment.refresh_from_db()
        self.assertEqual(shipment.status, old_shipment_status)
        self.assertEqual(self.order.status, old_order_status)
        self.assertEqual(self.first_fulfillment.status, old_fulfillment_status)
        self.assertEqual((ShipmentEvent.objects.count(), SellerOrderFulfillmentHistory.objects.count(), OrderStatusHistory.objects.count()), counts)

    def test_create_notification_failure_rolls_back_shipment_and_event(self):
        with patch("apps.shipping.views.create_shipment_notification", side_effect=RuntimeError("Notification unavailable")):
            with self.assertRaises(RuntimeError):
                self.client.post(reverse("shipment-list"), {"order": self.order.pk, "seller": self.first_seller.pk}, format="json")
        self.assertFalse(Shipment.objects.exists())
        self.assertFalse(ShipmentEvent.objects.exists())
        self.first_fulfillment.refresh_from_db()
        self.assertEqual(self.first_fulfillment.status, Order.StatusChoices.PAID)

    def test_ready_notification_failure_rolls_back_all_fulfillment_state(self):
        self.assert_snapshot_unchanged(self.shipment(), "mark-ready")

    def test_shipped_notification_failure_rolls_back_all_fulfillment_state(self):
        self.assert_snapshot_unchanged(self.shipment(), "mark-shipped")

    def test_delivered_notification_failure_rolls_back_all_fulfillment_state(self):
        shipment = self.shipment()
        shipment.mark_shipped(user=self.admin)
        self.assert_snapshot_unchanged(shipment, "mark-delivered")

    def test_cancel_notification_failure_rolls_back_all_fulfillment_state(self):
        self.assert_snapshot_unchanged(self.shipment(), "cancel")
