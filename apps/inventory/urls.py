from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.inventory.views import (
    StockMovementViewSet,
    StockTransferViewSet,
    StockViewSet,
    WarehouseViewSet,
)

router = DefaultRouter()

router.register(r"warehouses", WarehouseViewSet, basename="warehouse")
router.register(r"stocks", StockViewSet, basename="stock")
router.register(r"stock-movements", StockMovementViewSet, basename="stock-movement")
router.register(r"stock-transfers", StockTransferViewSet, basename="stock-transfer")

urlpatterns = [
    path("", include(router.urls)),
]