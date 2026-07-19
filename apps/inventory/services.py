from apps.notifications.models import Notification
from apps.notifications.services import create_notification


def create_low_stock_notification_if_needed(*, stock, movement):
    product = stock.product
    seller = getattr(product, "seller", None)

    if not seller:
        return None

    if movement.quantity >= 0:
        return None

    before_available = movement.before_quantity - stock.reserved_quantity
    after_available = stock.available_quantity

    if before_available <= stock.low_stock_threshold:
        return None

    if after_available > stock.low_stock_threshold:
        return None

    return create_notification(
        user=seller,
        title="Low stock alert",
        message=(
            f"Product {product.name} is low in stock at "
            f"{stock.warehouse.name}. Available quantity: {after_available}."
        ),
        notification_type=Notification.NotificationType.INVENTORY,
        priority=Notification.Priority.HIGH,
        related_object_type="stock",
        related_object_id=str(stock.pk),
        action_url=f"/inventory/stock/{stock.pk}/",
        metadata={
            "product_id": product.pk,
            "product_name": product.name,
            "warehouse_id": stock.warehouse.pk,
            "warehouse_name": stock.warehouse.name,
            "available_quantity": after_available,
            "low_stock_threshold": stock.low_stock_threshold,
            "movement_id": movement.pk,
            "movement_type": movement.movement_type,
        },
    )
