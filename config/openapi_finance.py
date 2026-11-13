"""Schema-only contracts for analytics and read-only financial reporting.

Fields mirror services.py, financial.py, seller_services.py and reconciliation.py.
View replacements inherit the original handlers and only attach OpenAPI metadata.
Money returned explicitly by these services is a decimal string, not a JSON float.
"""
from copy import deepcopy

from drf_spectacular.extensions import OpenApiViewExtension
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema, extend_schema_view, inline_serializer
from rest_framework import serializers

from apps.analytics.financial_views import FinancialAnalyticsQuerySerializer
from apps.analytics.seller_views import SellerAnalyticsQuerySerializer
from apps.analytics.serializers import (
    AnalyticsAlertsQuerySerializer,
    AnalyticsBreakdownQuerySerializer,
    AnalyticsExportQuerySerializer,
    AnalyticsGeneratedReportSerializer,
    DashboardQuerySerializer,
    GenerateAnalyticsReportNowSerializer,
    TimeSeriesQuerySerializer,
)
from apps.settlements.monitoring_views import PageQuery, RunInput
from apps.settlements.payout_views import PayoutEligibilityQuerySerializer
from apps.settlements.reconciliation_views import BalanceQuerySerializer, ReportQuerySerializer


def _object(properties):
    return {"type": "object", "properties": properties, "required": list(properties)}


def _array(items):
    return {"type": "array", "items": items}


TEXT = {"type": "string"}
INTEGER = {"type": "integer"}
BOOLEAN = {"type": "boolean"}
MONEY = {"type": "string", "pattern": r"^-?\d+(?:\.\d+)?$"}
DATETIME = {"type": "string", "format": "date-time"}
NULLABLE_DATETIME = {**DATETIME, "nullable": True}
NULLABLE_ID = {**INTEGER, "nullable": True}
NULLABLE_TEXT = {**TEXT, "nullable": True}
COUNTS = {"type": "object", "additionalProperties": INTEGER}

REPORT_FILTERS = _object({"period": TEXT, "start_at": NULLABLE_DATETIME, "end_at": NULLABLE_DATETIME})
FINANCIAL_FILTERS = _object({
    "period": TEXT, "start_at": NULLABLE_DATETIME,
    "end_exclusive_at": DATETIME, "timezone": TEXT,
})
CASH_VALUES = {
    "captured_amount": MONEY, "refunded_amount": MONEY, "net_cash_flow": MONEY,
    "captured_payments_count": INTEGER, "refunded_payments_count": INTEGER,
}
FINANCIAL_RESPONSE = _object({
    "metric_contract_version": INTEGER,
    "filters": FINANCIAL_FILTERS,
    "currencies": _array(_object({"currency": TEXT, **CASH_VALUES})),
    "data_quality": _object({
        "has_warnings": BOOLEAN, "completed_payments_without_paid_at": INTEGER,
        "refunded_payments_without_refunded_at": INTEGER, "payment_order_amount_mismatches": INTEGER,
        "orders_with_multiple_captured_payments": INTEGER, "scope": TEXT,
    }),
    "accounting_notes": _object({
        "metric_type": TEXT, "capture_date_field": TEXT, "refund_date_field": TEXT,
        "full_refunds_supported": BOOLEAN, "partial_refunds_supported": BOOLEAN,
        "platform_profit_calculated": BOOLEAN, "tax_and_fee_adjustments_included": BOOLEAN,
    }),
})
DAILY_FINANCIAL_RESPONSE = deepcopy(FINANCIAL_RESPONSE)
DAILY_FINANCIAL_RESPONSE["properties"]["series"] = _array(_object({
    "currency": TEXT, "points": _array(_object({"date": {"type": "string", "format": "date"}, **CASH_VALUES})),
}))
DAILY_FINANCIAL_RESPONSE["required"].append("series")
PROVIDER_FINANCIAL_RESPONSE = deepcopy(FINANCIAL_RESPONSE)
PROVIDER_FINANCIAL_RESPONSE["properties"]["by_provider"] = _array(_object({
    "provider": NULLABLE_TEXT, "currency": TEXT, **CASH_VALUES,
}))
PROVIDER_FINANCIAL_RESPONSE["required"].append("by_provider")

