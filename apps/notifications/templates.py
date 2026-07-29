from apps.notifications.models import Notification

NOTIFICATION_TEMPLATES = {
    "product_submitted": {
        "title": "Product submitted",
        "message": "Your product '{product_name}' has been submitted for review.",
        "notification_type": Notification.NotificationType.PRODUCT,
        "priority": Notification.Priority.NORMAL,
    },
    "product_approved": {
        "title": "Product approved",
        "message": "Your product '{product_name}' has been approved.",
        "notification_type": Notification.NotificationType.PRODUCT,
        "priority": Notification.Priority.NORMAL,
    },
    "product_rejected": {
        "title": "Product rejected",
        "message": "Your product '{product_name}' has been rejected. Reason: {reason}",
        "notification_type": Notification.NotificationType.PRODUCT,
        "priority": Notification.Priority.HIGH,
    },
    "low_stock_alert": {
        "title": "Low stock alert",
        "message": "Product '{product_name}' is low in stock. Available quantity: {available_quantity}.",
        "notification_type": Notification.NotificationType.INVENTORY,
        "priority": Notification.Priority.HIGH,
    },
    "order_created": {
        "title": "Order created",
        "message": "Your order #{order_id} has been created successfully.",
        "notification_type": Notification.NotificationType.ORDER,
        "priority": Notification.Priority.NORMAL,
    },
    "order_cancelled": {
        "title": "Order cancelled",
        "message": "Your order #{order_id} has been cancelled.",
        "notification_type": Notification.NotificationType.ORDER,
        "priority": Notification.Priority.HIGH,
    },
    "payment_successful": {
        "title": "Payment successful",
        "message": "Your payment for order #{order_id} was successful.",
        "notification_type": Notification.NotificationType.PAYMENT,
        "priority": Notification.Priority.NORMAL,
    },
    "payment_failed": {
        "title": "Payment failed",
        "message": "Your payment for order #{order_id} failed.",
        "notification_type": Notification.NotificationType.PAYMENT,
        "priority": Notification.Priority.HIGH,
    },
    "shipment_created": {
        "title": "Shipment created",
        "message": "A shipment has been created for your order #{order_id}.",
        "notification_type": Notification.NotificationType.SHIPPING,
        "priority": Notification.Priority.NORMAL,
    },
    "shipment_shipped": {
        "title": "Shipment shipped",
        "message": "Your shipment for order #{order_id} has been shipped.",
        "notification_type": Notification.NotificationType.SHIPPING,
        "priority": Notification.Priority.NORMAL,
    },
    "shipment_delivered": {
        "title": "Shipment delivered",
        "message": "Your shipment for order #{order_id} has been delivered.",
        "notification_type": Notification.NotificationType.SHIPPING,
        "priority": Notification.Priority.NORMAL,
    },
    "return_submitted": {
        "title": "Return request submitted",
        "message": "Your return request for order #{order_id} has been submitted.",
        "notification_type": Notification.NotificationType.RETURN,
        "priority": Notification.Priority.NORMAL,
    },
    "return_approved": {
        "title": "Return request approved",
        "message": "Your return request for order #{order_id} has been approved.",
        "notification_type": Notification.NotificationType.RETURN,
        "priority": Notification.Priority.NORMAL,
    },
    "return_rejected": {
        "title": "Return request rejected",
        "message": "Your return request for order #{order_id} has been rejected.",
        "notification_type": Notification.NotificationType.RETURN,
        "priority": Notification.Priority.HIGH,
    },
}


def render_notification_template(template_key, **context):
    template = NOTIFICATION_TEMPLATES.get(template_key)

    if template is None:
        raise ValueError(f"Notification template '{template_key}' does not exist.")

    return {
        "title": template["title"],
        "message": template["message"].format(**context),
        "notification_type": template["notification_type"],
        "priority": template["priority"],
    }
