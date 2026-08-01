from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.reviews.views import ProductReviewViewSet

router = DefaultRouter()
router.register("product-reviews", ProductReviewViewSet, basename="product-review")

urlpatterns = [
    path("", include(router.urls)),
]
