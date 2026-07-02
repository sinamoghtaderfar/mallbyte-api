from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import F

from apps.discounts.models import Discount, DiscountUsage


def get_discount_by_code(code):
    normalized_code = code.strip().upper()

    try:
        return Discount.objects.get(code=normalized_code)
    except Discount.DoesNotExist as exc:
        raise ValidationError("Invalid discount code.") from exc


def validate_discount_for_cart(code, user, cart):
    discount = get_discount_by_code(code)
    discount_amount = discount.validate_for_cart(user=user, cart=cart)

    return discount, discount_amount


@transaction.atomic
def apply_discount_to_order(discount, user, cart, order):
    """
    Apply a validated discount to an order.

    This function should be called during checkout, before payment.
    """

    locked_discount = Discount.objects.select_for_update().get(pk=discount.pk)
    discount_amount = locked_discount.validate_for_cart(user=user, cart=cart)

    order.discount_amount = discount_amount
    order.save(update_fields=["discount_amount", "total_amount", "updated_at"])

    usage = DiscountUsage.objects.create(
        discount=locked_discount,
        user=user,
        order=order,
        code_snapshot=locked_discount.code,
        discount_amount=discount_amount,
    )

    Discount.objects.filter(pk=locked_discount.pk).update(
        used_count=F("used_count") + 1
    )

    return usage