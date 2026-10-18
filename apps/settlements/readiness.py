"""Non-mutating financial migration/readiness checks for operators."""
from django.db.models import Count, F, OuterRef, Exists

from apps.orders.models import Order, OrderItem
from apps.payments.models import Payment
from apps.settlements.models import ItemAllocation, SellerLedgerEntry


def financial_readiness():
    missing = OrderItem.objects.filter(financial_allocation__isnull=True)
    captured = Payment.objects.filter(
        status__in=(Payment.StatusChoices.SUCCESS, Payment.StatusChoices.REFUNDED),
        paid_at__isnull=False,
    )
    has_ledger = SellerLedgerEntry.objects.filter(
        allocation__order_item__order_id=OuterRef("order_id"),
        kind=SellerLedgerEntry.Kind.SALE,
    )
    unposted = captured.annotate(any_ledger=Exists(has_ledger)).filter(any_ledger=False)
    return {
        "order_items_missing_snapshots": missing.count(),
        "captured_payments_without_any_seller_sale_ledger": unposted.count(),
        "paid_orders_with_missing_item_allocations": Order.objects.filter(
            payment_status=Order.PaymentStatusChoices.PAID,
            items__financial_allocation__isnull=True,
        ).distinct().count(),
        "warning": "Historical orders must be reviewed, not automatically revalued using current product ownership or commission rate.",
    }
