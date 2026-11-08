from decimal import Decimal
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from rest_framework import serializers
from rest_framework.test import APITestCase

from apps.accounts.models import Seller, User
from apps.inventory.models import Stock, Warehouse
from apps.products.filters import ProductFilter
from apps.products.models import Category, Product, ProductImage, ProductVariant, Tag
from apps.products.querysets import catalog_queryset
from apps.products.serializers import CategorySerializer, ProductCreateUpdateSerializer, ProductListSerializer


class CatalogIntegrityTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.seller = User.objects.create_user(email="catalog-integrity@example.com", is_seller=True)
        Seller.objects.create(user=cls.seller, store_name="Catalog integrity", store_slug="catalog-integrity", status="approved")
        cls.category = Category.objects.create(name="Integrity", slug="integrity")
        cls.product = Product.objects.create(seller=cls.seller, category=cls.category, name="Integrity", sku="integrity", price=100, status="approved")

    def test_negative_and_inconsistent_prices_rejected_by_database(self):
        for changes in ({"price": -1}, {"compare_price": 99}, {"cost_per_item": -1}, {"weight": -1}):
            with self.subTest(changes=changes), self.assertRaises(IntegrityError), transaction.atomic():
                Product.objects.filter(pk=self.product.pk).update(**changes)

    def test_main_image_and_default_variant_are_unique(self):
        ProductImage.objects.create(product=self.product, image="main.png", is_main=True)
        with self.assertRaises(IntegrityError), transaction.atomic():
            ProductImage.objects.create(product=self.product, image="other.png", is_main=True)
        ProductVariant.objects.create(product=self.product, name="One", sku="variant-one", price=100, is_default=True)
        with self.assertRaises(IntegrityError), transaction.atomic():
            ProductVariant.objects.create(product=self.product, name="Two", sku="variant-two", price=100, is_default=True)

    def test_variant_final_price_matches_selling_price(self):
        variant = ProductVariant(product=self.product, name="Discounted", sku="discounted", price=Decimal("80"), compare_price=Decimal("100"))
        self.assertEqual(variant.final_price, Decimal("80"))

    def test_nested_existing_sku_can_be_replaced_and_explicit_empty_lists_clear(self):
        ProductVariant.objects.create(product=self.product, name="Old", sku="replace-me", price=100)
        tag = Tag.objects.create(name="clear-tag")
        self.product.tags.add(tag)
        serializer = ProductCreateUpdateSerializer(self.product, data={"variants": [{"name": "New", "sku": "replace-me", "price": 80}], "tags": []}, partial=True)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        serializer.save()
        self.assertEqual(self.product.variants.get().name, "New")
        self.assertFalse(self.product.tags.exists())
        clear = ProductCreateUpdateSerializer(self.product, data={"variants": []}, partial=True)
        self.assertTrue(clear.is_valid(), clear.errors)
        clear.save()
        self.assertFalse(self.product.variants.exists())

    def test_duplicate_nested_skus_are_validation_errors(self):
        serializer = ProductCreateUpdateSerializer(self.product, data={"variants": [{"name": "One", "sku": "duplicate", "price": 100}, {"name": "Two", "sku": "duplicate", "price": 100}]}, partial=True)
        self.assertFalse(serializer.is_valid())
        self.assertIn("variants", serializer.errors)

    def test_nested_constraint_race_rolls_back_all_changes(self):
        ProductVariant.objects.create(product=self.product, name="Original", sku="original", price=100)
        serializer = ProductCreateUpdateSerializer(self.product, data={"name": "Must roll back", "variants": [{"name": "New", "sku": "new", "price": 100}]}, partial=True)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        with patch("apps.products.serializers.ProductVariant.objects.create", side_effect=IntegrityError("concurrent SKU collision")):
            with self.assertRaises(serializers.ValidationError):
                serializer.save()
        self.product.refresh_from_db()
        self.assertEqual(self.product.name, "Integrity")
        self.assertEqual(self.product.variants.get().sku, "original")
        self.assertEqual(self.product.status, "approved")

    def test_invalid_compare_price_labels_and_category_cycle_are_rejected(self):
        for payload in ({"compare_price": 90}, {"labels": "new"}, {"labels": ["unknown"]}, {"weight": -1}):
            serializer = ProductCreateUpdateSerializer(self.product, data=payload, partial=True)
            self.assertFalse(serializer.is_valid(), payload)
        child = Category.objects.create(name="Child", slug="child", parent=self.category)
        category = CategorySerializer(self.category, data={"parent": child.pk}, partial=True)
        self.assertFalse(category.is_valid())

    def test_stock_filter_does_not_multiply_warehouse_aggregates(self):
        for index in range(2):
            warehouse = Warehouse.objects.create(name=f"Warehouse {index}", code=f"WH{index}")
            Stock.objects.create(product=self.product, warehouse=warehouse, quantity=10, reserved_quantity=2)
        queryset = ProductFilter({"in_stock": "true"}, queryset=catalog_queryset(Product.objects.all())).qs
        result = ProductListSerializer(queryset.get(pk=self.product.pk)).data
        self.assertEqual(result["stock"], 20)
        self.assertEqual(result["reserved_stock"], 4)
        self.assertEqual(result["available_stock"], 16)
        self.assertFalse(ProductFilter({"in_stock": "false"}, queryset=Product.objects.all()).qs.filter(pk=self.product.pk).exists())

    def test_comparison_validates_ids_and_uses_constant_queries(self):
        self.assertEqual(self.client.get(reverse("product-compare"), {"ids": "bad"}).status_code, 400)
        self.assertEqual(self.client.get(reverse("product-compare"), {"ids": f"{self.product.pk},{self.product.pk}"}).status_code, 400)
        self.assertEqual(self.client.get(reverse("product-compare"), {"ids": ",".join(str(i) for i in range(1, 22))}).status_code, 400)
        with CaptureQueriesContext(connection) as queries:
            response = self.client.get(reverse("product-compare"), {"ids": str(self.product.pk)})
        self.assertEqual(response.status_code, 200)
        self.assertLessEqual(len(queries), 4)

    def test_category_tree_queries_do_not_grow_with_descendant_count(self):
        for index in range(3):
            child = Category.objects.create(name=f"Child {index}", slug=f"tree-child-{index}", parent=self.category)
            Category.objects.create(name=f"Grandchild {index}", slug=f"tree-grandchild-{index}", parent=child)
        with CaptureQueriesContext(connection) as queries:
            response = self.client.get(reverse("category-list"))
        self.assertEqual(response.status_code, 200)
        self.assertLessEqual(len(queries), 4)
        root = next(row for row in response.data["results"] if row["id"] == self.category.pk)
        self.assertEqual(len(root["children"]), 3)
        self.assertTrue(all(len(row["children"]) == 1 for row in root["children"]))

    def test_featured_and_seller_lists_are_paginated(self):
        Product.objects.filter(pk=self.product.pk).update(is_featured=True)
        response = self.client.get(reverse("product-featured"))
        self.assertEqual(response.status_code, 200)
        self.assertIn("results", response.data)
        self.client.force_authenticate(self.seller)
        response = self.client.get(reverse("product-my-products"))
        self.assertEqual(response.status_code, 200)
        self.assertIn("results", response.data)

    def test_bulk_import_uses_validation_and_returns_sanitized_row_errors(self):
        self.client.force_authenticate(self.seller)
        content = f"name,sku,price,category_id,description\nNegative,negative,-1,{self.category.pk},Invalid\nGood,good,100,{self.category.pk},Valid\n"
        response = self.client.post(reverse("bulk-upload"), {"file": SimpleUploadedFile("products.csv", content.encode(), content_type="text/csv")})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["created"], 1, response.data)
        self.assertEqual(len(response.data["errors"]), 1)
        self.assertEqual(response.data["errors"][0]["row"], 2)
        self.assertFalse(Product.objects.filter(sku="negative").exists())
        self.assertEqual(Product.objects.get(sku="good").status, "pending")

    def test_non_numeric_component_parent_returns_validation_error(self):
        self.client.force_authenticate(self.seller)
        response = self.client.post(reverse("product-variant-list"), {"product": "invalid", "name": "Invalid", "sku": "invalid-parent", "price": 100})
        self.assertEqual(response.status_code, 400)


