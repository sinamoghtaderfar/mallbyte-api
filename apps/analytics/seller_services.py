"""Seller-scoped merchandise analytics with immutable snapshots and legacy fallback.

NOT settlement/profit. Snapshot totals include checkout discounts and verified
partial merchandise refunds. Older unsnapshotted records use historical legacy
semantics; they must be migrated before trustworthy historical ownership reports.
"""
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal

from django.db.models import OuterRef, Subquery
from django.utils import timezone

from apps.analytics.financial import CAPTURED_STATUSES, format_money, get_financial_window
from apps.orders.models import OrderItem
from apps.payments.models import Payment
from apps.products.models import Product
from apps.settlements.models import ItemAllocation, RefundAllocation

ZERO = Decimal("0")


def _empty():
    return {"gross": ZERO, "discount": ZERO, "refund": ZERO,
            "units": 0, "fully_refunded_units": 0}


def _key(row, dimension, day):
    currency = str(row["currency"]).upper()
    if dimension == "timeseries":
        return (currency, day)
    if dimension == "products":
        return (currency, row["product_id"], row["name"], row["sku"])
    return (currency,)


def _add(buckets, row, dimension, event_at, *, kind):
    day = timezone.localtime(event_at).date() if event_at else None
    bucket = buckets[_key(row, dimension, day)]
    if kind == "sale":
        bucket["gross"] += row["gross"]
        bucket["discount"] += row["discount"]
        bucket["units"] += row["quantity"]
    else:
        bucket["refund"] += row["refund"]
        bucket["fully_refunded_units"] += row.get("fully_refunded_units", 0)


def _format(bucket):
    gross, discount, refunds = bucket["gross"], bucket["discount"], bucket["refund"]
    return {
        "gross_merchandise_value": format_money(gross),
        "discount_amount": format_money(discount),
        "merchandise_after_discount": format_money(gross - discount),
        "refunded_merchandise_value": format_money(refunds),
        # Deprecated compatibility field: includes PARTIAL refunds in new snapshots.
        "fully_refunded_merchandise_value": format_money(refunds),
        "net_merchandise_value": format_money(gross - discount - refunds),
        "units_sold": bucket["units"],
        # Units cannot be reconstructed reliably from amount-only partial refunds.
        "fully_refunded_units": bucket["fully_refunded_units"],
    }


def _in_window(at, window):
    return at is not None and at < window.end_exclusive_at and (
        window.start_at is None or at >= window.start_at
    )


