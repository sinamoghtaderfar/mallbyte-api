"""Refund merchandise consideration from order snapshots, never current prices."""
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db.models import Sum

from apps.returns.models import ReturnItem, ReturnRequest
from apps.settlements.models import ItemAllocation
from apps.settlements.services import allocate, money


def merchandise_net_by_item(order):
    items = list(order.items.order_by("pk"))
    gross = [money(item.total_price) for item in items]
    if not items or sum(gross, Decimal("0.00")) != money(order.subtotal):
        raise ValidationError("Order item totals require reconciliation before a return.")
    if order.discount_amount < 0 or order.discount_amount > order.subtotal:
        raise ValidationError("Order discount requires reconciliation before a return.")
    snapshots = {row.order_item_id: row for row in ItemAllocation.objects.filter(order_item__order_id=order.pk)}
    if snapshots:
        if set(snapshots) != {item.pk for item in items}:
            raise ValidationError("Incomplete financial snapshots require manual reconciliation.")
        for item in items:
            row = snapshots[item.pk]
            if row.quantity != item.quantity or money(row.gross) != money(item.total_price):
                raise ValidationError("Order items differ from their financial snapshots.")
        net = {item.pk: money(snapshots[item.pk].merchandise_net) for item in items}
        if any(value < 0 for value in net.values()) or sum(net.values()) != money(order.subtotal - order.discount_amount):
            raise ValidationError("Financial snapshot discounts require reconciliation.")
        return net
    discounts = allocate(order.discount_amount, gross)
    return {item.pk: money(item.total_price - discounts[index]) for index, item in enumerate(items)}


def refund_amount_for_quantity(order_item, quantity, net):
    # The owning order is locked by create_return_request. Active claims reserve
    # both quantity and consideration; a final partial claim takes the remainder.
    prior = ReturnItem.objects.filter(order_item=order_item).exclude(
        return_request__status__in=[ReturnRequest.Status.REJECTED, ReturnRequest.Status.CANCELLED],
    ).aggregate(quantity=Sum("quantity"), amount=Sum("requested_refund_amount"))
    used_quantity = prior["quantity"] or 0
    used_amount = money(prior["amount"] or 0)
    remaining_quantity = order_item.quantity - used_quantity
    if quantity <= 0 or quantity > remaining_quantity:
        raise ValidationError(f"You can return at most {remaining_quantity} item(s) for {order_item.product_name}.")
    remaining_amount = money(net - used_amount)
    if remaining_amount < 0:
        raise ValidationError("Existing return amounts require manual reconciliation.")
    if quantity == remaining_quantity:
        return remaining_amount
    return min(money(net * Decimal(quantity) / order_item.quantity), remaining_amount)
