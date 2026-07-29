from apps.notifications.services import create_notification
from apps.notifications.templates import render_notification_template


def create_low_stock_notification_if_needed(*, stock, movement):
    product = stock.product
    seller = product.seller

    current_available_quantity = stock.available_quantity
    previous_available_quantity = current_available_quantity - movement.quantity

    if previous_available_quantity <= stock.low_stock_threshold:
        return None

    if current_available_quantity > stock.low_stock_threshold:
        return None

    template_data = render_notification_template(
        "low_stock_alert",
        product_name=product.name,
        available_quantity=current_available_quantity,
    )

    return create_notification(
        user=seller,
        title=template_data["title"],
        message=template_data["message"],
        notification_type=template_data["notification_type"],
        priority=template_data["priority"],
        related_object_type="stock",
        related_object_id=str(stock.pk),
        action_url=f"/inventory/stocks/{stock.pk}/",
        metadata={
            "stock_id": stock.pk,
            "product_id": product.pk,
            "product_name": product.name,
            "warehouse_id": stock.warehouse_id,
            "available_quantity": current_available_quantity,
            "low_stock_threshold": stock.low_stock_threshold,
            "movement_id": movement.pk,
            "template_key": "low_stock_alert",
        },
    )
