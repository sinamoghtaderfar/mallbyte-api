"""Read-only financial reconciliation. Does not post or transfer money."""

from decimal import Decimal

from django.db.models import (
    CharField,
    Count,
    DecimalField,
    Exists,
    F,
    OuterRef,
    Q,
    Subquery,
    Sum,
    Value,
)
from django.db.models.functions import Cast, Concat
from django.utils import timezone

from apps.orders.models import Order, OrderItem
from apps.payments.models import Payment
from apps.returns.models import ReturnRequest
from apps.settlements.models import (
    ConfirmedPayout,
    ConfirmedRefund,
    ItemAllocation,
    RefundAllocation,
    SellerLedgerEntry,
)

MONEY = DecimalField(max_digits=24, decimal_places=2)
ZERO = Decimal("0.00")

CAPTURED = (
    Payment.StatusChoices.SUCCESS,
    Payment.StatusChoices.REFUNDED,
)


def _money(value):
    return str((value or ZERO).quantize(Decimal("0.01")))


def _sum_subquery(queryset, grouping_field, amount_field):
    return Subquery(
        queryset.order_by()
        .values(grouping_field)
        .annotate(total=Sum(amount_field))
        .values("total")[:1],
        output_field=MONEY,
    )


def _sample(queryset, limit):
    return {
        "count": queryset.count(),
        "sample_ids": list(
            queryset.order_by("pk").values_list("pk", flat=True)[:limit]
        ),
    }


