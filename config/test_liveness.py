from django.test import SimpleTestCase, override_settings
from django.urls import reverse


class LivenessTests(SimpleTestCase):
    def test_liveness_is_public_and_contains_no_infrastructure_details(self):
        response = self.client.get(reverse("liveness"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})
        self.assertNotIn("database", response.content.decode().lower())
        self.assertNotIn("secret", response.content.decode().lower())

    @override_settings(
        DEBUG=False,
        ALLOWED_HOSTS=["testserver"],
        SECURE_SSL_REDIRECT=True,
        SECURE_REDIRECT_EXEMPT=[r"^healthz/$"],
    )
    def test_internal_http_healthcheck_is_not_redirected_to_https(self):
        response = self.client.get("/healthz/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})
        self.assertNotIn("Location", response.headers)

    @override_settings(
        DEBUG=False,
        ALLOWED_HOSTS=["testserver"],
        SECURE_SSL_REDIRECT=True,
        SECURE_REDIRECT_EXEMPT=[r"^healthz/$"],
    )
    def test_normal_routes_still_redirect_to_https(self):
        response = self.client.get("/api/auth/otp/request/")
        self.assertEqual(response.status_code, 301)
        self.assertTrue(response.headers["Location"].startswith("https://"))
