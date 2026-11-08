from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.products.models import Product, ProductImage, ProductVariant, Wishlist
from apps.products.tests import test_visibility_and_ownership as fixtures


class CatalogModerationHardeningTests(APITestCase):
    setUpTestData = classmethod(fixtures.ProductVisibilityAndOwnershipTests.setUpTestData.__func__)
    make_seller = classmethod(fixtures.ProductVisibilityAndOwnershipTests.make_seller.__func__)
    make_product = classmethod(fixtures.ProductVisibilityAndOwnershipTests.make_product.__func__)

    def test_parent_edit_requeues_approved_product_and_clears_approval(self):
        self.public_a.approved_by = self.admin
        self.public_a.approved_at = timezone.now()
        self.public_a.save()
        self.client.force_authenticate(user=self.seller_a)
        response = self.client.patch(reverse("product-detail", args=[self.public_a.pk]), {"description": "Changed after approval", "is_featured": True}, format="json")
        self.assertEqual(response.status_code, 200)
        self.public_a.refresh_from_db()
        self.assertEqual(self.public_a.status, Product.StatusChoices.PENDING)
        self.assertIsNone(self.public_a.approved_by_id)
        self.assertIsNone(self.public_a.approved_at)
        self.assertFalse(self.public_a.is_featured)
        self.client.force_authenticate(user=None)
        self.assertEqual(self.client.get(reverse("product-detail", args=[self.public_a.pk])).status_code, 404)

    def test_component_edits_and_deletions_requeue_product(self):
        variant = ProductVariant.objects.create(product=self.public_a, name="Original", sku="moderation-variant", price=100)
        image = ProductImage.objects.create(product=self.public_a, image="products/existing.png")
        self.client.force_authenticate(user=self.seller_a)
        operations = (
            ("product-variant-detail", variant.pk, {"name": "Changed"}, "patch"),
            ("product-image-detail", image.pk, {"alt_text": "Changed"}, "patch"),
            ("product-image-detail", image.pk, None, "delete"),
        )
        for route, pk, data, method in operations:
            self.public_a.status = Product.StatusChoices.APPROVED
            self.public_a.save(update_fields=["status"])
            response = getattr(self.client, method)(reverse(route, args=[pk]), data, format="json")
            self.assertIn(response.status_code, (200, 204))
            self.public_a.refresh_from_db()
            self.assertEqual(self.public_a.status, Product.StatusChoices.PENDING)

    def test_public_and_other_sellers_never_receive_cost_or_account_email(self):
        self.public_a.cost_per_item = 70
        self.public_a.save(update_fields=["cost_per_item"])
        for user in (None, self.customer, self.seller_b):
            self.client.force_authenticate(user=user)
            data = self.client.get(reverse("product-detail", args=[self.public_a.pk])).data
            self.assertNotIn("cost_per_item", data)
            self.assertNotIn("seller_email", data)
        self.client.force_authenticate(user=self.seller_a)
        self.assertEqual(self.client.get(reverse("product-detail", args=[self.public_a.pk])).data["seller_email"], self.seller_a.email)

    def test_wishlist_cannot_reveal_unpublished_products_and_repeated_add_is_safe(self):
        self.client.force_authenticate(user=self.customer)
        url = reverse("wishlist-list")
        for product in (self.pending_a, self.pending_b, self.inactive_b):
            self.assertEqual(self.client.post(url, {"product": product.pk}).status_code, 400)
        first = self.client.post(url, {"product": self.public_a.pk})
        again = self.client.post(url, {"product": self.public_a.pk})
        self.assertEqual(first.status_code, 201)
        self.assertEqual(again.data["id"], first.data["id"])
        self.assertEqual(Wishlist.objects.filter(user=self.customer).count(), 1)
        self.public_a.status = Product.StatusChoices.PENDING
        self.public_a.save(update_fields=["status"])
        self.assertEqual(self.client.get(url).data["results"], [])