def get_seller_analytics(*, seller_id, period="month", start_date=None,
                         end_date=None, dimension="dashboard", limit=10):
    window = get_financial_window(
        period=period, start_date=start_date, end_date=end_date
    )
    if dimension not in {"dashboard", "timeseries", "products"}:
        raise ValueError("Invalid analytics dimension")
    if dimension == "timeseries":
        if window.start_at is None:
            raise ValueError("Time series requires a bounded date range.")
        first = timezone.localtime(window.start_at).date()
        last = timezone.localtime(
            window.end_exclusive_at - timedelta(microseconds=1)
        ).date()
        if (last - first).days > 365:
            raise ValueError("Time series supports at most 366 calendar days.")

    buckets = defaultdict(_empty)
    totals = defaultdict(_empty)

    def put(row, at, *, kind):
        if not _in_window(at, window):
            return
        _add(buckets, row, dimension, at, kind=kind)
        _add(totals, row, "dashboard", at, kind=kind)

    # Read snapshot ownership and merchandise amounts as they were at checkout.
    # A scalar subquery avoids double-counting if an order has several attempts.
    captures = Payment.objects.filter(
        order_id=OuterRef("order_item__order_id"),
        status__in=CAPTURED_STATUSES,
        paid_at__isnull=False,
    ).order_by("paid_at", "pk")
    snapshots = (
        ItemAllocation.objects.filter(seller_id=seller_id)
        .annotate(captured_at=Subquery(captures.values("paid_at")[:1]))
        .filter(captured_at__isnull=False, captured_at__lt=window.end_exclusive_at)
    )
    if window.start_at is not None:
        snapshots = snapshots.filter(captured_at__gte=window.start_at)
    for allocation in snapshots.select_related("order_item").iterator(chunk_size=500):
        item = allocation.order_item
        put({"currency": allocation.currency, "product_id": item.product_id,
             "name": item.product_name, "sku": item.product_sku,
             "gross": allocation.gross, "discount": allocation.discount,
             "quantity": allocation.quantity}, allocation.captured_at, kind="sale")

    # Verified refunds are item-level and can be partial. They use original
    # ownership, never Product.seller (which can change after a sale).
    refunds = RefundAllocation.objects.filter(
        allocation__seller_id=seller_id,
        refund__confirmed_at__lt=window.end_exclusive_at,
    )
    if window.start_at is not None:
        refunds = refunds.filter(refund__confirmed_at__gte=window.start_at)
    for line in refunds.select_related("allocation__order_item", "refund").iterator(chunk_size=500):
        item = line.allocation.order_item
        put({"currency": line.allocation.currency, "product_id": item.product_id,
             "name": item.product_name, "sku": item.product_sku,
             "refund": line.customer_merchandise}, line.refund.confirmed_at, kind="refund")

    # Historical records created BEFORE ItemAllocation existed. Retain the
    # previous API behavior for these only, with explicit data-quality notice.
    legacy = OrderItem.objects.filter(
        financial_allocation__isnull=True, product__seller_id=seller_id
    )
    for refund in (False, True):
        field = "order__payments__refunded_at" if refund else "order__payments__paid_at"
        statuses = ((Payment.StatusChoices.REFUNDED,) if refund else CAPTURED_STATUSES)
        conditions = {
            "order__payments__status__in": statuses,
            f"{field}__isnull": False,
            f"{field}__lt": window.end_exclusive_at,
        }
        if window.start_at is not None:
            conditions[f"{field}__gte"] = window.start_at
        rows = legacy.filter(**conditions).values(
            "product_id", "product_name", "product_sku", "quantity",
            "total_price", "order__payments__currency", field,
        )
        for item in rows.iterator(chunk_size=500):
            row = {"currency": item["order__payments__currency"],
                   "product_id": item["product_id"],
                   "name": item["product_name"], "sku": item["product_sku"]}
            if refund:
                row.update(refund=item["total_price"], fully_refunded_units=item["quantity"])
            else:
                row.update(gross=item["total_price"], discount=ZERO, quantity=item["quantity"])
            put(row, item[field], kind="refund" if refund else "sale")

    currencies = sorted({key[0] for key in totals})
    result = {
        "metric_contract_version": 2,
        "scope": {"type": "seller", "seller_id": seller_id},
        "filters": {
            "period": window.period,
            "start_at": window.start_at.isoformat() if window.start_at else None,
            "end_exclusive_at": window.end_exclusive_at.isoformat(),
            "timezone": timezone.get_current_timezone_name(),
        },
        "currencies": [
            {"currency": currency, **_format(totals[(currency,)])}
            for currency in currencies
        ],
        "accounting_notes": {
            "metric_type": "order_item_merchandise_value",
            "recognition": "payment.paid_at / confirmed_refund.confirmed_at",
            "discounts_shipping_tax_included": False,
            "checkout_discounts_in_net": True,
            "partial_refunds_supported": True,
            "seller_payout_or_profit": False,
            "seller_ownership_source": "checkout_snapshot_with_legacy_fallback",
            "legacy_records_note": "Unsnapshotted legacy orders use current product ownership; backfill for accurate history.",
            "refunded_units_note": "Amount-only partial refunds cannot reliably determine refunded unit counts.",
        },
    }
    if dimension == "dashboard":
        products = Product.objects.filter(seller_id=seller_id)
        result["catalog"] = {
            "total_products": products.count(),
            "active_products": products.filter(is_active=True).count(),
        }
    elif dimension == "timeseries":
        result["series"] = [{
            "currency": currency,
            "points": [
                {"date": (first + timedelta(days=i)).isoformat(),
                 **_format(buckets.get((currency, first + timedelta(days=i)), _empty()))}
                for i in range((last - first).days + 1)
            ],
        } for currency in currencies]
    else:
        grouped = defaultdict(list)
        for key, values in buckets.items():
            currency, product_id, name, sku = key
            grouped[currency].append({
                "product_id": product_id, "name": name, "sku": sku,
                **_format(values),
            })
        result["products_by_currency"] = [{
            "currency": currency,
            "products": sorted(rows, key=lambda r: (
                -Decimal(r["gross_merchandise_value"]), -r["units_sold"],
                r["product_id"] or 0,
            ))[:limit],
        } for currency, rows in sorted(grouped.items())]
    return result
