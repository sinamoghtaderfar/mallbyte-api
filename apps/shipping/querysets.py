"""Database eligibility filtering before bounded shipment-order serialization."""
from django.db.models import Exists, OuterRef, Prefetch, Q, Subquery

from apps.orders.models import Order, OrderItem, SellerOrderFulfillment
from apps.shipping.models import Shipment

EXCLUDED_SHIPMENT_STATUSES = [Shipment.StatusChoices.CANCELLED, Shipment.StatusChoices.RETURNED]


def eligible_order_queryset():
    active = Shipment.objects.exclude(status__in=EXCLUDED_SHIPMENT_STATUSES)
    active_for_order = active.filter(order_id=OuterRef("pk"))
    status = SellerOrderFulfillment.objects.filter(
        order_id=OuterRef("order_id"), seller_id=OuterRef("product__seller_id"),
    ).values("status")[:1]
    assigned = active.filter(
        order_id=OuterRef("order_id"), seller_fulfillment__seller_id=OuterRef("product__seller_id"),
    )
    eligible_items = OrderItem.objects.filter(order_id=OuterRef("pk")).annotate(
        _seller_state=Subquery(status), _assigned=Exists(assigned),
    ).filter(
        Q(_seller_state__isnull=True) | Q(_seller_state__in=[Order.StatusChoices.PAID, Order.StatusChoices.PROCESSING]),
        _assigned=False,
    )
    return Order.objects.select_related("user").filter(
        status__in=[Order.StatusChoices.PAID, Order.StatusChoices.PROCESSING],
        payment_status=Order.PaymentStatusChoices.PAID,
    ).annotate(
        _has_items=Exists(OrderItem.objects.filter(order_id=OuterRef("pk"))),
        _has_active=Exists(active_for_order),
        _has_legacy=Exists(active_for_order.filter(seller_fulfillment__isnull=True)),
        _has_eligible=Exists(eligible_items),
    ).filter(_has_legacy=False).filter(
        Q(_has_items=False, _has_active=False) | Q(_has_items=True, _has_eligible=True),
    ).prefetch_related(
        Prefetch("items", queryset=OrderItem.objects.select_related("product__seller")),
        "seller_fulfillments",
        Prefetch("shipments", queryset=active.select_related("seller_fulfillment"), to_attr="active_shipping_shipments"),
    ).order_by("-paid_at", "-created_at", "-pk")
