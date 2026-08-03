from apps.notifications.services import create_notification
from apps.notifications.templates import render_notification_template


def create_review_notification(*, review, template_key, metadata=None, **context):
    if metadata is None:
        metadata = {}

    template_data = render_notification_template(template_key, **context)

    return create_notification(
        user=review.customer,
        title=template_data["title"],
        message=template_data["message"],
        notification_type=template_data["notification_type"],
        priority=template_data["priority"],
        related_object_type="product_review",
        related_object_id=str(review.pk),
        action_url=f"/reviews/product-reviews/{review.pk}/",
        metadata={
            "review_id": review.pk,
            "product_id": review.product_id,
            "template_key": template_key,
            **metadata,
        },
    )