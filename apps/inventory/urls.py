from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import StockMovementViewSet, StockTransferViewSet, StockViewSet, WarehouseViewSet

router = DefaultRouter()
router.register("warehouses", WarehouseViewSet, basename="warehouse")
router.register("stocks", StockViewSet, basename="stock")
router.register("movements", StockMovementViewSet, basename="stock-movement")
router.register("transfers", StockTransferViewSet, basename="stock-transfer")

urlpatterns = [
    path("", include(router.urls)),
]