TOP_PRODUCT = _object({
    "product_id": NULLABLE_ID, "name": NULLABLE_TEXT, "quantity_sold": INTEGER, "revenue": MONEY,
})
DASHBOARD_RESPONSE = _object({
    "filters": REPORT_FILTERS,
    "sales": _object({"total_revenue": MONEY, "paid_orders_count": INTEGER, "average_order_value": MONEY}),
    "financial": FINANCIAL_RESPONSE,
    "orders": _object({"total_orders": INTEGER, "by_status": COUNTS, "by_payment_status": COUNTS}),
    "payments": _object({
        "total_payments": INTEGER, "successful_amount": MONEY, "refunded_amount": MONEY,
        "failed_payments": INTEGER, "by_status": COUNTS, "by_provider": COUNTS,
    }),
    "products": _object({
        **dict.fromkeys(("total_products", "active_products", "approved_products", "featured_products", "new_products", "total_stock_quantity", "reserved_stock_quantity", "low_stock_items", "out_of_stock_items"), INTEGER),
        "top_products": _array(TOP_PRODUCT),
    }),
    "customers": _object(dict.fromkeys(("total_users", "active_users", "customers", "sellers", "staff_users", "new_users"), INTEGER)),
    "reviews": _object({
        "total_reviews": INTEGER, "average_rating": MONEY, "verified_reviews": INTEGER, "by_status": COUNTS,
    }),
    "support": _object({
        "total_tickets": INTEGER, "unassigned_tickets": INTEGER, "urgent_tickets": INTEGER,
        "high_priority_tickets": INTEGER, "by_status": COUNTS, "by_priority": COUNTS, "by_category": COUNTS,
    }),
    "returns": _object({
        "total_returns": INTEGER, "requested_amount": MONEY, "approved_amount": MONEY,
        "by_status": COUNTS, "by_reason": COUNTS, "by_resolution": COUNTS,
    }),
    "content": _object({
        "pages": _object(dict.fromkeys(("total", "published", "draft", "archived", "featured", "new"), INTEGER)),
        "banners": _object(dict.fromkeys(("total", "published", "draft"), INTEGER)),
        "announcements": _object(dict.fromkeys(("total", "published", "draft"), INTEGER)),
        "faqs": _object(dict.fromkeys(("total", "active", "featured"), INTEGER)),
    }),
    "trends": _object(dict.fromkeys(("revenue_change_percent", "orders_change_percent", "users_change_percent"), MONEY)),
})
TIME_VALUES = {"revenue": MONEY, **dict.fromkeys(("orders_count", "paid_orders_count", "successful_payments_count", "new_users_count"), INTEGER)}
TIMESERIES_RESPONSE = _object({
    "filters": REPORT_FILTERS, "totals": _object(TIME_VALUES),
    "points": _array(_object({"date": {"type": "string", "format": "date"}, **TIME_VALUES})),
    "financial": DAILY_FINANCIAL_RESPONSE,
})
STATUS_BREAKDOWN = _array(_object({"status": TEXT, "label": TEXT, "count": INTEGER}))
BREAKDOWN_RESPONSE = _object({
    "filters": _object({**REPORT_FILTERS["properties"], "limit": INTEGER}),
    "orders_by_status": STATUS_BREAKDOWN, "financial": PROVIDER_FINANCIAL_RESPONSE,
    "payments_by_provider": _array(_object({
        "provider": TEXT, "count": INTEGER, "success_count": INTEGER, "total_amount": MONEY,
    })),
    "revenue_by_category": _array(_object({
        "category_id": NULLABLE_ID, "category_name": TEXT, "revenue": MONEY,
        "quantity_sold": INTEGER, "orders_count": INTEGER,
    })),
    "top_selling_products": _array(_object({
        **TOP_PRODUCT["properties"], "sku": NULLABLE_TEXT, "category_name": TEXT, "orders_count": INTEGER,
    })),
    "reviews_by_status": STATUS_BREAKDOWN,
    "support_by_category": _array(_object({
        "category": TEXT, "label": TEXT, "count": INTEGER, "open_count": INTEGER, "urgent_count": INTEGER,
    })),
    "returns_by_reason": _array(_object({
        "reason": TEXT, "label": TEXT, "count": INTEGER, "requested_amount": MONEY, "approved_amount": MONEY,
    })),
})

