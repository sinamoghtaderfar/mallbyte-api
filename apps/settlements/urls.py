from django.urls import include, path

from apps.settlements.demo_gateway import (
    DemoCaptureView,
    DemoFailView,
    DemoPayoutView,
    DemoRefundView,
)
from apps.settlements.monitoring_views import (
    FinancialAuditAlertsView,
    FinancialAuditRunDetailView,
    FinancialAuditRunNowView,
    FinancialAuditRunsView,
)
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
    path("integrations/", include("apps.settlements.integration_urls")),
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
    path("admin/alerts/", SettlementAlertsView.as_view(), name="settlement-alerts"),
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
    path("admin/balances/", BalanceView.as_view(), name="settlement-admin-balances"),
    path(
        "admin/balances/export/",
        BalanceExportView.as_view(),
        name="settlement-admin-balances-export",
    ),
    # Stage 7: persistent automated reconciliation and deduplicated alerts.
    path(
        "admin/monitoring/runs/",
        FinancialAuditRunsView.as_view(),
        name="settlement-monitoring-runs",
    ),
    path(
        "admin/monitoring/runs/<int:pk>/",
        FinancialAuditRunDetailView.as_view(),
        name="settlement-monitoring-run-detail",
    ),
    path(
        "admin/monitoring/alerts/",
        FinancialAuditAlertsView.as_view(),
        name="settlement-monitoring-alerts",
    ),
    path(
        "admin/monitoring/run-now/",
        FinancialAuditRunNowView.as_view(),
        name="settlement-monitoring-run-now",
    ),
    # These cannot execute when DEBUG is False, regardless of feature flags.
    path("demo/capture/", DemoCaptureView.as_view(), name="settlement-demo-capture"),
    path("demo/fail/", DemoFailView.as_view(), name="settlement-demo-fail"),
    path("demo/refund/", DemoRefundView.as_view(), name="settlement-demo-refund"),
    path("demo/payout/", DemoPayoutView.as_view(), name="settlement-demo-payout"),
]
