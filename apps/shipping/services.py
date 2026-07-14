from apps.notifications.models import Notification
from apps.notifications.services import create_notification


def create_shipment_notification(
    *,
    user,
    shipment,
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
        notification_type=Notification.NotificationType.SHIPPING,
        priority=priority,
        related_object_type="shipment",
        related_object_id=str(shipment.pk),
        action_url=f"/shipping/{shipment.pk}/",
        metadata={
            "shipment_number": shipment.shipment_number,
            "shipment_status": shipment.status,
            "order_id": shipment.order_id,
            "order_number": shipment.order.order_number,
            "carrier": shipment.carrier,
            "tracking_number": shipment.tracking_number,
        },
    )
