from django.contrib import admin, messages
from django.utils import timezone

from apps.products.models import Product
from apps.reviews.models import ProductReview, ProductReviewVote
from apps.reviews.services import update_product_review_stats


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

    actions = (
        "approve_reviews",
        "reject_reviews",
        "hide_reviews",
    )

    moderator_readonly_fields = (
        "customer",
        "product",
        "order_item",
        "rating",
        "title",
        "comment",
        "is_verified_purchase",
        "approved_by",
        "approved_at",
        "helpful_count",
        "not_helpful_count",
        "created_at",
        "updated_at",
    )

    def get_readonly_fields(self, request, obj=None):
        if request.user.is_superuser:
            return self.readonly_fields

        return self.moderator_readonly_fields

    def has_add_permission(self, request):
        return request.user.is_superuser

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser

    def save_model(self, request, obj, form, change):
        old_product_id = None

        if change and obj.pk:
            old_product_id = (
                ProductReview.objects.filter(pk=obj.pk)
                .values_list("product_id", flat=True)
                .first()
            )

        self._apply_moderation_metadata(request, obj)
        super().save_model(request, obj, form, change)

        product_ids = {obj.product_id}

        if old_product_id:
            product_ids.add(old_product_id)

        self._refresh_product_review_stats(product_ids)

    def _apply_moderation_metadata(self, request, review):
        if review.status == ProductReview.StatusChoices.APPROVED:
            review.approved_by = request.user
            review.approved_at = review.approved_at or timezone.now()
            review.rejected_reason = ""

        elif review.status == ProductReview.StatusChoices.REJECTED:
            review.approved_by = None
            review.approved_at = None

        elif review.status == ProductReview.StatusChoices.PENDING:
            review.approved_by = None
            review.approved_at = None
            review.rejected_reason = ""

    def _refresh_product_review_stats(self, product_ids):
        for product in Product.objects.filter(pk__in=product_ids):
            update_product_review_stats(product)

    def _bulk_update_status(self, request, queryset, status_value, message):
        product_ids = set()
        now = timezone.now()

        for review in queryset.select_related("product"):
            review.status = status_value

            update_fields = [
                "status",
                "updated_at",
            ]

            if status_value == ProductReview.StatusChoices.APPROVED:
                review.approved_by = request.user
                review.approved_at = now
                review.rejected_reason = ""

                update_fields.extend(
                    [
                        "approved_by",
                        "approved_at",
                        "rejected_reason",
                    ]
                )

            elif status_value == ProductReview.StatusChoices.REJECTED:
                review.approved_by = None
                review.approved_at = None

                if not review.rejected_reason:
                    review.rejected_reason = "Rejected from Django admin."

                update_fields.extend(
                    [
                        "approved_by",
                        "approved_at",
                        "rejected_reason",
                    ]
                )

            review.save(update_fields=update_fields)
            product_ids.add(review.product_id)

        self._refresh_product_review_stats(product_ids)

        self.message_user(
            request,
            f"{queryset.count()} review(s) {message}.",
            messages.SUCCESS,
        )

    @admin.action(description="Approve selected reviews")
    def approve_reviews(self, request, queryset):
        self._bulk_update_status(
            request,
            queryset,
            ProductReview.StatusChoices.APPROVED,
            "approved",
        )

    @admin.action(description="Reject selected reviews")
    def reject_reviews(self, request, queryset):
        self._bulk_update_status(
            request,
            queryset,
            ProductReview.StatusChoices.REJECTED,
            "rejected",
        )

    @admin.action(description="Hide selected reviews")
    def hide_reviews(self, request, queryset):
        self._bulk_update_status(
            request,
            queryset,
            ProductReview.StatusChoices.HIDDEN,
            "hidden",
        )


@admin.register(ProductReviewVote)
class ProductReviewVoteAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "review",
        "user",
        "vote",
        "created_at",
    )

    list_filter = (
        "vote",
        "created_at",
    )

    search_fields = (
        "review__title",
        "review__comment",
        "user__phone",
        "user__email",
        "user__full_name",
    )

    readonly_fields = (
        "review",
        "user",
        "vote",
        "created_at",
        "updated_at",
    )

    def has_add_permission(self, request):
        return request.user.is_superuser

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser
