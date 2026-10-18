from django.urls import include, path

from apps.settlements.payout_views import (
    SellerPayoutEligibilityView,
    SettlementReadinessView,
)
from apps.settlements.reconciliation_views import (
    BalanceExportView,
    BalanceView,
    ReconciliationExportView,
    ReconciliationView,
)
from apps.settlements.views import (
    SellerStatementCSVView,
    SellerStatementView,
    SettlementAlertsView,
)

urlpatterns = [
    path(
        "integrations/",
        include("apps.settlements.integration_urls"),
    ),
    path(
        "seller/payout-eligibility/",
        SellerPayoutEligibilityView.as_view(),
        name="seller-payout-eligibility",
    ),
    path(
        "admin/readiness/",
        SettlementReadinessView.as_view(),
        name="settlement-readiness",
    ),
    path(
        "seller/statement/",
        SellerStatementView.as_view(),
        name="seller-financial-statement",
    ),
    path(
        "seller/export/",
        SellerStatementCSVView.as_view(),
        name="seller-financial-export",
    ),
    path(
        "admin/alerts/",
        SettlementAlertsView.as_view(),
        name="settlement-alerts",
    ),
    # Stage 6: Financial reconciliation.
    path(
        "admin/reconciliation/",
        ReconciliationView.as_view(),
        name="settlement-reconciliation",
    ),
    path(
        "admin/reconciliation/export/",
        ReconciliationExportView.as_view(),
        name="settlement-reconciliation-export",
    ),
    path(
        "admin/balances/",
        BalanceView.as_view(),
        name="settlement-admin-balances",
    ),
    path(
        "admin/balances/export/",
        BalanceExportView.as_view(),
        name="settlement-admin-balances-export",
    ),
]
