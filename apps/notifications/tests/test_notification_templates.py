from django.test import TestCase

from apps.notifications.models import Notification
from apps.notifications.templates import render_notification_template


class NotificationTemplateTests(TestCase):
    def test_render_product_submitted_template(self):
        result = render_notification_template(
            "product_submitted",
            product_name="Test Product",
        )

        self.assertEqual(result["title"], "Product submitted")
        self.assertEqual(
            result["message"],
            "Your product 'Test Product' has been submitted for review.",
        )
        self.assertEqual(
            result["notification_type"],
            Notification.NotificationType.PRODUCT,
        )
        self.assertEqual(
            result["priority"],
            Notification.Priority.NORMAL,
        )

    def test_render_low_stock_alert_template(self):
        result = render_notification_template(
            "low_stock_alert",
            product_name="Test Product",
            available_quantity=3,
        )

        self.assertEqual(result["title"], "Low stock alert")
        self.assertEqual(
            result["message"],
            "Product 'Test Product' is low in stock. Available quantity: 3.",
        )
        self.assertEqual(
            result["notification_type"],
            Notification.NotificationType.INVENTORY,
        )
        self.assertEqual(
            result["priority"],
            Notification.Priority.HIGH,
        )

    def test_render_order_status_updated_template(self):
        result = render_notification_template(
            "order_status_updated",
            order_id="ORD-1001",
            status_display="Shipped",
        )

        self.assertEqual(result["title"], "Order status updated")
        self.assertEqual(
            result["message"],
            "Your order #ORD-1001 status has been updated to Shipped.",
        )
        self.assertEqual(
            result["notification_type"],
            Notification.NotificationType.ORDER,
        )
        self.assertEqual(
            result["priority"],
            Notification.Priority.NORMAL,
        )

    def test_render_missing_template_raises_value_error(self):
        with self.assertRaises(ValueError):
            render_notification_template(
                "missing_template",
            )

    def test_render_template_with_missing_context_raises_key_error(self):
        with self.assertRaises(KeyError):
            render_notification_template(
                "product_submitted",
            )
