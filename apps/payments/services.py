from apps.notifications.models import Notification
from apps.notifications.services import create_notification


def create_payment_notification(
    *,
    user,
    payment,
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
        notification_type=Notification.NotificationType.PAYMENT,
        priority=priority,
        related_object_type="payment",
        related_object_id=str(payment.pk),
        action_url=f"/payments/{payment.pk}/",
        metadata={
            "payment_number": payment.payment_number,
            "payment_status": payment.status,
            "order_id": payment.order_id,
            "order_number": payment.order.order_number,
            "amount": str(payment.amount),
            "provider": payment.provider,
        },
    )
