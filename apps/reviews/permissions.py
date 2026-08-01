from rest_framework import permissions

from apps.reviews.models import ProductReview


class IsReviewOwnerOrAdminOrReadOnly(permissions.BasePermission):
    def has_object_permission(self, request, view, obj):
        if request.method in permissions.SAFE_METHODS:
            if obj.status == ProductReview.StatusChoices.APPROVED:
                return True

            if request.user and request.user.is_authenticated:
                return (
                    obj.customer == request.user
                    or request.user.is_staff
                    or request.user.is_superuser
                )

            return False

        if not request.user or not request.user.is_authenticated:
            return False

        return (
            obj.customer == request.user
            or request.user.is_staff
            or request.user.is_superuser
        )
