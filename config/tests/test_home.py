from django.test import TestCase
from django.urls import reverse


class APIHomeTests(TestCase):
    def test_api_home_returns_service_metadata(self):
        response = self.client.get(reverse("api_home"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/json")

        data = response.json()

        self.assertEqual(data["name"], "MallByte API")
        self.assertEqual(data["status"], "running")
        self.assertIn("links", data)
        self.assertIn("admin", data["links"])
        self.assertIn("health", data["links"])
