from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.orders.views import CartViewSet, OrderViewSet


router = DefaultRouter()

router.register(r"cart", CartViewSet, basename="cart")
router.register(r"orders", OrderViewSet, basename="order")


urlpatterns = [
    path("", include(router.urls)),
]