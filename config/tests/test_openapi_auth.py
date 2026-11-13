"""Authentication documentation describes the actual two-factor/cookie boundary."""
import io
from contextlib import redirect_stderr

from django.test import SimpleTestCase
from django.urls import resolve
from drf_spectacular.generators import SchemaGenerator
from drf_spectacular.validation import validate_schema

from apps.accounts.mfa_views import AdminMFACompleteView, AdminMFASetupView, AdminMFAVerifyView
from apps.accounts.views import CookieTokenRefreshView


class AuthenticationOpenAPIContractTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        output = io.StringIO()
        with redirect_stderr(output):
            cls.schema = SchemaGenerator().get_schema(request=None, public=True)
        cls.generation_messages = output.getvalue()

    def component(self, schema):
        return self.schema["components"]["schemas"][schema["$ref"].rsplit("/", 1)[-1]]

    def request(self, path):
        return self.component(self.schema["paths"][path]["post"]["requestBody"]["content"]["application/json"]["schema"])

    def response(self, path, status="200"):
        return self.component(self.schema["paths"][path]["post"]["responses"][status]["content"]["application/json"]["schema"])

    def test_schema_is_valid_and_generates_without_database_or_warning_fallbacks(self):
        # SimpleTestCase rejects any database access during schema generation.
        self.assertEqual(self.generation_messages, "")
        validate_schema(self.schema)

    def test_protected_routes_require_the_actual_bearer_jwt_scheme(self):
        self.assertEqual(self.schema["components"]["securitySchemes"]["jwtAuth"], {
            "type": "http", "scheme": "bearer", "bearerFormat": "JWT",
        })
        self.assertEqual(self.schema["paths"]["/api/orders/orders/"]["get"]["security"], [{"jwtAuth": []}])

    def test_mfa_enrollment_and_verification_document_their_real_inputs(self):
        setup = self.request("/api/auth/mfa/setup/")
        self.assertEqual(set(setup["required"]), {"challenge", "password"})
        self.assertTrue(setup["properties"]["password"]["writeOnly"])
        for path in ("/api/auth/mfa/complete/", "/api/auth/mfa/verify/"):
            request = self.request(path)
            self.assertEqual(set(request["required"]), {"challenge", "code"})
            self.assertTrue(request["properties"]["code"]["writeOnly"])
            self.assertIn({}, self.schema["paths"][path]["post"]["security"])
        result = self.response("/api/auth/mfa/complete/")
        self.assertEqual(set(result["properties"]), {"user", "access", "is_new", "recovery_codes"})
        self.assertEqual(result["properties"]["recovery_codes"]["maxItems"], 10)
        self.assertNotIn("refresh", self.response("/api/auth/mfa/verify/")["properties"])

    def test_refresh_uses_a_cookie_and_does_not_accept_a_json_refresh_token(self):
        operation = self.schema["paths"]["/api/auth/token/refresh/"]["post"]
        self.assertNotIn("requestBody", operation)
        cookie = next(parameter for parameter in operation["parameters"] if parameter["in"] == "cookie")
        self.assertEqual(cookie["name"], "mallbyte_refresh")
        self.assertTrue(cookie["required"])
        self.assertEqual(set(self.response("/api/auth/token/refresh/")["properties"]), {"access"})

    def test_registration_and_otp_describe_verification_and_privileged_challenges(self):
        registration = self.response("/api/auth/register/", "201")
        self.assertIn("verification_required", registration["properties"])
        self.assertNotIn("access", registration["properties"])
        verification = self.response("/api/auth/otp/verify/")
        variants = [self.component(item) for item in verification["oneOf"]]
        self.assertTrue(any("access" in variant["properties"] for variant in variants))
        self.assertTrue(any(set(variant["properties"]) == {"mfa_required", "challenge", "mfa_enrolled"} for variant in variants))

    def test_computed_collections_are_typed_as_arrays_and_counts_as_integers(self):
        components = self.schema["components"]["schemas"]
        self.assertEqual(components["Role"]["properties"]["permissions"]["type"], "array")
        self.assertEqual(components["Role"]["properties"]["permissions_count"]["type"], "integer")
        self.assertEqual(components["Category"]["properties"]["children"]["type"], "array")
        self.assertEqual(components["SupportTicket"]["properties"]["messages"]["type"], "array")
        action = self.schema["paths"]["/api/rbac/roles/{id}/permissions/"]["get"]
        self.assertEqual(action["responses"]["200"]["content"]["application/json"]["schema"]["type"], "array")

    def test_schema_registration_does_not_replace_runtime_authentication_views(self):
        for path, view in (
            ("/api/auth/mfa/setup/", AdminMFASetupView),
            ("/api/auth/mfa/complete/", AdminMFACompleteView),
            ("/api/auth/mfa/verify/", AdminMFAVerifyView),
            ("/api/auth/token/refresh/", CookieTokenRefreshView),
        ):
            self.assertIs(resolve(path).func.view_class, view)