def reconciliation_report(*, sample_limit=20):
    """
    All-time snapshot consistency report.

    Samples are bounded; counts cover all matching records.
    This does not establish external bank settlement.
    """

    captured_for_order = Payment.objects.filter(
        order_id=OuterRef("order_id"),
        status__in=CAPTURED,
        paid_at__isnull=False,
    )

    captured_for_allocation = Payment.objects.filter(
        order_id=OuterRef("order_item__order_id"),
        status__in=CAPTURED,
        paid_at__isnull=False,
    )

    # 1. Captured order items without financial snapshots.
    missing_snapshots = OrderItem.objects.annotate(
        has_capture=Exists(captured_for_order)
    ).filter(
        has_capture=True,
        financial_allocation__isnull=True,
    )

    # 2. Order total differs from sum of item allocations.
    allocation_total = _sum_subquery(
        ItemAllocation.objects.filter(order_item__order_id=OuterRef("pk")),
        "order_item__order_id",
        "charged",
    )

    bad_order_totals = (
        Order.objects.annotate(snapshot_total=allocation_total)
        .filter(snapshot_total__isnull=False)
        .exclude(total_amount=F("snapshot_total"))
    )

    # 3. Captured allocations missing their seller credit.
    valid_sale = SellerLedgerEntry.objects.filter(
        allocation_id=OuterRef("pk"),
        seller_id=OuterRef("seller_id"),
        currency=OuterRef("currency"),
        amount=OuterRef("seller_payable"),
        kind=SellerLedgerEntry.Kind.SALE,
    )

    missing_sales = ItemAllocation.objects.annotate(
        has_capture=Exists(captured_for_allocation),
        has_sale=Exists(valid_sale),
    ).filter(
        has_capture=True,
        has_sale=False,
        seller_payable__gt=0,
    )

    # 4. More than one sale credit for an allocation.
    duplicate_sales = (
        SellerLedgerEntry.objects.filter(
            kind=SellerLedgerEntry.Kind.SALE,
            allocation_id__isnull=False,
        )
        .values("allocation_id")
        .annotate(entry_count=Count("pk"))
        .filter(entry_count__gt=1)
    )

    # 5. Ledger sale entries inconsistent with snapshots.
    bad_sale_entries = SellerLedgerEntry.objects.filter(
        kind=SellerLedgerEntry.Kind.SALE,
    ).filter(
        Q(allocation__isnull=True)
        | ~Q(seller_id=F("allocation__seller_id"))
        | ~Q(currency=F("allocation__currency"))
        | ~Q(amount=F("allocation__seller_payable"))
    )

    # 6. Confirmed refund total differs from item allocations.
    refund_total = _sum_subquery(
        RefundAllocation.objects.filter(refund_id=OuterRef("pk")),
        "refund_id",
        "customer_amount",
    )

    bad_refunds = ConfirmedRefund.objects.annotate(allocated_total=refund_total).filter(
        Q(allocated_total__isnull=True) | ~Q(amount=F("allocated_total"))
    )

    # 7. Refund seller debit is missing or incorrect.
    refund_ledger = (
        SellerLedgerEntry.objects.filter(
            kind=SellerLedgerEntry.Kind.REFUND,
            allocation_id=OuterRef("allocation_id"),
            refund_id=OuterRef("refund_id"),
            seller_id=OuterRef("allocation__seller_id"),
            currency=OuterRef("allocation__currency"),
        )
        .order_by("pk")
        .values("amount")[:1]
    )

    missing_refund_debits = (
        RefundAllocation.objects.filter(seller_reversal__gt=0)
        .annotate(
            recorded_amount=Subquery(
                refund_ledger,
                output_field=MONEY,
            )
        )
        .filter(
            Q(recorded_amount__isnull=True) | ~Q(recorded_amount=-F("seller_reversal"))
        )
    )

    # 8. Confirmed payouts without matching ledger debits.
    payout_ledger = (
        SellerLedgerEntry.objects.filter(
            kind=SellerLedgerEntry.Kind.PAYOUT,
            seller_id=OuterRef("seller_id"),
            currency=OuterRef("currency"),
            source_key=Concat(
                Value("payout:"),
                Cast(OuterRef("pk"), CharField()),
            ),
        )
        .order_by("pk")
        .values("amount")[:1]
    )

    missing_payout_debits = ConfirmedPayout.objects.annotate(
        recorded_amount=Subquery(
            payout_ledger,
            output_field=MONEY,
        )
    ).filter(Q(recorded_amount__isnull=True) | ~Q(recorded_amount=-F("amount")))

    # 9. Captured payment amount differs from order total.
    captured_amount_mismatches = Payment.objects.filter(
        status__in=CAPTURED,
        paid_at__isnull=False,
    ).exclude(amount=F("order__total_amount"))

    # 10. Legacy refunded payments without verified evidence.
    unverified_legacy_refunds = Payment.objects.filter(
        status=Payment.StatusChoices.REFUNDED,
        settlement_refunds__isnull=True,
    )

    # 11. Return marked refunded without financial evidence.
    unverified_returns = ReturnRequest.objects.filter(
        status=ReturnRequest.Status.REFUNDED,
        confirmed_financial_refunds__isnull=True,
    )

    def group_sample(queryset):
        return {
            "count": queryset.count(),
            "sample_allocation_ids": list(
                queryset.order_by("allocation_id").values_list(
                    "allocation_id",
                    flat=True,
                )[:sample_limit]
            ),
        }

    findings = {
        "captured_items_missing_snapshot": _sample(
            missing_snapshots,
            sample_limit,
        ),
        "order_snapshot_total_mismatch": _sample(
            bad_order_totals,
            sample_limit,
        ),
        "captured_allocations_missing_sale_credit": _sample(
            missing_sales,
            sample_limit,
        ),
        "duplicate_sale_credits_per_allocation": group_sample(
            duplicate_sales,
        ),
        "sale_credit_snapshot_mismatch": _sample(
            bad_sale_entries,
            sample_limit,
        ),
        "refund_total_allocation_mismatch": _sample(
            bad_refunds,
            sample_limit,
        ),
        "refund_missing_or_incorrect_seller_debit": _sample(
            missing_refund_debits,
            sample_limit,
        ),
        "payout_missing_or_incorrect_seller_debit": _sample(
            missing_payout_debits,
            sample_limit,
        ),
        "captured_payment_order_amount_mismatch": _sample(
            captured_amount_mismatches,
            sample_limit,
        ),
        "legacy_refunded_payment_without_evidence": _sample(
            unverified_legacy_refunds,
            sample_limit,
        ),
        "return_refunded_without_verified_evidence": _sample(
            unverified_returns,
            sample_limit,
        ),
    }

    # 12. Negative seller balances.
    balances = (
        SellerLedgerEntry.objects.values(
            "seller_id",
            "currency",
        )
        .annotate(balance=Sum("amount"))
        .filter(balance__lt=0)
        .order_by("seller_id", "currency")
    )

    findings["negative_seller_balance"] = {
        "count": balances.count(),
        "samples": [
            {
                "seller_id": row["seller_id"],
                "currency": row["currency"],
                "balance": _money(row["balance"]),
            }
            for row in balances[:sample_limit]
        ],
    }

    total = sum(item["count"] for item in findings.values())

    return {
        "version": 1,
        "scope": "platform",
        "generated_at": timezone.now().isoformat(),
        "status": ("warnings" if total else "no_detected_mismatches"),
        "total_findings": total,
        "sample_limit_per_check": sample_limit,
        "findings": findings,
        "notes": [
            (
                "Read-only database checks; this is NOT "
                "bank or processor reconciliation."
            ),
            (
                "All-time metrics; legacy payment/refund "
                "records may need manual review."
            ),
            (
                "Sample IDs are limited; count is the "
                "full number of matching records."
            ),
            ("Concurrent financial postings can change " "values between queries."),
        ],
    }


def seller_balance_rows(*, seller_id=None, currency=None):
    """Read-only grouped seller balances by currency."""

    queryset = SellerLedgerEntry.objects.all()

    if seller_id is not None:
        queryset = queryset.filter(seller_id=seller_id)

    if currency:
        queryset = queryset.filter(currency=currency.upper())

    return (
        queryset.values(
            "seller_id",
            "currency",
        )
        .annotate(
            balance=Sum("amount"),
            entry_count=Count("pk"),
        )
        .order_by(
            "seller_id",
            "currency",
        )
    )
