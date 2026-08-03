from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q

from apps.orders.models import OrderItem
from apps.products.models import Product


class ProductReview(models.Model):
    class StatusChoices(models.TextChoices):
        PENDING = "pending", "Pending"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"
        HIDDEN = "hidden", "Hidden"

    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="product_reviews",
    )
    # TODO: Consider adding a unique constraint to ensure that a customer can only leave one review per product. This can be done by adding a unique_together constraint on the customer and product fields.
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name="product_reviews",
    )

    order_item = models.ForeignKey(
        OrderItem,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviews",
    )

    rating = models.PositiveSmallIntegerField(
        validators=[
            MinValueValidator(1),
            MaxValueValidator(5),
        ]
    )

    title = models.CharField(max_length=255, blank=True)
    comment = models.TextField()

    status = models.CharField(
        max_length=20,
        choices=StatusChoices.choices,
        default=StatusChoices.PENDING,
        db_index=True,
    )

    is_verified_purchase = models.BooleanField(default=False, db_index=True)

    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="approved_product_reviews",
    )

    approved_at = models.DateTimeField(null=True, blank=True)
    rejected_reason = models.TextField(blank=True)

    helpful_count = models.PositiveIntegerField(default=0)
    not_helpful_count = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Product Review"
        verbose_name_plural = "Product Reviews"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["product", "status", "-created_at"]),
            models.Index(fields=["customer", "-created_at"]),
            models.Index(fields=["rating"]),
            models.Index(fields=["is_verified_purchase"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["customer", "product"],
                name="unique_review_per_customer_product",
            ),
            models.CheckConstraint(
                condition=Q(rating__gte=1) & Q(rating__lte=5),
                name="review_rating_between_1_and_5",
            ),
        ]

    def __str__(self):
        return f"{self.product.name} - {self.rating}/5 by {self.customer}"


class ProductReviewVote(models.Model):
    class VoteChoices(models.TextChoices):
        HELPFUL = "helpful", "Helpful"
        NOT_HELPFUL = "not_helpful", "Not Helpful"

    review = models.ForeignKey(
        ProductReview,
        on_delete=models.CASCADE,
        related_name="votes",
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="product_review_votes",
    )

    vote = models.CharField(
        max_length=20,
        choices=VoteChoices.choices,
        db_index=True,
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Product Review Vote"
        verbose_name_plural = "Product Review Votes"
        unique_together = ["review", "user"]
        indexes = [
            models.Index(fields=["review", "vote"]),
            models.Index(fields=["user", "-created_at"]),
        ]

    def __str__(self):
        return f"{self.user} voted {self.vote} on review {self.review_id}"