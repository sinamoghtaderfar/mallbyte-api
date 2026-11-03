from django.test import SimpleTestCase
from django.urls import reverse


class LivenessTests(SimpleTestCase):
    def test_liveness_is_public_and_contains_no_infrastructure_details(self):
        response = self.client.get(reverse("liveness"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})
        self.assertNotIn("database", response.content.decode().lower())
        self.assertNotIn("secret", response.content.decode().lower())
