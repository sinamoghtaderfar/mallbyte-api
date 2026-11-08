from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest import skipUnless

from django.contrib.auth import get_user_model
from django.db import close_old_connections, connection
from django.urls import reverse
from rest_framework.test import APIClient, APITransactionTestCase

from apps.returns.models import ReturnRequest, ReturnShipment
from apps.returns.tests import test_multiseller_returns_security as fixtures


@skipUnless(connection.vendor == "postgresql", "Requires PostgreSQL row locking")
class ReturnShipmentConcurrencyTests(APITransactionTestCase):
    setUp = fixtures.MultiSellerReturnsSecurityTests.setUp

    def test_simultaneous_identical_tracking_creates_one_history_event(self):
        self.claim.status = ReturnRequest.Status.APPROVED
        self.claim.save(update_fields=["status"])
        before = self.claim.status_history.count()
        buyer_id, claim_id = self.buyer.pk, self.claim.pk
        barrier = Barrier(2)

        def submit():
            close_old_connections()
            try:
                client = APIClient()
                client.force_authenticate(get_user_model().objects.get(pk=buyer_id))
                barrier.wait(timeout=5)
                return client.post(reverse("return-customer-shipment", args=[claim_id]),
                                   {"carrier": "Test", "tracking_number": "CONCURRENT-123"}, format="json").status_code
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: submit(), range(2)))
        self.assertEqual(results, [200, 200])
        self.assertEqual(ReturnShipment.objects.filter(return_request=self.claim).count(), 1)
        self.assertEqual(self.claim.status_history.count(), before + 1)
