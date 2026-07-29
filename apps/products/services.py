from apps.notifications.services import create_notification
from apps.notifications.templates import render_notification_template


def create_product_notification(
    *,
    user,
    product,
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
        user=user,
        title=template_data["title"],
        message=template_data["message"],
        notification_type=template_data["notification_type"],
        priority=template_data["priority"],
        related_object_type="product",
        related_object_id=str(product.pk),
        action_url=f"/products/{product.pk}/",
        metadata={
            "product_id": product.pk,
            "product_name": product.name,
            "template_key": template_key,
            **metadata,
        },
    )
