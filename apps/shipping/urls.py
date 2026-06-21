from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.shipping.views import ShipmentViewSet


router = DefaultRouter()

router.register(r"shipments", ShipmentViewSet, basename="shipment")


urlpatterns = [
    path("", include(router.urls)),
]