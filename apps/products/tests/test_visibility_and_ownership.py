from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from apps.accounts.models import Seller, User
from apps.products.models import Category, Product


class ProductVisibilityAndOwnershipTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.category = Category.objects.create(name="Visibility", slug="visibility")
        cls.customer = User.objects.create_user(
            email="buyer-visibility@example.com", full_name="Buyer"
        )
        cls.seller_a = cls.make_seller("a")
        cls.seller_b = cls.make_seller("b")
        cls.admin = User.objects.create_superuser(
            email="admin-visibility@example.com",
            full_name="Product Admin",
            password="TestPass123!",
        )
        cls.public_a = cls.make_product(cls.seller_a, "Public A", "approved", True)
        cls.public_b = cls.make_product(cls.seller_b, "Public B", "approved", True)
        cls.pending_a = cls.make_product(cls.seller_a, "Pending A", "pending", True)
        cls.pending_b = cls.make_product(cls.seller_b, "Pending B", "pending", True)
        cls.inactive_b = cls.make_product(cls.seller_b, "Inactive B", "approved", False)

    @classmethod
    def make_seller(cls, suffix):
        user = User.objects.create_user(
            email=f"seller-{suffix}-visibility@example.com",
            full_name=f"Seller {suffix}",
            is_seller=True,
        )
        Seller.objects.create(
            user=user,
            store_name=f"Visibility Store {suffix}",
            store_slug=f"visibility-store-{suffix}",
            business_email=f"store-{suffix}@example.com",
            business_phone="123456789",
            status=Seller.StatusChoices.APPROVED,
        )
        return user

    @classmethod
    def make_product(cls, seller, name, product_status, active):
        return Product.objects.create(
            seller=seller,
            category=cls.category,
            name=name,
            description="Visibility test item",
            price=100,
            sku=name.lower().replace(" ", "-"),
            status=product_status,
            is_active=active,
        )

    def authenticate(self, user):
        self.client.force_authenticate(user=user)

    def public_ids(self):
        response = self.client.get(reverse("product-list"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        return {item["id"] for item in response.data["results"]}

    def test_anonymous_and_customer_see_only_public_products(self):
        expected = {self.public_a.pk, self.public_b.pk}
        self.assertEqual(self.public_ids(), expected)
        self.authenticate(self.customer)
        self.assertEqual(self.public_ids(), expected)

    def test_logged_in_sellers_see_every_sellers_public_products(self):
        expected = {self.public_a.pk, self.public_b.pk}
        for seller in (self.seller_a, self.seller_b):
            with self.subTest(seller=seller.email):
                self.authenticate(seller)
                self.assertEqual(self.public_ids(), expected)

    def test_seller_can_retrieve_own_pending_but_not_other_sellers(self):
        self.authenticate(self.seller_a)
        self.assertEqual(
            self.client.get(reverse("product-detail", args=[self.pending_a.pk])).status_code,
            status.HTTP_200_OK,
        )
        self.assertEqual(
            self.client.get(reverse("product-detail", args=[self.pending_b.pk])).status_code,
            status.HTTP_404_NOT_FOUND,
        )
        self.assertEqual(
            self.client.get(reverse("product-detail", args=[self.public_b.pk])).status_code,
            status.HTTP_200_OK,
        )

    def test_public_cannot_retrieve_pending_or_inactive_product(self):
        for product in (self.pending_a, self.inactive_b):
            with self.subTest(product=product.pk):
                self.assertEqual(
                    self.client.get(reverse("product-detail", args=[product.pk])).status_code,
                    status.HTTP_404_NOT_FOUND,
                )

    def test_seller_only_manages_own_products(self):
        self.authenticate(self.seller_a)
        listing = self.client.get(reverse("product-my-products"))
        self.assertEqual(listing.status_code, status.HTTP_200_OK)
        self.assertEqual(
            {item["id"] for item in listing.data},
            {self.public_a.pk, self.pending_a.pk},
        )
        self.assertEqual(
            self.client.patch(
                reverse("product-detail", args=[self.public_b.pk]),
                {"name": "Hijacked"},
                format="json",
            ).status_code,
            status.HTTP_404_NOT_FOUND,
        )
        self.assertEqual(
            self.client.delete(
                reverse("product-detail", args=[self.public_b.pk])
            ).status_code,
            status.HTTP_404_NOT_FOUND,
        )
        self.public_b.refresh_from_db()
        self.assertEqual(self.public_b.name, "Public B")

    def test_customer_cannot_access_seller_listing(self):
        self.authenticate(self.customer)
        self.assertEqual(
            self.client.get(reverse("product-my-products")).status_code,
            status.HTTP_403_FORBIDDEN,
        )

    def test_admin_can_moderate_pending_products(self):
        self.authenticate(self.admin)
        response = self.client.post(reverse("product-approve", args=[self.pending_b.pk]))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.pending_b.refresh_from_db()
        self.assertEqual(self.pending_b.status, Product.StatusChoices.APPROVED)

    def test_public_catalog_listing_uses_bounded_database_queries(self):
        for index in range(25):
            self.make_product(
                self.seller_a, f"Performance Product {index}", "approved", True
            )
        with CaptureQueriesContext(connection) as queries:
            response = self.client.get(reverse("product-list"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 20)
        self.assertEqual(response.data["count"], 27)
        # Pagination, aggregate and a single prefetched image query should
        # stay bounded regardless of how many products are serialized.
        self.assertLessEqual(len(queries), 7)

    def test_default_search_ranks_name_above_description(self):
        name_match = self.make_product(
            self.seller_a, "Premium Laptop", "approved", True
        )
        desc_match = self.make_product(
            self.seller_a, "Basic Laptop", "approved", True
        )
        desc_match.description = "Premium materials included"
        desc_match.save(update_fields=["description"])

        response = self.client.get(reverse("product-list"), {"search": "premium"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        result_ids = [item["id"] for item in response.data["results"]]
        self.assertIn(name_match.pk, result_ids)
        self.assertIn(desc_match.pk, result_ids)
        self.assertLess(result_ids.index(name_match.pk), result_ids.index(desc_match.pk))

    def test_explicit_sort_overrides_default_search_relevance(self):
        name_match = self.make_product(
            self.seller_a, "Premium Laptop", "approved", True
        )
        desc_match = self.make_product(
            self.seller_a, "Basic Laptop", "approved", True
        )
        name_match.price = 200
        name_match.save(update_fields=["price"])
        desc_match.price = 50
        desc_match.description = "Premium materials included"
        desc_match.save(update_fields=["price", "description"])

        response = self.client.get(
            reverse("product-list"), {"search": "premium", "ordering": "price"}
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        result_ids = [item["id"] for item in response.data["results"]]
        self.assertLess(result_ids.index(desc_match.pk), result_ids.index(name_match.pk))
