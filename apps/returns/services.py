from decimal import Decimal, ROUND_DOWN

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from apps.notifications.services import create_notification
from apps.notifications.templates import render_notification_template
from apps.orders.models import Order, OrderItem, SellerOrderFulfillment
from apps.returns.models import (
    ReturnItem,
    ReturnRequest,
    ReturnShipment,
    ReturnStatusHistory,
)


def is_admin_user(user):
    return getattr(user, "is_staff", False) or getattr(user, "is_superuser", False)


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


def create_return_notification(
    *,
    return_request,
    template_key,
    metadata=None,
    **context,
):
    if metadata is None:
        metadata = {}

    if not return_request.customer:
        return None

    template_data = render_notification_template(
        template_key,
        **context,
    )

    return create_notification(
        user=return_request.customer,
        title=template_data["title"],
        message=template_data["message"],
        notification_type=template_data["notification_type"],
        priority=template_data["priority"],
        related_object_type="return_request",
        related_object_id=return_request.pk,
        action_url=f"/returns/{return_request.pk}/",
        metadata={
            "return_request_id": return_request.pk,
            "request_number": return_request.request_number,
            "status": return_request.status,
            "order_id": return_request.order_id,
            "order_number": return_request.order.order_number,
            "template_key": template_key,
            **metadata,
        },
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

    if order.payment_status != Order.PaymentStatusChoices.PAID or order.status in {
        Order.StatusChoices.PENDING_PAYMENT,
        Order.StatusChoices.CANCELLED,
        Order.StatusChoices.REFUNDED,
    }:
        raise ValidationError("Only paid, active orders with delivered items can be returned.")

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

        seller_status = (
            SellerOrderFulfillment.objects.filter(
                order_id=order.id, seller_id=order_item.product.seller_id
            )
            .values_list("status", flat=True)
            .first()
        )
        if seller_status is not None:
            if seller_status != Order.StatusChoices.DELIVERED:
                raise ValidationError(
                    "Only items delivered by their seller can be returned."
                )
        elif order.status != Order.StatusChoices.DELIVERED:
            # Legacy orders without seller fulfillment records retain their
            # whole-order delivery rule. Never infer delivery from payment.
            raise ValidationError("Only delivered items can be returned.")

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

    create_return_notification(
        return_request=return_request,
        template_key="return_submitted",
        order_id=return_request.order.order_number,
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

    create_return_notification(
        return_request=return_request,
        template_key="return_cancelled",
        order_id=return_request.order.order_number,
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

    return_items = list(return_request.items.select_for_update().order_by("pk"))
    if not return_items:
        raise ValidationError("A return request must have at least one item.")
    requested_total = sum(
        (item.requested_refund_amount for item in return_items), Decimal("0.00")
    )
    if requested_total != return_request.total_requested_amount:
        raise ValidationError("Return item amounts do not match the request total.")
    if approved_amount is None:
        approved_amount = requested_total
    else:
        approved_amount = Decimal(str(approved_amount))
    if approved_amount < 0 or approved_amount > requested_total:
        raise ValidationError("Approved amount must be between zero and requested total.")
    approved_amount = approved_amount.quantize(Decimal("0.01"))

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

    # Allocate a partial approval proportionally to item amounts. Remainder
    # goes to the last item so seller-level totals equal the global total.
    allocated = Decimal("0.00")
    funded = [item.pk for item in return_items if item.requested_refund_amount > 0]
    last_funded_id = funded[-1] if funded else None
    for item in return_items:
        if item.requested_refund_amount == 0 or requested_total == 0:
            item_amount = Decimal("0.00")
        elif item.pk == last_funded_id:
            item_amount = approved_amount - allocated
        else:
            item_amount = (
                approved_amount * item.requested_refund_amount / requested_total
            ).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
        allocated += item_amount
        item.status = ReturnItem.ItemStatus.APPROVED
        item.approved_refund_amount = item_amount
        item.save(update_fields=["status", "approved_refund_amount", "updated_at"])

    create_return_status_history(
        return_request=return_request,
        old_status=old_status,
        new_status=return_request.status,
        user=user,
        note=note or "Return request approved.",
    )

    create_return_notification(
        return_request=return_request,
        template_key="return_approved",
        order_id=return_request.order.order_number,
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

    create_return_notification(
        return_request=return_request,
        template_key="return_rejected",
        order_id=return_request.order.order_number,
        metadata={
            "note": note or "Return request rejected.",
        },
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

    shipment, _created = ReturnShipment.objects.get_or_create(
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

    create_return_notification(
        return_request=return_request,
        template_key="return_received",
        order_id=return_request.order.order_number,
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

    create_return_notification(
        return_request=return_request,
        template_key="return_refunded",
        order_id=return_request.order.order_number,
    )

    return return_request
