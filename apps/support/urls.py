from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.support.views import SupportTagViewSet, SupportTicketViewSet

router = DefaultRouter()
router.register("tickets", SupportTicketViewSet, basename="support-ticket")
router.register("tags", SupportTagViewSet, basename="support-tag")

urlpatterns = [
    path("", include(router.urls)),
]