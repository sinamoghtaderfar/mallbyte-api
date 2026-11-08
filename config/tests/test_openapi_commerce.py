"""Documented custom responses preserve actual wire shapes and URL callbacks."""
from importlib.util import find_spec
from unittest import skipUnless

from django.test import SimpleTestCase
from django.urls import resolve
from drf_spectacular.generators import SchemaGenerator

from apps.orders.views import CartViewSet
from apps.products.views import ProductExportView
from config import openapi_commerce  # noqa: F401 - schema extension registration


class CommerceOpenAPIContractTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.schema = SchemaGenerator().get_schema(request=None, public=True)

    def response_schema(self, path, method="get", status="200", media="application/json"):
        return self.schema["paths"][path][method]["responses"][status]["content"][media]["schema"]

    def component(self, reference):
        return self.schema["components"]["schemas"][reference.rsplit("/", 1)[-1]]

    def test_cart_is_one_object_and_mutations_describe_actual_inputs(self):
        schema = self.response_schema("/api/orders/cart/")
        self.assertIn("$ref", schema)
        self.assertEqual(self.component(schema["$ref"])["type"], "object")
        request = self.schema["paths"]["/api/orders/cart/add/"]["post"]["requestBody"]["content"]["application/json"]["schema"]
        fields = self.component(request["$ref"])["properties"]
        self.assertIn("product", fields)
        self.assertIn("quantity", fields)
        operation = self.schema["paths"]["/api/orders/cart/items/{item_id}/"]["patch"]
        parameter = next(value for value in operation["parameters"] if value["name"] == "item_id")
        self.assertEqual(parameter["schema"]["type"], "integer")
        self.assertNotIn("requestBody", self.schema["paths"]["/api/orders/cart/items/{item_id}/"]["delete"])

    def test_product_binary_and_multipart_contracts_use_correct_media_types(self):
        png = self.response_schema("/api/products/products/{product_id}/qr-code/", media="image/png")
        self.assertEqual(png, {"type": "string", "format": "binary"})
        csv = self.response_schema("/api/products/export/", media="text/csv")
        self.assertEqual(csv["format"], "binary")
        request = self.schema["paths"]["/api/products/bulk-upload/"]["post"]["requestBody"]["content"]["multipart/form-data"]["schema"]
        component = self.component(request["$ref"])
        self.assertEqual(component["properties"]["file"]["format"], "binary")
        self.assertIn("file", component["required"])
        labels = self.response_schema("/api/products/labels/")
        self.assertEqual(labels["type"], "array")

    def test_health_and_metrics_describe_derived_fields_and_failure_status(self):
        health = self.component(self.response_schema("/api/observability/health/")["$ref"])["properties"]
        self.assertEqual(health["is_stale"]["type"], "boolean")
        self.assertEqual(health["stale_after_seconds"]["type"], "integer")
        unavailable = self.component(self.response_schema("/api/observability/health/", status="503")["$ref"])
        self.assertIn("detail", unavailable["properties"])
        metrics = self.component(self.response_schema("/api/observability/stats/")["$ref"])["properties"]
        self.assertEqual(metrics["request_trend"]["type"], "array")
        self.assertEqual(metrics["status_codes"]["type"], "array")

    def test_schema_replacements_do_not_replace_runtime_views(self):
        self.assertIs(resolve("/api/orders/cart/").func.cls, CartViewSet)
        self.assertIs(resolve("/api/products/export/").func.view_class, ProductExportView)

    @skipUnless(find_spec("apps.returns.customer_workflows"), "Requires the customer-return workflow PR.")
    def test_customer_return_evidence_and_tracking_have_explicit_contracts(self):
        upload = self.schema["paths"]["/api/returns/requests/{id}/attachments/"]["post"]
        request = upload["requestBody"]["content"]["multipart/form-data"]["schema"]
        self.assertEqual(self.component(request["$ref"])["properties"]["file"]["format"], "binary")
        self.assertIn("201", upload["responses"])
        tracking = self.schema["paths"]["/api/returns/requests/{id}/shipment/"]["post"]
        fields = self.component(tracking["requestBody"]["content"]["application/json"]["schema"]["$ref"])
        self.assertEqual(set(fields["required"]), {"carrier", "tracking_number"})
        self.assertIn("409", tracking["responses"])
        for path in ("/api/returns/attachments/{id}/download/", "/api/returns/shipments/{id}/label/download/"):
            download = self.schema["paths"][path]["get"]
            self.assertEqual(download["security"], [{"jwtAuth": []}])
            self.assertEqual(download["responses"]["200"]["content"]["*/*"]["schema"]["format"], "binary")
            headers = download["responses"]["200"]["headers"]
            self.assertIn("Cache-Control", headers)
            self.assertIn("X-Content-Type-Options", headers)

    @skipUnless(find_spec("apps.returns.inventory_restoration"), "Requires the explicit return-restoration PR.")
    def test_return_restock_requires_confirmation_and_describes_idempotent_results(self):
        operation = self.schema["paths"]["/api/returns/requests/{id}/items/{item_pk}/restock/"]["post"]
        self.assertEqual(operation["security"], [{"jwtAuth": []}])
        request = self.component(operation["requestBody"]["content"]["application/json"]["schema"]["$ref"])
        self.assertEqual(set(request["required"]), {"warehouse", "quantity", "idempotency_key", "sellable_confirmed"})
        self.assertEqual(request["properties"]["sellable_confirmed"], {"type": "boolean", "enum": [True]})
        for status in ("200", "201"):
            result = self.component(operation["responses"][status]["content"]["application/json"]["schema"]["$ref"])
            self.assertEqual(result["properties"]["replayed"]["type"], "boolean")
            self.assertEqual(result["properties"]["remaining_quantity"]["minimum"], 0)
        self.assertIn("409", operation["responses"])
