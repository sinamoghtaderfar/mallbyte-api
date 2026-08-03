from decimal import Decimal
from typing import cast

from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from apps.accounts.models import User
from apps.orders.models import Order, OrderItem
from apps.products.models import Category, Product
from apps.reviews.models import ProductReview, ProductReviewVote


class ProductReviewVoteTests(APITestCase):
    def create_test_user(
        self,
        *,
        phone,
        email,
        full_name,
        password="testpass123",
        is_staff=False,
        is_superuser=False,
    ):
        user = User(
            phone=phone,
            email=email,
            full_name=full_name,
            is_active=True,
            is_staff=is_staff,
            is_superuser=is_superuser,
        )
        user.set_password(password)
        user.save()
        return user

    def setUp(self):
        self.admin_user = self.create_test_user(
            phone="+989910000001",
            email="admin_review_vote@example.com",
            full_name="Review Vote Admin",
            is_staff=True,
            is_superuser=True,
        )

        self.review_owner = self.create_test_user(
            phone="+989910000002",
            email="review_owner@example.com",
            full_name="Review Owner",
        )

        self.voter = self.create_test_user(
            phone="+989910000003",
            email="review_voter@example.com",
            full_name="Review Voter",
        )

        self.other_voter = self.create_test_user(
            phone="+989910000004",
            email="other_review_voter@example.com",
            full_name="Other Review Voter",
        )

        self.category = Category.objects.create(
            name="Review Vote Category",
            description="Category for review vote tests",
            is_active=True,
        )

        self.product = Product.objects.create(
            seller=self.admin_user,
            category=self.category,
            name="Review Vote Product",
            description="Product for review vote tests",
            price=Decimal("100000"),
            status=Product.StatusChoices.APPROVED,
            is_active=True,
            sku="REVIEW-VOTE-SKU-001",
        )

        self.other_product = Product.objects.create(
            seller=self.admin_user,
            category=self.category,
            name="Other Review Vote Product",
            description="Other product for review vote tests",
            price=Decimal("120000"),
            status=Product.StatusChoices.APPROVED,
            is_active=True,
            sku="REVIEW-VOTE-SKU-002",
        )

        self.order = Order.objects.create(
            user=self.review_owner,
            status=Order.StatusChoices.DELIVERED,
            payment_status=Order.PaymentStatusChoices.PAID,
            subtotal=Decimal("100000"),
            discount_amount=Decimal("0"),
            shipping_cost=Decimal("0"),
            tax_amount=Decimal("0"),
            receiver_name="Review Owner",
            receiver_phone="+989910000002",
            province="Tehran",
            city="Tehran",
            address="Review vote address",
            postal_code="1234567890",
        )

        self.order_item = OrderItem.objects.create(
            order=self.order,
            product=self.product,
            quantity=1,
            unit_price=Decimal("100000"),
            total_price=Decimal("100000"),
        )

        self.review = ProductReview.objects.create(
            customer=self.review_owner,
            product=self.product,
            order_item=self.order_item,
            rating=5,
            title="Approved review",
            comment="This is an approved review.",
            status=ProductReview.StatusChoices.APPROVED,
            is_verified_purchase=True,
        )

    def get_api_client(self) -> APIClient:
        return cast(APIClient, self.client)

    def authenticate_voter(self):
        self.get_api_client().force_authenticate(user=self.voter)

    def authenticate_other_voter(self):
        self.get_api_client().force_authenticate(user=self.other_voter)

    def authenticate_review_owner(self):
        self.get_api_client().force_authenticate(user=self.review_owner)

    def authenticate_admin(self):
        self.get_api_client().force_authenticate(user=self.admin_user)

    def test_user_can_mark_approved_review_as_helpful(self):
        self.authenticate_voter()

        url = reverse("product-review-helpful", args=[self.review.pk])

        response = self.client.post(url, data={}, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.review.refresh_from_db()

        self.assertEqual(self.review.helpful_count, 1)
        self.assertEqual(self.review.not_helpful_count, 0)

        vote = ProductReviewVote.objects.get(
            review=self.review,
            user=self.voter,
        )

        self.assertEqual(vote.vote, ProductReviewVote.VoteChoices.HELPFUL)

    def test_user_can_mark_approved_review_as_not_helpful(self):
        self.authenticate_voter()

        url = reverse("product-review-not-helpful", args=[self.review.pk])

        response = self.client.post(url, data={}, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.review.refresh_from_db()

        self.assertEqual(self.review.helpful_count, 0)
        self.assertEqual(self.review.not_helpful_count, 1)

        vote = ProductReviewVote.objects.get(
            review=self.review,
            user=self.voter,
        )

        self.assertEqual(vote.vote, ProductReviewVote.VoteChoices.NOT_HELPFUL)

    def test_user_vote_is_updated_instead_of_duplicated(self):
        self.authenticate_voter()

        helpful_url = reverse("product-review-helpful", args=[self.review.pk])
        not_helpful_url = reverse("product-review-not-helpful", args=[self.review.pk])

        helpful_response = self.client.post(helpful_url, data={}, format="json")

        self.assertEqual(helpful_response.status_code, status.HTTP_200_OK)

        not_helpful_response = self.client.post(
            not_helpful_url,
            data={},
            format="json",
        )

        self.assertEqual(not_helpful_response.status_code, status.HTTP_200_OK)

        self.review.refresh_from_db()

        self.assertEqual(self.review.helpful_count, 0)
        self.assertEqual(self.review.not_helpful_count, 1)

        self.assertEqual(
            ProductReviewVote.objects.filter(
                review=self.review,
                user=self.voter,
            ).count(),
            1,
        )

        vote = ProductReviewVote.objects.get(
            review=self.review,
            user=self.voter,
        )

        self.assertEqual(vote.vote, ProductReviewVote.VoteChoices.NOT_HELPFUL)

    def test_multiple_users_can_vote_on_same_review(self):
        self.authenticate_voter()

        helpful_url = reverse("product-review-helpful", args=[self.review.pk])

        first_response = self.client.post(helpful_url, data={}, format="json")

        self.assertEqual(first_response.status_code, status.HTTP_200_OK)

        self.authenticate_other_voter()

        second_response = self.client.post(helpful_url, data={}, format="json")

        self.assertEqual(second_response.status_code, status.HTTP_200_OK)

        self.review.refresh_from_db()

        self.assertEqual(self.review.helpful_count, 2)
        self.assertEqual(self.review.not_helpful_count, 0)

    def test_user_cannot_vote_on_own_review(self):
        self.authenticate_review_owner()

        url = reverse("product-review-helpful", args=[self.review.pk])

        response = self.client.post(url, data={}, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        data = response.json()

        self.assertEqual(data["detail"], "You cannot vote on your own review.")

        self.review.refresh_from_db()

        self.assertEqual(self.review.helpful_count, 0)
        self.assertEqual(self.review.not_helpful_count, 0)

        self.assertFalse(
            ProductReviewVote.objects.filter(
                review=self.review,
                user=self.review_owner,
            ).exists()
        )

    def test_user_cannot_vote_on_pending_review(self):
        pending_review = ProductReview.objects.create(
            customer=self.review_owner,
            product=self.other_product,
            rating=4,
            title="Pending review",
            comment="This review is pending.",
            status=ProductReview.StatusChoices.PENDING,
            is_verified_purchase=False,
        )

        self.authenticate_admin()

        url = reverse("product-review-helpful", args=[pending_review.pk])

        response = self.client.post(url, data={}, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        data = response.json()

        self.assertEqual(data["detail"], "You can only vote on approved reviews.")

        pending_review.refresh_from_db()

        self.assertEqual(pending_review.helpful_count, 0)
        self.assertEqual(pending_review.not_helpful_count, 0)

    def test_anonymous_user_cannot_vote_on_review(self):
        url = reverse("product-review-helpful", args=[self.review.pk])

        response = self.client.post(url, data={}, format="json")

        self.assertIn(
            response.status_code,
            [
                status.HTTP_401_UNAUTHORIZED,
                status.HTTP_403_FORBIDDEN,
            ],
        )

        self.review.refresh_from_db()

        self.assertEqual(self.review.helpful_count, 0)
        self.assertEqual(self.review.not_helpful_count, 0)