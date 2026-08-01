from rest_framework import serializers

from apps.orders.models import Order, OrderItem
from apps.reviews.models import ProductReview


class ProductReviewSerializer(serializers.ModelSerializer):
    customer_display = serializers.CharField(
        source="customer.full_name", read_only=True
    )
    product_name = serializers.CharField(source="product.name", read_only=True)
    approved_by_display = serializers.CharField(
        source="approved_by.full_name",
        read_only=True,
    )

    class Meta:
        model = ProductReview
        fields = [
            "id",
            "customer",
            "customer_display",
            "product",
            "product_name",
            "order_item",
            "rating",
            "title",
            "comment",
            "status",
            "is_verified_purchase",
            "approved_by",
            "approved_by_display",
            "approved_at",
            "rejected_reason",
            "helpful_count",
            "not_helpful_count",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "customer",
            "customer_display",
            "product_name",
            "order_item",
            "status",
            "is_verified_purchase",
            "approved_by",
            "approved_by_display",
            "approved_at",
            "rejected_reason",
            "helpful_count",
            "not_helpful_count",
            "created_at",
            "updated_at",
        ]

    def validate(self, attrs):
        request = self.context.get("request")

        if request is None or request.user.is_anonymous:
            raise serializers.ValidationError(
                "Authentication is required to create a review."
            )

        product = attrs.get("product")

        if product is None:
            return attrs

        if ProductReview.objects.filter(
            customer=request.user,
            product=product,
        ).exists():
            raise serializers.ValidationError("You have already reviewed this product.")

        order_item = (
            OrderItem.objects.filter(
                order__user=request.user,
                order__status=Order.StatusChoices.DELIVERED,
                product=product,
            )
            .select_related("order", "product")
            .order_by("-created_at")
            .first()
        )

        if order_item is None:
            raise serializers.ValidationError(
                "You can only review products from delivered orders."
            )

        attrs["order_item"] = order_item
        attrs["is_verified_purchase"] = True

        return attrs

    def create(self, validated_data):
        request = self.context["request"]

        return ProductReview.objects.create(
            customer=request.user,
            status=ProductReview.StatusChoices.PENDING,
            **validated_data,
        )


class ProductReviewModerationSerializer(serializers.Serializer):
    reason = serializers.CharField(required=False, allow_blank=True)
