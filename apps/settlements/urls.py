from django.urls import path
from .views import SellerStatementView, SellerStatementCSVView, SettlementAlertsView

urlpatterns = [
    path("seller/statement/", SellerStatementView.as_view(), name="seller-financial-statement"),
    path("seller/export/", SellerStatementCSVView.as_view(), name="seller-financial-export"),
    path("admin/alerts/", SettlementAlertsView.as_view(), name="settlement-alerts"),
]
