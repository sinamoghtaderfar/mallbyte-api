from apps.notifications.services import create_notification
from apps.notifications.templates import render_notification_template


def create_shipment_notification(
    *,
    shipment,
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
        user=shipment.order.user,
        title=template_data["title"],
        message=template_data["message"],
        notification_type=template_data["notification_type"],
        priority=template_data["priority"],
        related_object_type="shipment",
        related_object_id=str(shipment.pk),
        action_url=f"/shipping/shipments/{shipment.pk}/",
        metadata={
            "shipment_id": shipment.pk,
            "order_id": shipment.order.pk,
            "order_number": shipment.order.order_number,
            "template_key": template_key,
            **metadata,
        },
    )
