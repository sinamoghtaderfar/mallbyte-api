from apps.notifications.services import create_notification
from apps.notifications.templates import render_notification_template


def create_order_notification(
    *,
    order,
    template_key,
    metadata=None,
    **context,
):
    if metadata is None:
        metadata = {}

    template_data = render_notification_template(
        template_key,
        **context,
    )

    return create_notification(
        user=order.user,
        title=template_data["title"],
        message=template_data["message"],
        notification_type=template_data["notification_type"],
        priority=template_data["priority"],
        related_object_type="order",
        related_object_id=str(order.pk),
        action_url=f"/orders/{order.pk}/",
        metadata={
            "order_id": order.pk,
            "template_key": template_key,
            **metadata,
        },
    )
