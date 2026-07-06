from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.returns.views import ReturnRequestViewSet

router = DefaultRouter()
router.register("requests", ReturnRequestViewSet, basename="return-request")


urlpatterns = [
    path("", include(router.urls)),
]
