from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from apps.orders.models import Order, OrderItem
from apps.returns.models import (
    ReturnItem,
    ReturnRequest,
    ReturnShipment,
    ReturnStatusHistory,
)


def is_admin_user(user):
    return user.is_staff or user.is_superuser


def create_return_status_history(
    return_request, old_status, new_status, user=None, note=""
):
    return ReturnStatusHistory.objects.create(
        return_request=return_request,
        old_status=old_status or "",
        new_status=new_status,
        changed_by=user,
        note=note or "",
    )


def get_already_returned_quantity(order_item):
    result = (
        ReturnItem.objects.filter(order_item=order_item)
        .exclude(
            return_request__status__in=[
                ReturnRequest.Status.REJECTED,
                ReturnRequest.Status.CANCELLED,
            ]
        )
        .aggregate(total=Sum("quantity"))
    )

    return result["total"] or 0


@transaction.atomic
def create_return_request(
    *,
    customer,
    order,
    items,
    reason,
    requested_resolution,
    refund_method,
    customer_note="",
):
    order = Order.objects.select_for_update().get(pk=order.pk)

    if order.user_id != customer.id:
        raise ValidationError("You can only return your own orders.")

    if order.status != Order.StatusChoices.DELIVERED:
        raise ValidationError("Only delivered orders can be returned.")

    if not items:
        raise ValidationError("At least one return item is required.")

    return_request = ReturnRequest.objects.create(
        customer=customer,
        order=order,
        status=ReturnRequest.Status.SUBMITTED,
        reason=reason,
        requested_resolution=requested_resolution,
        refund_method=refund_method,
        customer_note=customer_note or "",
        total_requested_amount=Decimal("0"),
        total_approved_amount=Decimal("0"),
    )

    total_requested_amount = Decimal("0")

    for item_data in items:
        order_item = OrderItem.objects.select_for_update().get(
            pk=item_data["order_item"].pk
        )

        if order_item.order_id != order.id:
            raise ValidationError("Return item does not belong to this order.")

        quantity = item_data["quantity"]

        if quantity <= 0:
            raise ValidationError("Return quantity must be greater than zero.")

        already_returned_quantity = get_already_returned_quantity(order_item)
        available_quantity = order_item.quantity - already_returned_quantity

        if quantity > available_quantity:
            raise ValidationError(
                f"You can return at most {available_quantity} item(s) for {order_item.product_name}."
            )

        requested_refund_amount = order_item.unit_price * quantity
        total_requested_amount += requested_refund_amount

        ReturnItem.objects.create(
            return_request=return_request,
            order_item=order_item,
            quantity=quantity,
            reason=item_data.get("reason") or reason,
            condition=item_data.get("condition") or ReturnItem.ItemCondition.UNKNOWN,
            status=ReturnItem.ItemStatus.REQUESTED,
            customer_note=item_data.get("customer_note", ""),
            requested_refund_amount=requested_refund_amount,
            approved_refund_amount=Decimal("0"),
        )

    return_request.total_requested_amount = total_requested_amount
    return_request.save(update_fields=["total_requested_amount", "updated_at"])

    create_return_status_history(
        return_request=return_request,
        old_status="",
        new_status=ReturnRequest.Status.SUBMITTED,
        user=customer,
        note="Return request submitted.",
    )

    return return_request


@transaction.atomic
def cancel_return_request(*, return_request, user, note=""):
    return_request = ReturnRequest.objects.select_for_update().get(pk=return_request.pk)

    if not is_admin_user(user) and return_request.customer_id != user.id:
        raise ValidationError("You cannot cancel this return request.")

    if return_request.status not in [
        ReturnRequest.Status.DRAFT,
        ReturnRequest.Status.SUBMITTED,
        ReturnRequest.Status.UNDER_REVIEW,
    ]:
        raise ValidationError("This return request cannot be cancelled anymore.")

    old_status = return_request.status

    return_request.status = ReturnRequest.Status.CANCELLED
    return_request.closed_at = timezone.now()
    return_request.save(update_fields=["status", "closed_at", "updated_at"])

    create_return_status_history(
        return_request=return_request,
        old_status=old_status,
        new_status=return_request.status,
        user=user,
        note=note or "Return request cancelled.",
    )

    return return_request


