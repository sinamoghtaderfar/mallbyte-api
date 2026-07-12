from apps.notifications.models import Notification
from apps.notifications.services import create_notification


def create_order_notification(
    *,
    user,
    order,
    title,
    message,
    priority=Notification.Priority.NORMAL,
):
    if not user:
        return None

    return create_notification(
        user=user,
        title=title,
        message=message,
        notification_type=Notification.NotificationType.ORDER,
        priority=priority,
        related_object_type="order",
        related_object_id=str(order.pk),
        action_url=f"/orders/{order.pk}/",
        metadata={
            "order_number": order.order_number,
            "status": order.status,
            "payment_status": order.payment_status,
            "total_amount": str(order.total_amount),
        },
    )
