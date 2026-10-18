"""Currency-safe financial reporting for analytics endpoints."""

from datetime import datetime, timedelta
from decimal import Decimal

from django.db.models import Count, F, Sum
from django.db.models.functions import TruncDate, Upper
from django.utils import timezone

from apps.analytics.financial import (
    CAPTURED_STATUSES,
    FinancialWindow,
    filter_event_window,
    format_money,
    get_financial_cashflow,
)
from apps.payments.models import Payment

ZERO = Decimal("0")


def _grouped_events(
    window,
    *,
    field_name,
    statuses,
    dimension,
):
    queryset = filter_event_window(
        Payment.objects.filter(status__in=statuses),
        field_name=field_name,
        window=window,
    )

    group_expression = (
        TruncDate(
            field_name,
            tzinfo=timezone.get_current_timezone(),
        )
        if dimension == "date"
        else F("provider")
    )

    return (
        queryset.annotate(
            currency_code=Upper("currency"),
            group_value=group_expression,
        )
        .values("currency_code", "group_value")
        .annotate(
            amount=Sum("amount"),
            count=Count("id"),
        )
        .order_by("currency_code", "group_value")
    )


def _build_grouped_cashflow(window, dimension):
    buckets = {}

    events = (
        (
            "captured",
            "paid_at",
            CAPTURED_STATUSES,
        ),
        (
            "refunded",
            "refunded_at",
            (Payment.StatusChoices.REFUNDED,),
        ),
    )

    for kind, field, statuses in events:
        rows = _grouped_events(
            window,
            field_name=field,
            statuses=statuses,
            dimension=dimension,
        )

        for row in rows:
            key = (
                row["group_value"],
                row["currency_code"],
            )

            bucket = buckets.setdefault(
                key,
                {
                    "captured": ZERO,
                    "refunded": ZERO,
                    "captured_count": 0,
                    "refunded_count": 0,
                },
            )

            bucket[kind] += row["amount"] or ZERO
            bucket[f"{kind}_count"] += row["count"]

    return buckets


def _formatted_bucket(bucket):
    bucket = bucket or {}

    captured = bucket.get("captured", ZERO)
    refunded = bucket.get("refunded", ZERO)

    return {
        "captured_amount": format_money(captured),
        "refunded_amount": format_money(refunded),
        "net_cash_flow": format_money(captured - refunded),
        "captured_payments_count": bucket.get(
            "captured_count",
            0,
        ),
        "refunded_payments_count": bucket.get(
            "refunded_count",
            0,
        ),
    }


def _build_daily_series(window, currencies):
    if window.start_at is None:
        raise ValueError("Daily financial series needs a bounded date range.")

    tz = timezone.get_current_timezone()

    first_day = timezone.localtime(
        window.start_at,
        tz,
    ).date()

    last_day = timezone.localtime(
        window.end_exclusive_at - timedelta(microseconds=1),
        tz,
    ).date()

    grouped = _build_grouped_cashflow(
        window,
        "date",
    )

    days_count = max(
        (last_day - first_day).days + 1,
        0,
    )

    series = []

    for currency in currencies:
        points = []

        for day_index in range(days_count):
            day = first_day + timedelta(days=day_index)

            points.append(
                {
                    "date": day.isoformat(),
                    **_formatted_bucket(grouped.get((day, currency))),
                }
            )

        series.append(
            {
                "currency": currency,
                "points": points,
            }
        )

    return series


def _build_provider_breakdown(window):
    grouped = _build_grouped_cashflow(
        window,
        "provider",
    )

    return [
        {
            "provider": provider,
            "currency": currency,
            **_formatted_bucket(bucket),
        }
        for (provider, currency), bucket in sorted(grouped.items())
    ]


def get_reporting_financial(
    *,
    period="month",
    start_date=None,
    end_date=None,
    include_series=False,
    include_providers=False,
):
    result = get_financial_cashflow(
        period=period,
        start_date=start_date,
        end_date=end_date,
    )

    if include_series or include_providers:
        # Use the exact snapshot window from the canonical
        # financial response. Do not call now() again.
        filters = result["filters"]

        window = FinancialWindow(
            period=filters["period"],
            start_at=(
                datetime.fromisoformat(filters["start_at"])
                if filters["start_at"]
                else None
            ),
            end_exclusive_at=datetime.fromisoformat(filters["end_exclusive_at"]),
        )

        if include_series:
            result["series"] = _build_daily_series(
                window,
                [row["currency"] for row in result["currencies"]],
            )

        if include_providers:
            result["by_provider"] = _build_provider_breakdown(window)

    return result
