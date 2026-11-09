from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.returns.customer_workflows import CustomerReturnShipmentView, ReturnEvidenceUploadView
from apps.returns.inventory_restoration import ReturnInventoryRestorationView
from apps.returns.private_media_views import ReturnAttachmentDownloadView, ReturnShippingLabelDownloadView
from apps.returns.views import ReturnRequestViewSet

router = DefaultRouter()
router.register("requests", ReturnRequestViewSet, basename="return-request")


urlpatterns = [
    path("requests/<int:pk>/attachments/", ReturnEvidenceUploadView.as_view(), name="return-evidence-upload"),
    path("requests/<int:pk>/shipment/", CustomerReturnShipmentView.as_view(), name="return-customer-shipment"),
    path("requests/<int:pk>/items/<int:item_pk>/restock/", ReturnInventoryRestorationView.as_view(), name="return-item-restock"),
    path("attachments/<int:pk>/download/", ReturnAttachmentDownloadView.as_view(), name="return-attachment-download"),
    path("shipments/<int:pk>/label/download/", ReturnShippingLabelDownloadView.as_view(), name="return-shipping-label-download"),
    path("", include(router.urls)),
]
