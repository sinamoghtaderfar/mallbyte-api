from decimal import Decimal
from unittest.mock import Mock

from django.contrib.admin.sites import AdminSite
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.test import RequestFactory, TestCase

from apps.products.models import Category, Product
from apps.reviews.admin import ProductReviewAdmin, ProductReviewVoteAdmin
from apps.reviews.models import ProductReview, ProductReviewVote
from apps.reviews.services import update_product_review_stats

User = get_user_model()


class ProductReviewAdminTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.admin_site = AdminSite()
        self.review_admin = ProductReviewAdmin(ProductReview, self.admin_site)
        self.vote_admin = ProductReviewVoteAdmin(ProductReviewVote, self.admin_site)

        self.superuser = User.objects.create_superuser(
            email="admin@example.com",
            full_name="Super Admin",
            password="password",
        )
        self.moderator = User.objects.create_user(
            email="moderator@example.com",
            full_name="Review Moderator",
            password="password",
            is_staff=True,
        )
        self.customer = User.objects.create_user(
            email="customer@example.com",
            full_name="Customer User",
            password="password",
        )
        self.seller = User.objects.create_user(
            email="seller@example.com",
            full_name="Seller User",
            password="password",
            is_seller=True,
        )

        self.category = Category.objects.create(
            name="Accessories",
            slug="accessories",
        )

        self.product = Product.objects.create(
            seller=self.seller,
            category=self.category,
            name="USB-C Docking Station",
            slug="usb-c-docking-station",
            description="A useful USB-C dock.",
            price=1000000,
            sku="DOCK-001",
            status=Product.StatusChoices.APPROVED,
            is_active=True,
        )

    def make_request(self, user):
        request = self.factory.get("/admin/reviews/productreview/")
        request.user = user
        return request

    def create_review(self, **overrides):
        data = {
            "customer": self.customer,
            "product": self.product,
            "rating": 4,
            "title": "Good product",
            "comment": "Works well.",
            "status": ProductReview.StatusChoices.PENDING,
            "is_verified_purchase": True,
        }
        data.update(overrides)

        return ProductReview.objects.create(**data)

    def test_superuser_keeps_full_review_edit_access(self):
        request = self.make_request(self.superuser)

        readonly_fields = self.review_admin.get_readonly_fields(request)

        self.assertNotIn("customer", readonly_fields)
        self.assertNotIn("product", readonly_fields)
        self.assertNotIn("rating", readonly_fields)
        self.assertNotIn("title", readonly_fields)
        self.assertNotIn("comment", readonly_fields)
        self.assertNotIn("status", readonly_fields)
        self.assertIn("approved_at", readonly_fields)

    def test_staff_moderator_can_only_edit_status_and_rejection_reason(self):
        request = self.make_request(self.moderator)

        readonly_fields = self.review_admin.get_readonly_fields(request)

        self.assertIn("customer", readonly_fields)
        self.assertIn("product", readonly_fields)
        self.assertIn("rating", readonly_fields)
        self.assertIn("title", readonly_fields)
        self.assertIn("comment", readonly_fields)
        self.assertIn("is_verified_purchase", readonly_fields)
        self.assertIn("helpful_count", readonly_fields)
        self.assertIn("not_helpful_count", readonly_fields)

        self.assertNotIn("status", readonly_fields)
        self.assertNotIn("rejected_reason", readonly_fields)

    def test_staff_moderator_cannot_add_or_delete_reviews(self):
        request = self.make_request(self.moderator)
        review = self.create_review()

        self.assertFalse(self.review_admin.has_add_permission(request))
        self.assertFalse(self.review_admin.has_delete_permission(request, review))

    def test_superuser_can_add_and_delete_reviews(self):
        request = self.make_request(self.superuser)
        review = self.create_review()

        self.assertTrue(self.review_admin.has_add_permission(request))
        self.assertTrue(self.review_admin.has_delete_permission(request, review))

    def test_save_model_approves_review_and_refreshes_product_stats(self):
        review = self.create_review(rating=5)
        request = self.make_request(self.moderator)

        review.status = ProductReview.StatusChoices.APPROVED
        self.review_admin.save_model(request, review, form=None, change=True)

        review.refresh_from_db()
        self.product.refresh_from_db()

        self.assertEqual(review.status, ProductReview.StatusChoices.APPROVED)
        self.assertEqual(review.approved_by, self.moderator)
        self.assertIsNotNone(review.approved_at)
        self.assertEqual(review.rejected_reason, "")

        self.assertEqual(self.product.reviews_count, 1)
        self.assertEqual(self.product.avrage_rating, Decimal("5.00"))

    def test_save_model_rejects_review_and_removes_it_from_product_stats(self):
        review = self.create_review(
            rating=5,
            status=ProductReview.StatusChoices.APPROVED,
            approved_by=self.superuser,
        )
        update_product_review_stats(self.product)

        self.product.refresh_from_db()
        self.assertEqual(self.product.reviews_count, 1)

        request = self.make_request(self.moderator)

        review.status = ProductReview.StatusChoices.REJECTED
        review.rejected_reason = "Spam content."
        self.review_admin.save_model(request, review, form=None, change=True)

        review.refresh_from_db()
        self.product.refresh_from_db()

        self.assertEqual(review.status, ProductReview.StatusChoices.REJECTED)
        self.assertIsNone(review.approved_by)
        self.assertIsNone(review.approved_at)
        self.assertEqual(review.rejected_reason, "Spam content.")

        self.assertEqual(self.product.reviews_count, 0)
        self.assertEqual(self.product.avrage_rating, Decimal("0.00"))

    def test_bulk_hide_reviews_updates_product_stats(self):
        review = self.create_review(
            rating=5,
            status=ProductReview.StatusChoices.APPROVED,
            approved_by=self.superuser,
        )
        update_product_review_stats(self.product)

        self.product.refresh_from_db()
        self.assertEqual(self.product.reviews_count, 1)

        request = self.make_request(self.moderator)
        self.review_admin.message_user = Mock()

        self.review_admin.hide_reviews(
            request,
            ProductReview.objects.filter(pk=review.pk),
        )

        review.refresh_from_db()
        self.product.refresh_from_db()

        self.assertEqual(review.status, ProductReview.StatusChoices.HIDDEN)
        self.assertEqual(self.product.reviews_count, 0)
        self.assertEqual(self.product.avrage_rating, Decimal("0.00"))

    def test_review_vote_admin_is_read_only_for_moderators(self):
        request = self.make_request(self.moderator)

        readonly_fields = self.vote_admin.get_readonly_fields(request)

        self.assertIn("review", readonly_fields)
        self.assertIn("user", readonly_fields)
        self.assertIn("vote", readonly_fields)
        self.assertFalse(self.vote_admin.has_add_permission(request))
        self.assertFalse(self.vote_admin.has_delete_permission(request))


class SetupReviewModeratorRoleCommandTests(TestCase):
    def test_command_creates_limited_review_moderator_group(self):
        call_command("setup_review_moderator_role")

        group = Group.objects.get(name="Review Moderators")
        permission_codenames = set(group.permissions.values_list("codename", flat=True))

        self.assertIn("view_productreview", permission_codenames)
        self.assertIn("change_productreview", permission_codenames)
        self.assertIn("view_productreviewvote", permission_codenames)

        self.assertNotIn("add_productreview", permission_codenames)
        self.assertNotIn("delete_productreview", permission_codenames)
        self.assertNotIn("change_productreviewvote", permission_codenames)
        self.assertNotIn("delete_productreviewvote", permission_codenames)
