from django.contrib import admin

from apps.reviews.models import ProductReview


@admin.register(ProductReview)
class ProductReviewAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "product",
        "customer",
        "rating",
        "status",
        "is_verified_purchase",
        "helpful_count",
        "not_helpful_count",
        "created_at",
    )

    list_filter = (
        "status",
        "rating",
        "is_verified_purchase",
        "created_at",
    )

    search_fields = (
        "product__name",
        "customer__phone",
        "customer__email",
        "customer__full_name",
        "title",
        "comment",
    )

    readonly_fields = (
        "created_at",
        "updated_at",
        "approved_at",
    )