ALERT_STOCK = _object({
    "product_id": INTEGER, "product_name": TEXT, "sku": TEXT, "warehouse_id": INTEGER, "warehouse_name": TEXT,
    "quantity": INTEGER, "reserved_quantity": INTEGER, "available_quantity": INTEGER, "low_stock_threshold": INTEGER,
})
ALERT_TICKET = _object({
    "id": INTEGER, "ticket_number": TEXT, "subject": TEXT, "customer_id": INTEGER,
    "priority": TEXT, "status": TEXT, "created_at": DATETIME,
})
ALERTS_RESPONSE = _object({
    "generated_at": DATETIME,
    "cards": _array(_object({"key": TEXT, "label": TEXT, "value": INTEGER, "severity": TEXT})),
    "inventory": _object({"out_of_stock": _array(ALERT_STOCK), "low_stock": _array(ALERT_STOCK)}),
    "orders": _object({"pending_payment_orders": _array(_object({
        "id": INTEGER, "order_number": TEXT, "customer_id": INTEGER, "total_amount": MONEY, "created_at": DATETIME,
    }))}),
    "payments": _object({"failed_payments": _array(_object({
        "id": INTEGER, "payment_number": TEXT, "order_id": INTEGER, "amount": MONEY,
        "provider": TEXT, "failure_reason": TEXT, "created_at": DATETIME,
    }))}),
    "reviews": _object({"pending_reviews": _array(_object({
        "id": INTEGER, "product_id": INTEGER, "product_name": TEXT, "customer_id": INTEGER,
        "rating": INTEGER, "title": TEXT, "created_at": DATETIME,
    }))}),
    "support": _object({"urgent_tickets": _array(ALERT_TICKET), "unassigned_tickets": _array(ALERT_TICKET)}),
    "returns": _object({"pending_returns": _array(_object({
        "id": INTEGER, "request_number": TEXT, "customer_id": INTEGER, "order_id": INTEGER,
        "status": TEXT, "reason": TEXT, "requested_amount": MONEY, "created_at": DATETIME,
    }))}),
    "content": _object(dict.fromkeys(("draft_pages", "draft_banners", "draft_announcements"), INTEGER)),
})

SELLER_VALUES = {**dict.fromkeys(("gross_merchandise_value", "discount_amount", "merchandise_after_discount", "refunded_merchandise_value", "fully_refunded_merchandise_value", "net_merchandise_value"), MONEY), "units_sold": INTEGER, "fully_refunded_units": INTEGER}
SELLER_RESPONSE = _object({
    "metric_contract_version": INTEGER, "scope": _object({"type": TEXT, "seller_id": INTEGER}),
    "filters": FINANCIAL_FILTERS, "currencies": _array(_object({"currency": TEXT, **SELLER_VALUES})),
    "accounting_notes": _object({
        **dict.fromkeys(("metric_type", "recognition", "seller_ownership_source", "legacy_records_note", "refunded_units_note"), TEXT),
        **dict.fromkeys(("discounts_shipping_tax_included", "checkout_discounts_in_net", "partial_refunds_supported", "seller_payout_or_profit"), BOOLEAN),
    }),
})
SELLER_DASHBOARD_RESPONSE = deepcopy(SELLER_RESPONSE)
SELLER_DASHBOARD_RESPONSE["properties"]["catalog"] = _object({"total_products": INTEGER, "active_products": INTEGER})
SELLER_DASHBOARD_RESPONSE["required"].append("catalog")
SELLER_TIMESERIES_RESPONSE = deepcopy(SELLER_RESPONSE)
SELLER_TIMESERIES_RESPONSE["properties"]["series"] = _array(_object({
    "currency": TEXT, "points": _array(_object({"date": {"type": "string", "format": "date"}, **SELLER_VALUES})),
}))
SELLER_TIMESERIES_RESPONSE["required"].append("series")
SELLER_PRODUCTS_RESPONSE = deepcopy(SELLER_RESPONSE)
SELLER_PRODUCTS_RESPONSE["properties"]["products_by_currency"] = _array(_object({
    "currency": TEXT, "products": _array(_object({"product_id": NULLABLE_ID, "name": TEXT, "sku": TEXT, **SELLER_VALUES})),
}))
SELLER_PRODUCTS_RESPONSE["required"].append("products_by_currency")

