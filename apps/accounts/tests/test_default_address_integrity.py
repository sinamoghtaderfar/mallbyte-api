from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest import skipUnless
from unittest.mock import patch

from django.db import IntegrityError, close_old_connections, connection, connections, transaction
from django.test import TransactionTestCase
from rest_framework.test import APITestCase

from apps.accounts.models import Address, User


def address_payload(title="Home"):
    return {
        "title": title, "province": "Berlin", "city": "Berlin", "street": "Example Street",
        "building_number": "10", "postal_code": "10115", "receiver_name": "Owner", "receiver_phone": "+491234567890",
    }


class DefaultAddressIntegrityTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="owner@example.com")
        self.first = Address.objects.create(user=self.user, is_default=True, **address_payload())
        self.second = Address.objects.create(user=self.user, **address_payload("Work"))
        self.client.force_authenticate(self.user)

    def test_database_rejects_multiple_defaults_even_when_model_save_is_bypassed(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Address.objects.filter(pk=self.second.pk).update(is_default=True)
        self.assertEqual(Address.objects.filter(user=self.user, is_default=True).count(), 1)

    def test_stale_full_metadata_save_cannot_restore_an_old_default(self):
        stale = Address.objects.get(pk=self.first.pk)
        self.second.is_default = True
        self.second.save(update_fields=["is_default"])
        stale.title = "New title"
        stale.save()
        stale.refresh_from_db()
        self.second.refresh_from_db()
        self.assertEqual(stale.title, "New title")
        self.assertFalse(stale.is_default)
        self.assertTrue(self.second.is_default)

    def test_partial_metadata_save_cannot_clear_another_default(self):
        stale = Address.objects.get(pk=self.first.pk)
        self.second.is_default = True
        self.second.save(update_fields=["is_default"])
        stale.title = "Changed metadata"
        stale.save(update_fields=["title"])
        self.assertFalse(stale.is_default)
        self.assertTrue(Address.objects.get(pk=self.second.pk).is_default)

    def test_failed_promotion_preserves_previous_default(self):
        self.second.is_default = True
        with patch.object(Address, "save_base", side_effect=RuntimeError("save failed")):
            with self.assertRaises(RuntimeError):
                self.second.save(update_fields=["is_default"])
        self.first.refresh_from_db()
        self.second.refresh_from_db()
        self.assertTrue(self.first.is_default)
        self.assertFalse(self.second.is_default)

    def test_set_default_api_uses_the_atomic_promotion(self):
        response = self.client.patch(f"/api/auth/addresses/{self.second.pk}/set_default/")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(list(Address.objects.filter(user=self.user, is_default=True).values_list("pk", flat=True)), [self.second.pk])

    def test_default_is_optional_and_other_users_are_unaffected(self):
        other = User.objects.create_user(email="other@example.com")
        other_default = Address.objects.create(user=other, is_default=True, **address_payload())
        self.first.is_default = False
        self.first.save(update_fields=["is_default"])
        self.assertFalse(Address.objects.filter(user=self.user, is_default=True).exists())
        self.assertTrue(Address.objects.get(pk=other_default.pk).is_default)


@skipUnless(connection.vendor == "postgresql", "PostgreSQL row-lock semantics required")
class DefaultAddressConcurrencyTests(TransactionTestCase):
    def test_simultaneous_first_default_promotions_leave_one_default(self):
        user = User.objects.create_user(email="owner@example.com")
        addresses = [Address.objects.create(user=user, **address_payload(title)) for title in ("Home", "Work")]
        barrier = Barrier(2)

        def promote(address_id):
            close_old_connections()
            try:
                address = Address.objects.get(pk=address_id)
                barrier.wait(timeout=10)
                address.is_default = True
                address.save(update_fields=["is_default"])
                return address.pk
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(promote, address.pk) for address in addresses]
            self.assertEqual({future.result(timeout=15) for future in futures}, {address.pk for address in addresses})
        self.assertEqual(Address.objects.filter(user=user, is_default=True).count(), 1)
