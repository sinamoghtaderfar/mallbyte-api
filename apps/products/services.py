from apps.notifications.models import Notification
from apps.notifications.services import create_notification


def create_product_notification(
    *,
    user,
    product,
    title,
    message,
    priority=Notification.Priority.NORMAL,
    metadata=None,
):
    if not user:
        return None

    if metadata is None:
        metadata = {}

    return create_notification(
        user=user,
        title=title,
        message=message,
        notification_type=Notification.NotificationType.PRODUCT,
        priority=priority,
        related_object_type="product",
        related_object_id=str(product.pk),
        action_url=f"/products/{product.pk}/",
        metadata={
            "product_id": product.pk,
            "product_name": product.name,
            "product_sku": product.sku,
            "product_status": product.status,
            **metadata,
        },
    )
