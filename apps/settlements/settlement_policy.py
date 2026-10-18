"""Conservative payout eligibility rules; never initiates a money transfer.

Balances are not necessarily withdrawable: capture, delivery, refund windows,
and unresolved returns affect eligibility. All money is partitioned by currency.
"""
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.db.models import Exists, OuterRef, Q, Sum
from django.utils import timezone

from apps.orders.models import Order, SellerOrderFulfillmentHistory
from apps.returns.models import ReturnItem, ReturnRequest
from apps.settlements.models import SellerLedgerEntry
from apps.settlements.services import money, seller_balance

ZERO = Decimal("0.00")


def payout_eligibility(seller_id, currency, *, as_of=None):
    """Return confirmed ledger balance and conservatively withdrawable amount.

    Sale credits become eligible only after delivery, hold period and absence of
    a still-pending return for the item. Refund and payout debits always reduce
    eligible balance, even if the originating sale is still held.
    """
    as_of = as_of or timezone.now()
    hold_days = int(getattr(settings, "SETTLEMENTS_PAYOUT_HOLD_DAYS", 14))
    if hold_days < 0:
        raise ValueError("SETTLEMENTS_PAYOUT_HOLD_DAYS cannot be negative")
    cutoff = as_of - timedelta(days=hold_days)
    currency = currency.upper()

    delivered = SellerOrderFulfillmentHistory.objects.filter(
        fulfillment__order_id=OuterRef("allocation__order_item__order_id"),
        fulfillment__seller_id=seller_id,
        new_status=Order.StatusChoices.DELIVERED,
        created_at__lte=cutoff,
    )
    blocking_returns = ReturnItem.objects.filter(
        order_item_id=OuterRef("allocation__order_item_id"),
        return_request__status__in=(
            ReturnRequest.Status.SUBMITTED,
            ReturnRequest.Status.UNDER_REVIEW,
            ReturnRequest.Status.APPROVED,
            ReturnRequest.Status.WAITING_FOR_ITEM,
            ReturnRequest.Status.ITEM_RECEIVED,
            ReturnRequest.Status.INSPECTING,
            ReturnRequest.Status.REFUND_PENDING,
        ),
    )

    sale_credits = SellerLedgerEntry.objects.filter(
        seller_id=seller_id,
        currency=currency,
        kind=SellerLedgerEntry.Kind.SALE,
        occurred_at__lte=as_of,
        allocation__isnull=False,
    ).annotate(
        seller_delivered=Exists(delivered),
        pending_return=Exists(blocking_returns),
    ).filter(
        Q(seller_delivered=True)
        | Q(
            allocation__order_item__order__status=Order.StatusChoices.DELIVERED,
            allocation__order_item__order__delivered_at__lte=cutoff,
        ),
        pending_return=False,
    )
    eligible_credits = money(sale_credits.aggregate(v=Sum("amount"))["v"] or ZERO)

    debits = SellerLedgerEntry.objects.filter(
        seller_id=seller_id,
        currency=currency,
        kind__in=(SellerLedgerEntry.Kind.REFUND, SellerLedgerEntry.Kind.PAYOUT),
        occurred_at__lte=as_of,
    ).aggregate(v=Sum("amount"))["v"] or ZERO

    raw = money(eligible_credits + debits)
    total_balance = seller_balance(seller_id, currency)
    withdrawable = max(ZERO, min(total_balance, raw))
    return {
        "currency": currency,
        "ledger_balance": str(total_balance),
        "eligible_sale_credits": str(eligible_credits),
        "refund_and_payout_debits": str(money(debits)),
        "withdrawable_amount": str(money(withdrawable)),
        "hold_days": hold_days,
        "evaluated_at": as_of.isoformat(),
        "policy": "delivery_hold_and_open_return_reserve",
    }