@transaction.atomic
def approve_return_request(*, return_request, user, note="", approved_amount=None):
    return_request = ReturnRequest.objects.select_for_update().get(pk=return_request.pk)

    if not is_admin_user(user):
        raise ValidationError("Only admins can approve return requests.")

    if return_request.status not in [
        ReturnRequest.Status.SUBMITTED,
        ReturnRequest.Status.UNDER_REVIEW,
    ]:
        raise ValidationError("This return request cannot be approved.")

    old_status = return_request.status

    if approved_amount is None:
        approved_amount = return_request.total_requested_amount

    return_request.status = ReturnRequest.Status.APPROVED
    return_request.total_approved_amount = approved_amount
    return_request.reviewed_by = user
    return_request.reviewed_at = timezone.now()
    return_request.save(
        update_fields=[
            "status",
            "total_approved_amount",
            "reviewed_by",
            "reviewed_at",
            "updated_at",
        ]
    )

    for item in return_request.items.all():
        item.status = ReturnItem.ItemStatus.APPROVED
        item.approved_refund_amount = item.requested_refund_amount
        item.save(update_fields=["status", "approved_refund_amount", "updated_at"])

    create_return_status_history(
        return_request=return_request,
        old_status=old_status,
        new_status=return_request.status,
        user=user,
        note=note or "Return request approved.",
    )

    return return_request


@transaction.atomic
def reject_return_request(*, return_request, user, note=""):
    return_request = ReturnRequest.objects.select_for_update().get(pk=return_request.pk)

    if not is_admin_user(user):
        raise ValidationError("Only admins can reject return requests.")

    if return_request.status not in [
        ReturnRequest.Status.SUBMITTED,
        ReturnRequest.Status.UNDER_REVIEW,
    ]:
        raise ValidationError("This return request cannot be rejected.")

    old_status = return_request.status

    return_request.status = ReturnRequest.Status.REJECTED
    return_request.total_approved_amount = Decimal("0")
    return_request.reviewed_by = user
    return_request.reviewed_at = timezone.now()
    return_request.closed_at = timezone.now()
    return_request.save(
        update_fields=[
            "status",
            "total_approved_amount",
            "reviewed_by",
            "reviewed_at",
            "closed_at",
            "updated_at",
        ]
    )

    for item in return_request.items.all():
        item.status = ReturnItem.ItemStatus.REJECTED
        item.approved_refund_amount = Decimal("0")
        item.save(update_fields=["status", "approved_refund_amount", "updated_at"])

    create_return_status_history(
        return_request=return_request,
        old_status=old_status,
        new_status=return_request.status,
        user=user,
        note=note or "Return request rejected.",
    )

    return return_request


@transaction.atomic
def mark_return_item_received(*, return_request, user, note=""):
    return_request = ReturnRequest.objects.select_for_update().get(pk=return_request.pk)

    if not is_admin_user(user):
        raise ValidationError("Only admins can mark return requests as received.")

    if return_request.status not in [
        ReturnRequest.Status.APPROVED,
        ReturnRequest.Status.WAITING_FOR_ITEM,
    ]:
        raise ValidationError("This return request cannot be marked as received.")

    old_status = return_request.status

    return_request.status = ReturnRequest.Status.ITEM_RECEIVED
    return_request.save(update_fields=["status", "updated_at"])

    for item in return_request.items.all():
        item.status = ReturnItem.ItemStatus.RECEIVED
        item.save(update_fields=["status", "updated_at"])

    shipment, created = ReturnShipment.objects.get_or_create(
        return_request=return_request
    )
    shipment.received_at = timezone.now()
    shipment.save(update_fields=["received_at", "updated_at"])

    create_return_status_history(
        return_request=return_request,
        old_status=old_status,
        new_status=return_request.status,
        user=user,
        note=note or "Returned item received.",
    )

    return return_request


@transaction.atomic
def mark_return_refunded(*, return_request, user, note=""):
    return_request = ReturnRequest.objects.select_for_update().get(pk=return_request.pk)

    if not is_admin_user(user):
        raise ValidationError("Only admins can mark return requests as refunded.")

    if return_request.status not in [
        ReturnRequest.Status.ITEM_RECEIVED,
        ReturnRequest.Status.INSPECTING,
        ReturnRequest.Status.REFUND_PENDING,
    ]:
        raise ValidationError("This return request cannot be marked as refunded.")

    old_status = return_request.status

    return_request.status = ReturnRequest.Status.REFUNDED
    return_request.closed_at = timezone.now()
    return_request.save(update_fields=["status", "closed_at", "updated_at"])

    for item in return_request.items.all():
        item.status = ReturnItem.ItemStatus.REFUNDED
        item.save(update_fields=["status", "updated_at"])

    create_return_status_history(
        return_request=return_request,
        old_status=old_status,
        new_status=return_request.status,
        user=user,
        note=note or "Return request refunded.",
    )

    return return_request
