"""Read-only seller-scoped merchandise analytics (not seller settlement)."""

from datetime import timedelta
from decimal import Decimal

from django.db.models import Count, Sum
from django.db.models.functions import TruncDate, Upper
from django.utils import timezone

from apps.analytics.financial import (
    CAPTURED_STATUSES,
    format_money,
    get_financial_window,
)
from apps.orders.models import OrderItem
from apps.payments.models import Payment
from apps.products.models import Product

ZERO = Decimal("0")


def _seller_events(seller_id, window, *, refund=False):
    """Single filter() keeps all payment constraints on the SAME join."""
    field = "order__payments__refunded_at" if refund else "order__payments__paid_at"
    statuses = (Payment.StatusChoices.REFUNDED,) if refund else CAPTURED_STATUSES
    conditions = {
        "product__seller_id": seller_id,
        "order__payments__status__in": statuses,
        f"{field}__isnull": False,
        f"{field}__lt": window.end_exclusive_at,
    }
    if window.start_at is not None:
        conditions[f"{field}__gte"] = window.start_at
    return OrderItem.objects.filter(**conditions), field


def _group(seller_id, window, *, refund=False, dimension="currency"):
    queryset, field = _seller_events(seller_id, window, refund=refund)
    expressions = {"currency_code": Upper("order__payments__currency")}
    fields = ["currency_code"]
    if dimension == "day":
        expressions["event_day"] = TruncDate(
            field, tzinfo=timezone.get_current_timezone()
        )
        fields.append("event_day")
    elif dimension == "product":
        fields.extend(("product_id", "product__name", "product__sku"))
    return list(
        queryset.annotate(**expressions)
        .values(*fields)
        .annotate(
            amount=Sum("total_price"),
            units=Sum("quantity"),
            orders_count=Count("order_id", distinct=True),
        )
        .order_by(*fields)
    )


def _blank():
    return {"gross": ZERO, "refund": ZERO, "units": 0, "refunded_units": 0, "orders": 0}


def _format(bucket):
    return {
        "gross_merchandise_value": format_money(bucket["gross"]),
        "fully_refunded_merchandise_value": format_money(bucket["refund"]),
        "net_merchandise_value": format_money(bucket["gross"] - bucket["refund"]),
        "units_sold": bucket["units"],
        "fully_refunded_units": bucket["refunded_units"],
    }


def _update(buckets, key, row, *, refund):
    item = buckets.setdefault(key, _blank())
    amount = row["amount"] or ZERO
    units = row["units"] or 0
    if refund:
        item["refund"] += amount
        item["refunded_units"] += units
    else:
        item["gross"] += amount
        item["units"] += units


def get_seller_analytics(
    *, seller_id, period="month", start_date=None, end_date=None,
    dimension="dashboard", limit=10,
):
    window = get_financial_window(
        period=period, start_date=start_date, end_date=end_date,
    )
    if dimension == "timeseries":
        if window.start_at is None:
            raise ValueError("Time series requires a bounded date range.")
        first = timezone.localtime(window.start_at).date()
        last = timezone.localtime(
            window.end_exclusive_at - timedelta(microseconds=1)
        ).date()
        if (last - first).days > 365:
            raise ValueError("Time series supports at most 366 calendar days.")

    captured = _group(seller_id, window, refund=False)
    refunded = _group(seller_id, window, refund=True)
    buckets = {}
    for row in captured:
        _update(buckets, row["currency_code"], row, refund=False)
    for row in refunded:
        _update(buckets, row["currency_code"], row, refund=True)

    currency_totals = [
        {"currency": currency, **_format(buckets[currency])}
        for currency in sorted(buckets)
    ]

    result = {
        "metric_contract_version": 1,
        "scope": {"type": "seller", "seller_id": seller_id},
        "filters": {
            "period": window.period,
            "start_at": window.start_at.isoformat() if window.start_at else None,
            "end_exclusive_at": window.end_exclusive_at.isoformat(),
            "timezone": timezone.get_current_timezone_name(),
        },
        "currencies": currency_totals,
        "accounting_notes": {
            "metric_type": "order_item_merchandise_value",
            "recognition": "payment.paid_at and payment.refunded_at",
            "discounts_shipping_tax_included": False,
            "partial_refunds_supported": False,
            "seller_payout_or_profit": False,
            "seller_ownership_source": "current_product_seller_id",
        },
    }

    if dimension == "dashboard":
        products = Product.objects.filter(seller_id=seller_id)
        result["catalog"] = {
            "total_products": products.count(),
            "active_products": products.filter(is_active=True).count(),
        }

    if dimension == "timeseries":
        grouped = {}
        for refund in (False, True):
            for row in _group(seller_id, window, refund=refund, dimension="day"):
                _update(
                    grouped, (row["currency_code"], row["event_day"]),
                    row, refund=refund,
                )
        result["series"] = []
        count = (last - first).days + 1
        for currency in sorted(buckets):
            points = [
                {
                    "date": (first + timedelta(days=idx)).isoformat(),
                    **_format(grouped.get(
                        (currency, first + timedelta(days=idx)), _blank()
                    )),
                }
                for idx in range(count)
            ]
            result["series"].append({"currency": currency, "points": points})

    if dimension == "products":
        grouped = {}
        for refund in (False, True):
            for row in _group(seller_id, window, refund=refund, dimension="product"):
                key = (
                    row["currency_code"], row["product_id"],
                    row["product__name"], row["product__sku"],
                )
                _update(grouped, key, row, refund=refund)
        groups = {}
        for (currency, product_id, name, sku), bucket in grouped.items():
            groups.setdefault(currency, []).append({
                "product_id": product_id,
                "name": name,
                "sku": sku,
                **_format(bucket),
            })
        result["products_by_currency"] = [
            {
                "currency": currency,
                "products": sorted(
                    rows,
                    key=lambda row: (
                        -Decimal(row["gross_merchandise_value"]),
                        -row["units_sold"], row["product_id"],
                    ),
                )[:limit],
            }
            for currency, rows in sorted(groups.items())
        ]

    return result
