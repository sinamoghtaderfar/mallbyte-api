from rest_framework import permissions

from apps.rbac.utils import has_permission
from apps.reviews.models import ProductReview


def can_moderate_reviews(user):
    return bool(user and user.is_authenticated and user.is_active and not user.is_deleted and (
        user.has_perm("reviews.change_productreview") or has_permission(user, "moderate_reviews")
    ))


class CanModerateReviews(permissions.BasePermission):
    def has_permission(self, request, view):
        return can_moderate_reviews(request.user)


class IsReviewOwnerOrAdminOrReadOnly(permissions.BasePermission):
    def has_object_permission(self, request, view, obj):
        if request.method in permissions.SAFE_METHODS:
            if obj.status == ProductReview.StatusChoices.APPROVED:
                return True

            if request.user and request.user.is_authenticated:
                return (
                    obj.customer == request.user
                    or can_moderate_reviews(request.user)
                )

            return False

        if not request.user or not request.user.is_authenticated:
            return False

        return (
            obj.customer == request.user
            or can_moderate_reviews(request.user)
        )