BALANCE_ROW = _object({"seller_id": INTEGER, "currency": TEXT, "balance": MONEY, "entry_count": INTEGER})
BALANCE_RESPONSE = _object({
    "scope": TEXT, "count": INTEGER, "page": INTEGER, "page_size": INTEGER, "results": _array(BALANCE_ROW),
})
SAMPLE_FINDING = _object({"count": INTEGER, "sample_ids": _array(INTEGER)})
GROUP_FINDING = _object({"count": INTEGER, "sample_allocation_ids": _array(INTEGER)})
NEGATIVE_FINDING = _object({"count": INTEGER, "samples": _array(_object({
    "seller_id": INTEGER, "currency": TEXT, "balance": MONEY,
}))})
RECONCILIATION_RESPONSE = _object({
    "version": INTEGER, "scope": TEXT, "generated_at": DATETIME, "status": TEXT,
    "total_findings": INTEGER, "sample_limit_per_check": INTEGER,
    "findings": _object({
        **dict.fromkeys((
            "captured_items_missing_snapshot", "order_snapshot_total_mismatch", "captured_allocations_missing_sale_credit",
            "sale_credit_snapshot_mismatch", "refund_total_allocation_mismatch", "refund_missing_or_incorrect_seller_debit",
            "payout_missing_or_incorrect_seller_debit", "captured_payment_order_amount_mismatch",
            "legacy_refunded_payment_without_evidence", "return_refunded_without_verified_evidence",
        ), SAMPLE_FINDING),
        "duplicate_sale_credits_per_allocation": GROUP_FINDING, "negative_seller_balance": NEGATIVE_FINDING,
    }),
    "notes": _array(TEXT),
})
STATEMENT_RESPONSE = _object({
    "scope": TEXT,
    "currencies": _array(_object({"currency": TEXT, **dict.fromkeys(("sales", "refunds", "payouts", "balance"), MONEY)})),
    "recent_entries": _array(_object({"kind": TEXT, "currency": TEXT, "amount": MONEY, "occurred_at": DATETIME})),
    "notice": TEXT,
})
SETTLEMENT_ALERTS_RESPONSE = _object({
    **dict.fromkeys(("paid_orders_missing_item_snapshots", "legacy_refunded_payments_without_verified_refund", "returns_marked_refunded_without_verified_payment", "approved_returns_waiting_for_confirmed_refund", "confirmed_refund_events"), INTEGER),
    "seller_balances_below_zero": _array(_object({"seller_id": INTEGER, "currency": TEXT, "balance": MONEY})),
})
READINESS_RESPONSE = _object({
    **dict.fromkeys(("order_items_missing_snapshots", "captured_payments_without_any_seller_sale_ledger", "paid_orders_with_missing_item_allocations"), INTEGER),
    "warning": TEXT,
})
PAYOUT_RESPONSE = _object({
    "currency": TEXT, "ledger_balance": MONEY, "eligible_sale_credits": MONEY, "refund_and_payout_debits": MONEY,
    "withdrawable_amount": MONEY, "hold_days": INTEGER, "evaluated_at": DATETIME, "policy": TEXT,
})
AUDIT_RUN = _object({
    "id": INTEGER, "run_key": TEXT, "source": TEXT, "status": TEXT, "findings_count": INTEGER,
    "created_at": DATETIME, "finished_at": NULLABLE_DATETIME,
})
AUDIT_RUN_DETAIL = _object({
    **AUDIT_RUN["properties"], "summary": {"oneOf": [RECONCILIATION_RESPONSE, {"type": "object", "maxProperties": 0}]}, "error": TEXT,
})
AUDIT_ALERT = _object({
    "code": TEXT, "findings_count": INTEGER, "sample": {"oneOf": [SAMPLE_FINDING, GROUP_FINDING, NEGATIVE_FINDING]},
    "first_seen_at": DATETIME, "last_seen_at": DATETIME, "last_run_id": INTEGER,
})


def _page(items):
    return _object({"count": INTEGER, "page": INTEGER, "page_size": INTEGER, "results": _array(items)})


def _view_extension(name, target, **operations):
    """Register schema-only subclasses without annotating the live view methods."""
    def replacement(self):
        documented = type(f"Documented{self.target_class.__name__}", (self.target_class,), {})
        return extend_schema_view(**{method: extend_schema(**contract) for method, contract in operations.items()})(documented)

    extension = type(name, (OpenApiViewExtension,), {"target_class": target, "view_replacement": replacement})
    globals()[name] = extension


def _get(name, target, response, query=None, **extra):
    _view_extension(name, target, get={"parameters": [query] if query else [], "responses": {200: response}, **extra})


