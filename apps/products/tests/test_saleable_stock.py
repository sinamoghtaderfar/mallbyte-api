from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from rest_framework.test import APITestCase

from apps.accounts.models import Seller, User
from apps.inventory.models import Stock, Warehouse
from apps.products.filters import ProductFilter
from apps.products.models import Category, Product
from apps.products.querysets import catalog_queryset
from apps.products.serializers import ProductListSerializer


class SaleableStockTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.seller = User.objects.create_user(email="saleable-seller@example.com", is_seller=True)
        Seller.objects.create(user=cls.seller, store_name="Saleable", store_slug="saleable", status="approved")
        cls.category = Category.objects.create(name="Saleable", slug="saleable")
        cls.active = Warehouse.objects.create(name="Active", code="SALE-ACTIVE", is_active=True)
        cls.inactive = Warehouse.objects.create(name="Inactive", code="SALE-INACTIVE", is_active=False)

    def product(self, sku, active=None, inactive=None):
        product = Product.objects.create(
            seller=self.seller, category=self.category, name=sku, sku=sku,
            price=100, status="approved", is_active=True,
        )
        for warehouse, amounts in ((self.active, active), (self.inactive, inactive)):
            if amounts is not None:
                Stock.objects.create(product=product, warehouse=warehouse, quantity=amounts[0], reserved_quantity=amounts[1])
        return product

    def test_inactive_only_stock_is_physical_but_unavailable(self):
        product = self.product("inactive-only", inactive=(10, 3))
        self.assertEqual(product.total_stock, 10)
        self.assertEqual(product.reserved_stock, 3)
        with self.assertNumQueries(1):
            self.assertEqual(product.available_stock, 0)
        self.assertFalse(product.is_in_stock)
        self.assertFalse(ProductFilter({"in_stock": "true"}, queryset=Product.objects.all()).qs.filter(pk=product.pk).exists())
        self.assertTrue(ProductFilter({"in_stock": "false"}, queryset=Product.objects.all()).qs.filter(pk=product.pk).exists())

    def test_mixed_warehouses_and_reservations_do_not_multiply_aggregates(self):
        product = self.product("mixed", active=(10, 4), inactive=(20, 2))
        self.assertEqual(product.available_stock, 6)
        filtered = ProductFilter({"in_stock": "true"}, queryset=catalog_queryset(Product.objects.all())).qs
        projected = filtered.get(pk=product.pk)
        self.assertEqual(projected.total_stock, 30)
        self.assertEqual(projected.reserved_stock, 6)
        with self.assertNumQueries(0):
            self.assertEqual(projected.available_stock, 6)
            self.assertTrue(projected.is_in_stock)
            self.assertEqual(ProductListSerializer(projected).data["available_stock"], 6)

    def test_fully_reserved_active_stock_cannot_be_replaced_by_inactive_stock(self):
        product = self.product("reserved-active", active=(5, 5), inactive=(30, 0))
        self.assertEqual(product.available_stock, 0)
        self.assertFalse(ProductFilter({"in_stock": "true"}, queryset=catalog_queryset(Product.objects.all())).qs.exists())
        Stock.objects.filter(product=product, warehouse=self.active).update(reserved_quantity=4)
        self.assertEqual(Product.objects.get(pk=product.pk).available_stock, 1)
        self.assertTrue(ProductFilter({"in_stock": "true"}, queryset=catalog_queryset(Product.objects.all())).qs.exists())

    def test_public_list_and_detail_share_active_availability(self):
        unavailable = self.product("public-inactive", inactive=(10, 1))
        available = self.product("public-mixed", active=(8, 3), inactive=(20, 0))
        listing = self.client.get(reverse("product-list"), {"in_stock": "true"})
        self.assertEqual(listing.status_code, 200)
        self.assertEqual([row["id"] for row in listing.data["results"]], [available.pk])
        self.assertEqual(listing.data["results"][0]["stock"], 28)
        self.assertEqual(listing.data["results"][0]["available_stock"], 5)
        detail = self.client.get(reverse("product-detail", args=[unavailable.pk]))
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.data["stock"], 10)
        self.assertEqual(detail.data["available_stock"], 0)
        self.assertFalse(detail.data["is_in_stock"])

    def test_warehouse_deactivation_is_reflected_on_next_read(self):
        product = self.product("deactivated", active=(7, 2))
        self.assertEqual(product.available_stock, 5)
        Warehouse.objects.filter(pk=self.active.pk).update(is_active=False)
        refreshed = catalog_queryset(Product.objects.all()).get(pk=product.pk)
        self.assertEqual(refreshed.available_stock, 0)
        self.assertEqual(refreshed.total_stock, 7)
        self.assertEqual(refreshed.reserved_stock, 2)

    def test_catalog_query_count_does_not_grow_per_product(self):
        for index in range(5):
            self.product(f"bounded-{index}", active=(10, 3), inactive=(20, 2))
        with CaptureQueriesContext(connection) as queries:
            data = ProductListSerializer(catalog_queryset(Product.objects.all()), many=True).data
        self.assertEqual(len(data), 5)
        self.assertTrue(all(row["available_stock"] == 7 for row in data))
        self.assertLessEqual(len(queries), 2)
