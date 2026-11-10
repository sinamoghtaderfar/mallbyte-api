"""Release abandoned checkout holds using the existing locked cancellation flow."""
from celery import shared_task
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.orders.models import Order


@shared_task(name="apps.orders.tasks.expire_pending_orders")
def expire_pending_orders(batch_size=100):
    batch_size = max(1, min(int(batch_size), 1000))
    candidates = Order.objects.filter(
        status=Order.StatusChoices.PENDING_PAYMENT,
        payment_status__in=[Order.PaymentStatusChoices.UNPAID, Order.PaymentStatusChoices.FAILED],
        reservation_expires_at__lte=timezone.now(),
    ).order_by("reservation_expires_at", "pk").values_list("pk", flat=True)[:batch_size]
    expired = 0
    for order_id in list(candidates):
        try:
            Order.objects.get(pk=order_id).cancel(note="Order reservation expired.")
            expired += 1
        except (Order.DoesNotExist, ValidationError):
            # Another task, cancellation or capture already won the order lock.
            continue
    return {"expired": expired}
