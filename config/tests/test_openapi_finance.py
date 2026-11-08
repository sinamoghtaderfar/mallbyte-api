"""Validate documented report shapes against actual rendered API responses."""
from copy import deepcopy

from django.utils import timezone
from jsonschema import Draft4Validator
from rest_framework.test import APITestCase

from apps.accounts.models import Seller, User
from apps.orders.models import Order
from apps.payments.models import Payment
from apps.settlements.models import SellerLedgerEntry
from apps.settlements.monitoring_models import FinancialAuditAlert, FinancialAuditRun
from config import openapi_finance as contracts


def json_schema(schema):
    """OpenAPI 3.0 nullable is expressed as JSON Schema's null alternative."""
    if isinstance(schema, list):
        return [json_schema(item) for item in schema]
    if not isinstance(schema, dict):
        return schema
    value = {key: json_schema(item) for key, item in schema.items() if key != "nullable"}
    return {"anyOf": [value, {"type": "null"}]} if schema.get("nullable") else value


class FinancialOpenAPIContractTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_superuser(
            email="schema-financial@example.com", password="StrongPass123!", is_seller=True,
        )
        Seller.objects.create(user=self.user, store_name="Schema store", status=Seller.StatusChoices.APPROVED)
        self.client.force_authenticate(self.user)
        self.order = Order.objects.create(user=self.user, subtotal=100, payment_status="paid", status="paid")
        Payment.objects.create(
            order=self.order, user=self.user, amount=100, currency="IRR", status="success", paid_at=timezone.now(),
        )

    def assert_contract(self, url, schema):
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200, response.data)
        Draft4Validator(json_schema(deepcopy(schema))).validate(response.json())
        return response

    def test_platform_analytics_responses_match_their_typed_contracts(self):
        for endpoint, schema in (
            ("dashboard", contracts.DASHBOARD_RESPONSE),
            ("timeseries", contracts.TIMESERIES_RESPONSE),
            ("breakdown", contracts.BREAKDOWN_RESPONSE),
            ("alerts", contracts.ALERTS_RESPONSE),
            ("financial", contracts.FINANCIAL_RESPONSE),
        ):
            with self.subTest(endpoint=endpoint):
                self.assert_contract(f"/api/analytics/{endpoint}/?period=today", schema)

    def test_seller_analytics_responses_match_all_three_dimensions(self):
        for endpoint, schema in (
            ("dashboard", contracts.SELLER_DASHBOARD_RESPONSE),
            ("timeseries", contracts.SELLER_TIMESERIES_RESPONSE),
            ("products", contracts.SELLER_PRODUCTS_RESPONSE),
        ):
            with self.subTest(endpoint=endpoint):
                self.assert_contract(f"/api/analytics/seller/{endpoint}/?period=today", schema)

    def test_statements_balances_payout_readiness_and_reconciliation_match_contracts(self):
        for kind, amount in (("sale", "90.00"), ("payout", "-100.00")):
            SellerLedgerEntry.objects.create(
                seller=self.user, currency="IRR", kind=kind, amount=amount,
                source_key=f"schema:{kind}", occurred_at=timezone.now(),
            )
        for endpoint, schema in (
            ("seller/statement/", contracts.STATEMENT_RESPONSE),
            ("admin/balances/", contracts.BALANCE_RESPONSE),
            ("admin/reconciliation/", contracts.RECONCILIATION_RESPONSE),
            ("admin/readiness/", contracts.READINESS_RESPONSE),
            ("admin/alerts/", contracts.SETTLEMENT_ALERTS_RESPONSE),
            ("seller/payout-eligibility/?currency=IRR", contracts.PAYOUT_RESPONSE),
        ):
            with self.subTest(endpoint=endpoint):
                self.assert_contract(f"/api/settlements/{endpoint}", schema)

    def test_running_audit_detail_and_paged_alerts_match_contracts(self):
        run = FinancialAuditRun.objects.create(run_key="manual:schema", source="manual")
        FinancialAuditAlert.objects.create(
            code="schema-finding", findings_count=1, sample={"count": 1, "sample_ids": [self.order.pk]},
            first_seen_at=timezone.now(), last_seen_at=timezone.now(), last_run=run,
        )
        self.assert_contract("/api/settlements/admin/monitoring/runs/", contracts._page(contracts.AUDIT_RUN))
        self.assert_contract(f"/api/settlements/admin/monitoring/runs/{run.pk}/", contracts.AUDIT_RUN_DETAIL)
        self.assert_contract("/api/settlements/admin/monitoring/alerts/", contracts._page(contracts.AUDIT_ALERT))
