from django.urls import path

from apps.settlements.gateway_bridge import (
    CaptureConfirmationView,
    RefundConfirmationView,
    PayoutConfirmationView,
)

urlpatterns = [
    path("capture-confirmed/", CaptureConfirmationView.as_view(), name="settlement-capture-confirmed"),
    path("refund-confirmed/", RefundConfirmationView.as_view(), name="settlement-refund-confirmed"),
    path("payout-confirmed/", PayoutConfirmationView.as_view(), name="settlement-payout-confirmed"),
]
