from decimal import Decimal

from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from apps.accounts.models import User
from apps.orders.models import Order, OrderItem
from apps.products.models import Category, Product
from apps.reviews.models import ProductReview


class ProductReviewStatsTests(APITestCase):
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
            phone="+989900000001",
            email="admin_review_stats@example.com",
            full_name="Review Stats Admin",
            is_staff=True,
            is_superuser=True,
        )

        self.customer = self.create_test_user(
            phone="+989900000002",
            email="customer_review_stats@example.com",
            full_name="Review Stats Customer",
        )

        self.other_customer = self.create_test_user(
            phone="+989900000003",
            email="other_customer_review_stats@example.com",
            full_name="Other Review Stats Customer",
        )

        self.category = Category.objects.create(
            name="Review Stats Category",
            description="Category for review stats tests",
            is_active=True,
        )

        self.product = Product.objects.create(
            seller=self.admin_user,
            category=self.category,
            name="Review Stats Product",
            description="Product for review stats tests",
            price=Decimal("100000"),
            status=Product.StatusChoices.APPROVED,
            is_active=True,
            sku="REVIEW-STATS-SKU-001",
        )

        self.order = Order.objects.create(
            user=self.customer,
            status=Order.StatusChoices.DELIVERED,
            payment_status=Order.PaymentStatusChoices.PAID,
            subtotal=Decimal("100000"),
            discount_amount=Decimal("0"),
            shipping_cost=Decimal("0"),
            tax_amount=Decimal("0"),
            receiver_name="Review Stats Customer",
            receiver_phone="+989900000002",
            province="Tehran",
            city="Tehran",
            address="Review stats address",
            postal_code="1234567890",
        )

        self.order_item = OrderItem.objects.create(
            order=self.order,
            product=self.product,
            quantity=1,
            unit_price=Decimal("100000"),
            total_price=Decimal("100000"),
        )

    def authenticate_admin(self):
        self.client.force_authenticate(user=self.admin_user)

    def create_review(self, *, customer, rating, status_choice):
        return ProductReview.objects.create(
            customer=customer,
            product=self.product,
            order_item=self.order_item,
            rating=rating,
            title=f"Rating {rating}",
            comment=f"Review with rating {rating}.",
            status=status_choice,
            is_verified_purchase=True,
        )

    def test_approving_review_updates_product_review_stats(self):
        review = self.create_review(
            customer=self.customer,
            rating=5,
            status_choice=ProductReview.StatusChoices.PENDING,
        )

        self.authenticate_admin()

        url = reverse("product-review-approve", args=[review.pk])

        response = self.client.post(url, data={}, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.product.refresh_from_db()

        self.assertEqual(self.product.reviews_count, 1)
        self.assertEqual(self.product.avrage_rating, Decimal("5.00"))

    def test_product_review_stats_use_only_approved_reviews(self):
        self.create_review(
            customer=self.customer,
            rating=5,
            status_choice=ProductReview.StatusChoices.APPROVED,
        )

        pending_review = self.create_review(
            customer=self.other_customer,
            rating=1,
            status_choice=ProductReview.StatusChoices.PENDING,
        )

        self.authenticate_admin()

        approve_url = reverse("product-review-approve", args=[pending_review.pk])

        response = self.client.post(approve_url, data={}, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.product.refresh_from_db()

        self.assertEqual(self.product.reviews_count, 2)
        self.assertEqual(self.product.avrage_rating, Decimal("3.00"))

    def test_rejecting_approved_review_updates_product_review_stats(self):
        review = self.create_review(
            customer=self.customer,
            rating=5,
            status_choice=ProductReview.StatusChoices.APPROVED,
        )

        self.create_review(
            customer=self.other_customer,
            rating=3,
            status_choice=ProductReview.StatusChoices.APPROVED,
        )

        self.product.avrage_rating = Decimal("4.00")
        self.product.reviews_count = 2
        self.product.save(
            update_fields=[
                "avrage_rating",
                "reviews_count",
                "updated_at",
            ]
        )

        self.authenticate_admin()

        url = reverse("product-review-reject", args=[review.pk])

        response = self.client.post(
            url,
            data={
                "reason": "Rejected after moderation.",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.product.refresh_from_db()

        self.assertEqual(self.product.reviews_count, 1)
        self.assertEqual(self.product.avrage_rating, Decimal("3.00"))

    def test_hiding_approved_review_updates_product_review_stats(self):
        review = self.create_review(
            customer=self.customer,
            rating=5,
            status_choice=ProductReview.StatusChoices.APPROVED,
        )

        self.create_review(
            customer=self.other_customer,
            rating=4,
            status_choice=ProductReview.StatusChoices.APPROVED,
        )

        self.product.avrage_rating = Decimal("4.50")
        self.product.reviews_count = 2
        self.product.save(
            update_fields=[
                "avrage_rating",
                "reviews_count",
                "updated_at",
            ]
        )

        self.authenticate_admin()

        url = reverse("product-review-hide", args=[review.pk])

        response = self.client.post(url, data={}, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.product.refresh_from_db()

        self.assertEqual(self.product.reviews_count, 1)
        self.assertEqual(self.product.avrage_rating, Decimal("4.00"))

    def test_deleting_approved_review_updates_product_review_stats(self):
        review = self.create_review(
            customer=self.customer,
            rating=5,
            status_choice=ProductReview.StatusChoices.APPROVED,
        )

        self.product.avrage_rating = Decimal("5.00")
        self.product.reviews_count = 1
        self.product.save(
            update_fields=[
                "avrage_rating",
                "reviews_count",
                "updated_at",
            ]
        )

        self.authenticate_admin()

        url = reverse("product-review-detail", args=[review.pk])

        response = self.client.delete(url)

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

        self.product.refresh_from_db()

        self.assertEqual(self.product.reviews_count, 0)
        self.assertEqual(self.product.avrage_rating, Decimal("0.00"))
