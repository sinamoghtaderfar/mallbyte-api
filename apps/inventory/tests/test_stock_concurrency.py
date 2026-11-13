from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest import skipUnless

from django.contrib.auth import get_user_model
from django.db import close_old_connections, connection
from django.test import TransactionTestCase

from apps.inventory.models import Stock, Warehouse
from apps.inventory.serializers import StockSerializer
from apps.products.models import Category, Product


@skipUnless(connection.vendor == "postgresql", "Requires PostgreSQL transaction semantics")
class StockMetadataConcurrencyTests(TransactionTestCase):
    def test_metadata_loaded_before_reservation_does_not_overwrite_it(self):
        seller = get_user_model().objects.create_user(
            email="stock-concurrency@example.com", password="StrongPass123!",
        )
        product = Product.objects.create(
            seller=seller, category=Category.objects.create(name="Concurrency"),
            name="Stock race", price=100, sku="STOCK-RACE",
        )
        warehouse = Warehouse.objects.create(name="Race warehouse", code="RACE")
        stock = Stock.objects.create(product=product, warehouse=warehouse, quantity=10)
        metadata_loaded = Event()
        reservation_committed = Event()

        def update_metadata():
            close_old_connections()
            try:
                stale = Stock.objects.get(pk=stock.pk)
                serializer = StockSerializer(stale, data={"aisle": "A2"}, partial=True)
                serializer.is_valid(raise_exception=True)
                metadata_loaded.set()
                if not reservation_committed.wait(timeout=5):
                    raise AssertionError("Reservation did not commit")
                serializer.save()
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(update_metadata)
            self.assertTrue(metadata_loaded.wait(timeout=5))
            stock.reserve(quantity=3, user=seller)
            reservation_committed.set()
            future.result(timeout=5)

        stock.refresh_from_db()
        self.assertEqual(stock.quantity, 10)
        self.assertEqual(stock.reserved_quantity, 3)
        self.assertEqual(stock.aisle, "A2")