class ProductAssetStartupTests(TestCase):
    def test_registered_startup_signal_generates_actual_png_only_after_commit(self):
        seller = User.objects.create_user(email="qr-startup@example.com")
        category = Category.objects.create(name="QR startup", slug="qr-startup")
        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            product = Product.objects.create(seller=seller, category=category, name="QR startup", sku="qr-startup", price=100)
            self.assertFalse(product.qr_code)
        self.assertEqual(len(callbacks), 1)
        product.refresh_from_db()
        self.assertTrue(product.qr_code)
        with product.qr_code.open("rb") as image:
            self.assertEqual(image.read(8), b"\x89PNG\r\n\x1a\n")


class CatalogMigrationSafetyTests(TransactionTestCase):
    def test_preflight_blocks_legacy_invalid_data_then_preserves_duplicate_tag_mapping(self):
        old_target = [("products", "0010_delete_review")]
        new_target = [("products", "0011_catalog_integrity")]
        executor = MigrationExecutor(connection)
        executor.migrate(old_target)
        old_apps = executor.loader.project_state(old_target).apps
        LegacyProduct = old_apps.get_model("products", "Product")
        LegacyTag = old_apps.get_model("products", "Tag")
        LegacyCategory = old_apps.get_model("products", "Category")
        LegacyMapping = old_apps.get_model("products", "ProductTag")
        seller = User.objects.create_user(email="migration-catalog@example.com")
        category = LegacyCategory.objects.create(name="Migration", slug="migration")
        product = LegacyProduct.objects.create(seller_id=seller.pk, category_id=category.pk, name="Legacy", slug="legacy", sku="legacy", price=100)
        tag = LegacyTag.objects.create(name="Legacy tag", slug="legacy-tag")
        LegacyMapping.objects.create(product=product, tag=tag)
        invalid = LegacyProduct.objects.create(seller_id=seller.pk, category_id=category.pk, name="Invalid legacy", slug="invalid-legacy", sku="invalid-legacy", price=-1)
        try:
            with self.assertRaisesRegex(RuntimeError, "Catalog constraint preflight failed"):
                MigrationExecutor(connection).migrate(new_target)
            invalid.delete()
            MigrationExecutor(connection).migrate(new_target)
            self.assertTrue(Product.objects.get(pk=product.pk).tags.filter(pk=tag.pk).exists())
            self.assertNotIn("products_producttag", connection.introspection.table_names())
        finally:
            # Restore the full migration state even if an assertion fails.
            LegacyProduct.objects.filter(pk=invalid.pk).delete()
            executor = MigrationExecutor(connection)
            executor.migrate(executor.loader.graph.leaf_nodes())
