from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.returns.private_media_views import ReturnAttachmentDownloadView, ReturnShippingLabelDownloadView
from apps.returns.views import ReturnRequestViewSet

router = DefaultRouter()
router.register("requests", ReturnRequestViewSet, basename="return-request")


urlpatterns = [
    path("attachments/<int:pk>/download/", ReturnAttachmentDownloadView.as_view(), name="return-attachment-download"),
    path("shipments/<int:pk>/label/download/", ReturnShippingLabelDownloadView.as_view(), name="return-shipping-label-download"),
    path("", include(router.urls)),
]
