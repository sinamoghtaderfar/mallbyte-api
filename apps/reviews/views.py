from django.db.models import Q
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import (
    IsAdminUser,
    IsAuthenticated,
    IsAuthenticatedOrReadOnly,
)
from rest_framework.response import Response

from apps.reviews.models import ProductReview
from apps.reviews.permissions import IsReviewOwnerOrAdminOrReadOnly
from apps.reviews.serializers import (
    ProductReviewModerationSerializer,
    ProductReviewSerializer,
)
from apps.reviews.services import set_review_vote, update_product_review_stats
from apps.reviews.services import update_product_review_stats
from apps.reviews.notifications import create_review_notification
from apps.reviews.models import ProductReview, ProductReviewVote

class ProductReviewViewSet(viewsets.ModelViewSet):
    serializer_class = ProductReviewSerializer
    permission_classes = [
        IsAuthenticatedOrReadOnly,
        IsReviewOwnerOrAdminOrReadOnly,
    ]
    http_method_names = ["get", "post", "put", "patch", "delete", "head", "options"]

    def get_queryset(self):
        queryset = ProductReview.objects.select_related(
            "customer",
            "product",
            "order_item",
            "approved_by",
        )

        user = self.request.user

        if user.is_authenticated and (user.is_staff or user.is_superuser):
            pass
        elif user.is_authenticated:
            queryset = queryset.filter(
                Q(status=ProductReview.StatusChoices.APPROVED) | Q(customer=user)
            )
        else:
            queryset = queryset.filter(
                status=ProductReview.StatusChoices.APPROVED,
            )

        product_id = self.request.query_params.get("product")
        status_filter = self.request.query_params.get("status")
        rating = self.request.query_params.get("rating")
        verified = self.request.query_params.get("is_verified_purchase")

        if product_id:
            queryset = queryset.filter(product_id=product_id)

        if status_filter:
            queryset = queryset.filter(status=status_filter)

        if rating:
            queryset = queryset.filter(rating=rating)

        if verified is not None:
            if verified.lower() == "true":
                queryset = queryset.filter(is_verified_purchase=True)
            elif verified.lower() == "false":
                queryset = queryset.filter(is_verified_purchase=False)

        return queryset.order_by("-created_at")

    @action(
        detail=True,
        methods=["post"],
        url_path="approve",
        permission_classes=[IsAdminUser],
    )
    def approve(self, request, pk=None):
        review = self.get_object()

        review.status = ProductReview.StatusChoices.APPROVED
        review.approved_by = request.user
        review.approved_at = timezone.now()
        review.rejected_reason = ""
        review.save(
            update_fields=[
                "status",
                "approved_by",
                "approved_at",
                "rejected_reason",
                "updated_at",
            ]
        )

        update_product_review_stats(review.product)
        
        create_review_notification(
            review=review,
            template_key="review_approved",
            product_name=review.product.name,
        )

        serializer = self.get_serializer(review)

        return Response(serializer.data, status=status.HTTP_200_OK)

    @action(
        detail=True,
        methods=["post"],
        url_path="reject",
        permission_classes=[IsAdminUser],
    )
    def reject(self, request, pk=None):
        review = self.get_object()

        serializer = ProductReviewModerationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        review.status = ProductReview.StatusChoices.REJECTED
        review.approved_by = None
        review.approved_at = None
        review.rejected_reason = serializer.validated_data.get("reason", "")
        review.save(
            update_fields=[
                "status",
                "approved_by",
                "approved_at",
                "rejected_reason",
                "updated_at",
            ]
        )
        update_product_review_stats(review.product)
        
        create_review_notification(
            review=review,
            template_key="review_rejected",
            product_name=review.product.name,
            reason=review.rejected_reason or "No reason provided.",
        )

        response_serializer = self.get_serializer(review)

        return Response(response_serializer.data, status=status.HTTP_200_OK)

    @action(
        detail=True,
        methods=["post"],
        url_path="hide",
        permission_classes=[IsAdminUser],
    )
    @action(
        detail=True,
        methods=["post"],
        url_path="hide",
        permission_classes=[IsAdminUser],
    )
    def hide(self, request, pk=None):
        review = self.get_object()

        review.status = ProductReview.StatusChoices.HIDDEN
        review.save(update_fields=["status", "updated_at"])

        update_product_review_stats(review.product)
        
        create_review_notification(
            review=review,
            template_key="review_hidden",
            product_name=review.product.name,
        )

        serializer = self.get_serializer(review)

        return Response(serializer.data, status=status.HTTP_200_OK)

    @action(
        detail=True,
        methods=["post"],
        url_path="helpful",
        permission_classes=[IsAuthenticated],
    )
    def helpful(self, request, pk=None):
        review = self.get_object()

        try:
            _, updated_review = set_review_vote(
                review=review,
                user=request.user,
                vote=ProductReviewVote.VoteChoices.HELPFUL,
            )
        except ValueError as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = self.get_serializer(updated_review)

        return Response(serializer.data, status=status.HTTP_200_OK)

    @action(
        detail=True,
        methods=["post"],
        url_path="not-helpful",
        permission_classes=[IsAuthenticated],
    )
    def not_helpful(self, request, pk=None):
        review = self.get_object()

        try:
            _, updated_review = set_review_vote(
                review=review,
                user=request.user,
                vote=ProductReviewVote.VoteChoices.NOT_HELPFUL,
            )
        except ValueError as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = self.get_serializer(updated_review)

        return Response(serializer.data, status=status.HTTP_200_OK)

    def perform_destroy(self, instance):
        product = instance.product
        instance.delete()
        update_product_review_stats(product)
        
        
    def perform_destroy(self, instance):
        product = instance.product
        instance.delete()
        update_product_review_stats(product)
