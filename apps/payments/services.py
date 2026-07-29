from apps.notifications.services import create_notification
from apps.notifications.templates import render_notification_template


def create_payment_notification(
    *,
    payment,
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
        user=payment.order.user,
        title=template_data["title"],
        message=template_data["message"],
        notification_type=template_data["notification_type"],
        priority=template_data["priority"],
        related_object_type="payment",
        related_object_id=str(payment.pk),
        action_url=f"/payments/{payment.pk}/",
        metadata={
            "payment_id": payment.pk,
            "order_id": payment.order.pk,
            "order_number": payment.order.order_number,
            "template_key": template_key,
            **metadata,
        },
    )
