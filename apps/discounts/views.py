from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.discounts.serializers import (
    DiscountValidateSerializer,
    build_discount_validation_response,
)
from apps.orders.models import Cart


class ValidateDiscountView(APIView):
    """
    Validate a discount code against the authenticated user's cart.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = DiscountValidateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            cart = Cart.objects.prefetch_related(
                "items",
                "items__product",
                "items__product__category",
            ).get(user=request.user)
        except Cart.DoesNotExist:
            return Response(
                {"detail": "Cart not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        if not cart.items.exists():
            return Response(
                {"detail": "Cart is empty."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            result = build_discount_validation_response(
                code=serializer.validated_data["code"],
                user=request.user,
                cart=cart,
            )
        except DjangoValidationError as exc:
            message = exc.messages[0] if hasattr(exc, "messages") else str(exc)

            return Response(
                {"detail": message},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(result, status=status.HTTP_200_OK)