from rest_framework import serializers

from apps.discounts.services import validate_discount_for_cart


class DiscountValidateSerializer(serializers.Serializer):
    code = serializers.CharField(max_length=50)

    def validate_code(self, value):
        value = value.strip().upper()

        if not value:
            raise serializers.ValidationError("Discount code is required.")

        return value


class DiscountValidationResultSerializer(serializers.Serializer):
    code = serializers.CharField()
    title = serializers.CharField()
    discount_type = serializers.CharField()
    discount_amount = serializers.DecimalField(max_digits=12, decimal_places=0)
    cart_subtotal = serializers.DecimalField(max_digits=12, decimal_places=0)
    total_after_discount = serializers.DecimalField(max_digits=12, decimal_places=0)


def build_discount_validation_response(code, user, cart):
    discount, discount_amount = validate_discount_for_cart(
        code=code,
        user=user,
        cart=cart,
    )

    total_after_discount = cart.subtotal - discount_amount

    if total_after_discount < 0:
        total_after_discount = 0

    return {
        "code": discount.code,
        "title": discount.title,
        "discount_type": discount.discount_type,
        "discount_amount": discount_amount,
        "cart_subtotal": cart.subtotal,
        "total_after_discount": total_after_discount,
    }