_get("DashboardContract", "apps.analytics.views.DashboardAnalyticsView", DASHBOARD_RESPONSE, DashboardQuerySerializer)
_get("TimeSeriesContract", "apps.analytics.views.AnalyticsTimeSeriesView", TIMESERIES_RESPONSE, TimeSeriesQuerySerializer)
_get("BreakdownContract", "apps.analytics.views.AnalyticsBreakdownView", BREAKDOWN_RESPONSE, AnalyticsBreakdownQuerySerializer)
_get("AnalyticsAlertsContract", "apps.analytics.views.AnalyticsAlertsView", ALERTS_RESPONSE, AnalyticsAlertsQuerySerializer)
_get("FinancialAnalyticsContract", "apps.analytics.financial_views.FinancialAnalyticsView", FINANCIAL_RESPONSE, FinancialAnalyticsQuerySerializer)
_get("SellerDashboardContract", "apps.analytics.seller_views.SellerDashboardView", SELLER_DASHBOARD_RESPONSE, SellerAnalyticsQuerySerializer)
_get("SellerTimeSeriesContract", "apps.analytics.seller_views.SellerTimeSeriesView", SELLER_TIMESERIES_RESPONSE, SellerAnalyticsQuerySerializer)
_get("SellerProductsContract", "apps.analytics.seller_views.SellerProductsView", SELLER_PRODUCTS_RESPONSE, SellerAnalyticsQuerySerializer)

QUEUED_REPORTS = inline_serializer("QueuedAnalyticsReports", fields={
    "detail": serializers.CharField(), "queued_reports": AnalyticsGeneratedReportSerializer(many=True),
})
_view_extension("GenerateAnalyticsReportContract", "apps.analytics.views.GenerateAnalyticsReportNowView",
                create={"request": GenerateAnalyticsReportNowSerializer, "responses": {202: QUEUED_REPORTS}})
_view_extension("AnalyticsScheduleRunContract", "apps.analytics.views.AnalyticsReportScheduleViewSet",
                run_now={"request": None, "responses": {202: QUEUED_REPORTS}})
_view_extension("AnalyticsDownloadContract", "apps.analytics.views.AnalyticsGeneratedReportViewSet",
                download={"responses": {(200, "text/csv"): OpenApiTypes.BINARY}})

_get("BalanceContract", "apps.settlements.reconciliation_views.BalanceView", BALANCE_RESPONSE, BalanceQuerySerializer)
_get("ReconciliationContract", "apps.settlements.reconciliation_views.ReconciliationView", RECONCILIATION_RESPONSE, ReportQuerySerializer)
_get("SellerStatementContract", "apps.settlements.views.SellerStatementView", STATEMENT_RESPONSE)
_get("SettlementAlertsContract", "apps.settlements.views.SettlementAlertsView", SETTLEMENT_ALERTS_RESPONSE)
_get("ReadinessContract", "apps.settlements.payout_views.SettlementReadinessView", READINESS_RESPONSE)
_get("PayoutEligibilityContract", "apps.settlements.payout_views.SellerPayoutEligibilityView", PAYOUT_RESPONSE, PayoutEligibilityQuerySerializer)
_get("FinancialAuditRunsContract", "apps.settlements.monitoring_views.FinancialAuditRunsView", _page(AUDIT_RUN), PageQuery,
     operation_id="api_settlements_admin_monitoring_runs_list")
_get("FinancialAuditRunContract", "apps.settlements.monitoring_views.FinancialAuditRunDetailView", AUDIT_RUN_DETAIL)
_get("FinancialAuditAlertsContract", "apps.settlements.monitoring_views.FinancialAuditAlertsView", _page(AUDIT_ALERT), PageQuery)
_view_extension("FinancialAuditRunNowContract", "apps.settlements.monitoring_views.FinancialAuditRunNowView", post={
    "request": RunInput,
    "responses": {
        202: _object({"queued": BOOLEAN, "run_key": TEXT, "task_id": TEXT, "status": TEXT}),
        503: _object({"detail": TEXT}),
    },
})

for _name, _target, _query in (
    ("AnalyticsExportContract", "apps.analytics.views.AnalyticsExportView", AnalyticsExportQuerySerializer),
    ("BalanceExportContract", "apps.settlements.reconciliation_views.BalanceExportView", BalanceQuerySerializer),
    ("ReconciliationExportContract", "apps.settlements.reconciliation_views.ReconciliationExportView", ReportQuerySerializer),
    ("SellerStatementExportContract", "apps.settlements.views.SellerStatementCSVView", None),
):
    _view_extension(_name, _target, get={
        "parameters": [_query] if _query else [], "responses": {(200, "text/csv"): OpenApiTypes.BINARY},
    })
