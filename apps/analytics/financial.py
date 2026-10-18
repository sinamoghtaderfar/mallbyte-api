from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.db.models import Count, F, Sum
from django.db.models.functions import Upper
from django.utils import timezone

from apps.payments.models import Payment

ZERO = Decimal("0.00")
CENT = Decimal("0.01")

CAPTURED_STATUSES = (
    Payment.StatusChoices.SUCCESS,
    Payment.StatusChoices.REFUNDED,
)


def format_money(value):
    amount = Decimal(str(value if value is not None else 0))
    return str(
        amount.quantize(
            CENT,
            rounding=ROUND_HALF_UP,
        )
    )


@dataclass(frozen=True)
class FinancialWindow:
    period: str
    start_at: datetime | None
    end_exclusive_at: datetime


def local_midnight(day: date):
    return timezone.make_aware(
        datetime.combine(day, time.min),
        timezone.get_current_timezone(),
    )


def get_financial_window(
    *,
    period="month",
    start_date=None,
    end_date=None,
):
    now = timezone.now()
    today = timezone.localdate(now)

    if start_date is not None and end_date is not None:
        return FinancialWindow(
            period="custom",
            start_at=local_midnight(start_date),
            end_exclusive_at=local_midnight(end_date + timedelta(days=1)),
        )

    if period == "all":
        return FinancialWindow(
            period="all",
            start_at=None,
            end_exclusive_at=now,
        )

    days = {
        "today": 1,
        "week": 7,
        "month": 30,
        "year": 365,
    }

    if period not in days:
        raise ValueError("Unsupported financial period.")

    first_day = today - timedelta(days=days[period] - 1)

    return FinancialWindow(
        period=period,
        start_at=local_midnight(first_day),
        end_exclusive_at=now,
    )


def filter_event_window(
    queryset,
    *,
    field_name,
    window,
):
    queryset = queryset.filter(
        **{
            f"{field_name}__isnull": False,
            f"{field_name}__lt": window.end_exclusive_at,
        }
    )

    if window.start_at is not None:
        queryset = queryset.filter(
            **{
                f"{field_name}__gte": window.start_at,
            }
        )

    return queryset


def aggregate_currency_events(queryset):
    return (
        queryset.annotate(currency_code=Upper("currency"))
        .values("currency_code")
        .annotate(
            total=Sum("amount"),
            count=Count("id"),
        )
        .order_by("currency_code")
    )


def get_financial_data_quality():
    completed = Payment.objects.filter(
        status__in=CAPTURED_STATUSES,
    )

    missing_paid_at = completed.filter(
        paid_at__isnull=True,
    ).count()

    missing_refunded_at = Payment.objects.filter(
        status=Payment.StatusChoices.REFUNDED,
        refunded_at__isnull=True,
    ).count()

    mismatched_payment_amounts = (
        completed.filter(paid_at__isnull=False)
        .exclude(amount=F("order__total_amount"))
        .count()
    )

    multiple_captured_order_count = (
        completed.filter(paid_at__isnull=False)
        .values("order_id")
        .annotate(payment_count=Count("id"))
        .filter(payment_count__gt=1)
        .count()
    )

    has_warnings = any(
        (
            missing_paid_at,
            missing_refunded_at,
            mismatched_payment_amounts,
            multiple_captured_order_count,
        )
    )

    return {
        "has_warnings": has_warnings,
        "completed_payments_without_paid_at": (missing_paid_at),
        "refunded_payments_without_refunded_at": (missing_refunded_at),
        "payment_order_amount_mismatches": (mismatched_payment_amounts),
        "orders_with_multiple_captured_payments": (multiple_captured_order_count),
        "scope": "all_time",
    }


def get_financial_cashflow(
    *,
    period="month",
    start_date=None,
    end_date=None,
):
    window = get_financial_window(
        period=period,
        start_date=start_date,
        end_date=end_date,
    )

    # A refunded payment was previously captured.
    # Keep it in the capture history using paid_at.
    captured_payments = Payment.objects.filter(
        status__in=CAPTURED_STATUSES,
    )
    captured_payments = filter_event_window(
        captured_payments,
        field_name="paid_at",
        window=window,
    )

    # A refund is recognized as a cash outflow on refunded_at.
    # Status REFUNDED is treated as a full-payment reversal.
    refunded_payments = Payment.objects.filter(
        status=Payment.StatusChoices.REFUNDED,
    )
    refunded_payments = filter_event_window(
        refunded_payments,
        field_name="refunded_at",
        window=window,
    )

    buckets = {}

    def get_bucket(currency):
        if currency not in buckets:
            buckets[currency] = {
                "currency": currency,
                "captured": ZERO,
                "refunded": ZERO,
                "captured_count": 0,
                "refunded_count": 0,
            }

        return buckets[currency]

    for row in aggregate_currency_events(captured_payments):
        bucket = get_bucket(row["currency_code"])

        bucket["captured"] = row["total"] or ZERO
        bucket["captured_count"] = row["count"]

    for row in aggregate_currency_events(refunded_payments):
        bucket = get_bucket(row["currency_code"])

        bucket["refunded"] = row["total"] or ZERO
        bucket["refunded_count"] = row["count"]

    currencies = []

    for currency in sorted(buckets):
        bucket = buckets[currency]

        net_cash_flow = bucket["captured"] - bucket["refunded"]

        currencies.append(
            {
                "currency": currency,
                "captured_amount": format_money(bucket["captured"]),
                "refunded_amount": format_money(bucket["refunded"]),
                "net_cash_flow": format_money(net_cash_flow),
                "captured_payments_count": (bucket["captured_count"]),
                "refunded_payments_count": (bucket["refunded_count"]),
            }
        )

    return {
        "metric_contract_version": 1,
        "filters": {
            "period": window.period,
            "timezone": (timezone.get_current_timezone_name()),
            "start_at": (window.start_at.isoformat() if window.start_at else None),
            "end_exclusive_at": (window.end_exclusive_at.isoformat()),
        },
        "currencies": currencies,
        "data_quality": get_financial_data_quality(),
        "accounting_notes": {
            "metric_type": "cash_flow",
            "capture_date_field": "paid_at",
            "refund_date_field": "refunded_at",
            "full_refunds_supported": True,
            "partial_refunds_supported": False,
            "platform_profit_calculated": False,
            "tax_and_fee_adjustments_included": False,
        },
    }
