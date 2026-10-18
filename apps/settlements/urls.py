from django.urls import include, path
from apps.settlements.payout_views import SellerPayoutEligibilityView, SettlementReadinessView
from .views import SellerStatementView, SellerStatementCSVView, SettlementAlertsView

urlpatterns = [
    path("integrations/", include("apps.settlements.integration_urls")),
    path("seller/payout-eligibility/", SellerPayoutEligibilityView.as_view(), name="seller-payout-eligibility"),
    path("admin/readiness/", SettlementReadinessView.as_view(), name="settlement-readiness"),
    path("seller/statement/", SellerStatementView.as_view(), name="seller-financial-statement"),
    path("seller/export/", SellerStatementCSVView.as_view(), name="seller-financial-export"),
    path("admin/alerts/", SettlementAlertsView.as_view(), name="settlement-alerts"),
]
