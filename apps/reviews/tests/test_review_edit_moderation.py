from django.contrib.auth.models import Permission
from django.urls import reverse
from rest_framework.test import APITestCase

from apps.reviews.models import ProductReview
from apps.reviews.services import update_product_review_stats
from apps.reviews.tests import test_product_reviews_api as fixtures


class ReviewEditModerationTests(APITestCase):
    setUp = fixtures.ProductReviewAPITests.setUp
    create_test_user = fixtures.ProductReviewAPITests.create_test_user

    def make_review(self):
        review = ProductReview.objects.create(customer=self.customer, product=self.product, order_item=self.order_item, rating=5, comment="Approved content", status="approved", approved_by=self.admin_user)
        update_product_review_stats(self.product)
        return review

    def test_customer_edit_requeues_and_refreshes_public_rating(self):
        review = self.make_review()
        self.client.force_authenticate(user=self.customer)
        response = self.client.patch(reverse("product-review-detail", args=[review.pk]), {"rating": 1, "comment": "Unreviewed replacement"}, format="json")
        self.assertEqual(response.status_code, 200)
        review.refresh_from_db()
        self.product.refresh_from_db()
        self.assertEqual(review.status, "pending")
        self.assertIsNone(review.approved_by_id)
        self.assertEqual(self.product.reviews_count, 0)
        self.assertEqual(self.product.avrage_rating, 0)

    def test_update_with_unchanged_product_does_not_reject_itself_as_duplicate(self):
        review = self.make_review()
        self.client.force_authenticate(user=self.customer)
        response = self.client.put(reverse("product-review-detail", args=[review.pk]), {"product": self.product.pk, "rating": 4, "comment": "Changed"}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status"], "pending")

    def test_plain_staff_cannot_read_pending_or_moderate_but_explicit_permission_can(self):
        review = self.make_review()
        review.status = "pending"
        review.save(update_fields=["status"])
        self.other_customer.is_staff = True
        self.other_customer.save(update_fields=["is_staff"])
        self.client.force_authenticate(user=self.other_customer)
        self.assertEqual(self.client.get(reverse("product-review-detail", args=[review.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse("product-review-approve", args=[review.pk])).status_code, 403)
        self.other_customer.user_permissions.add(Permission.objects.get(codename="change_productreview"))
        # Reload rather than reusing Django's per-object permission cache.
        self.client.force_authenticate(user=type(self.other_customer).objects.get(pk=self.other_customer.pk))
        self.assertEqual(self.client.post(reverse("product-review-approve", args=[review.pk])).status_code, 200)
