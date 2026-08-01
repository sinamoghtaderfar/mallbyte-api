from decimal import Decimal
from typing import Any, cast

from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from apps.accounts.models import User
from apps.orders.models import Order, OrderItem
from apps.products.models import Category, Product
from apps.reviews.models import ProductReview


class ProductReviewAPITests(APITestCase):
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
            phone="+989890000001",
            email="admin_review@example.com",
            full_name="Review Admin",
            is_staff=True,
            is_superuser=True,
        )

        self.customer = self.create_test_user(
            phone="+989890000002",
            email="customer_review@example.com",
            full_name="Review Customer",
        )

        self.other_customer = self.create_test_user(
            phone="+989890000003",
            email="other_customer_review@example.com",
            full_name="Other Review Customer",
        )

        self.category = Category.objects.create(
            name="Review Test Category",
            description="Category for review tests",
            is_active=True,
        )

        self.product = Product.objects.create(
            seller=self.admin_user,
            category=self.category,
            name="Review Test Product",
            description="Product for review tests",
            price=Decimal("100000"),
            status=Product.StatusChoices.APPROVED,
            is_active=True,
            sku="REVIEW-SKU-001",
        )

        self.other_product = Product.objects.create(
            seller=self.admin_user,
            category=self.category,
            name="Other Review Test Product",
            description="Other product for review tests",
            price=Decimal("150000"),
            status=Product.StatusChoices.APPROVED,
            is_active=True,
            sku="REVIEW-SKU-002",
        )

        self.order = Order.objects.create(
            user=self.customer,
            status=Order.StatusChoices.DELIVERED,
            payment_status=Order.PaymentStatusChoices.PAID,
            subtotal=Decimal("100000"),
            discount_amount=Decimal("0"),
            shipping_cost=Decimal("0"),
            tax_amount=Decimal("0"),
            receiver_name="Review Customer",
            receiver_phone="+989890000002",
            province="Tehran",
            city="Tehran",
            address="Review customer address",
            postal_code="1234567890",
        )

        self.order_item = OrderItem.objects.create(
            order=self.order,
            product=self.product,
            quantity=1,
            unit_price=Decimal("100000"),
            total_price=Decimal("100000"),
        )

    def get_api_client(self) -> APIClient:
        return cast(APIClient, self.client)

    def authenticate_customer(self):
        self.get_api_client().force_authenticate(user=self.customer)

    def authenticate_other_customer(self):
        self.get_api_client().force_authenticate(user=self.other_customer)

    def authenticate_admin(self):
        self.get_api_client().force_authenticate(user=self.admin_user)

    def get_response_items(self, response) -> list[dict[str, Any]]:
        data = response.json()

        if isinstance(data, dict) and "results" in data:
            results = data["results"]

            if isinstance(results, list):
                return results

            return []

        if isinstance(data, list):
            return data

        return []

    def test_customer_can_create_review_for_delivered_order_product(self):
        self.authenticate_customer()

        url = reverse("product-review-list")

        response = self.client.post(
            url,
            data={
                "product": self.product.pk,
                "rating": 5,
                "title": "Great product",
                "comment": "The product quality was excellent.",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        review = ProductReview.objects.get(
            customer=self.customer,
            product=self.product,
        )

        self.assertEqual(review.rating, 5)
        self.assertEqual(review.title, "Great product")
        self.assertEqual(review.status, ProductReview.StatusChoices.PENDING)
        self.assertTrue(review.is_verified_purchase)
        self.assertEqual(review.order_item, self.order_item)

    def test_customer_cannot_create_review_for_not_purchased_product(self):
        self.authenticate_customer()

        url = reverse("product-review-list")

        response = self.client.post(
            url,
            data={
                "product": self.other_product.pk,
                "rating": 4,
                "title": "Looks good",
                "comment": "I did not buy this product.",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        self.assertFalse(
            ProductReview.objects.filter(
                customer=self.customer,
                product=self.other_product,
            ).exists()
        )

    def test_customer_cannot_create_duplicate_review_for_same_product(self):
        ProductReview.objects.create(
            customer=self.customer,
            product=self.product,
            order_item=self.order_item,
            rating=5,
            title="First review",
            comment="First review comment.",
            status=ProductReview.StatusChoices.PENDING,
            is_verified_purchase=True,
        )

        self.authenticate_customer()

        url = reverse("product-review-list")

        response = self.client.post(
            url,
            data={
                "product": self.product.pk,
                "rating": 4,
                "title": "Second review",
                "comment": "Second review comment.",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        self.assertEqual(
            ProductReview.objects.filter(
                customer=self.customer,
                product=self.product,
            ).count(),
            1,
        )

    def test_customer_cannot_review_product_from_non_delivered_order(self):
        self.order.status = Order.StatusChoices.PAID
        self.order.save(update_fields=["status", "total_amount", "updated_at"])

        self.authenticate_customer()

        url = reverse("product-review-list")

        response = self.client.post(
            url,
            data={
                "product": self.product.pk,
                "rating": 5,
                "title": "Not delivered yet",
                "comment": "Order is not delivered yet.",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        self.assertFalse(
            ProductReview.objects.filter(
                customer=self.customer,
                product=self.product,
            ).exists()
        )

    def test_anonymous_user_can_only_list_approved_reviews(self):
        approved_review = ProductReview.objects.create(
            customer=self.customer,
            product=self.product,
            order_item=self.order_item,
            rating=5,
            title="Approved review",
            comment="Approved review comment.",
            status=ProductReview.StatusChoices.APPROVED,
            is_verified_purchase=True,
        )

        pending_review = ProductReview.objects.create(
            customer=self.customer,
            product=self.other_product,
            rating=3,
            title="Pending review",
            comment="Pending review comment.",
            status=ProductReview.StatusChoices.PENDING,
            is_verified_purchase=False,
        )

        url = reverse("product-review-list")

        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        items = self.get_response_items(response)
        ids = [item["id"] for item in items]

        self.assertIn(approved_review.pk, ids)
        self.assertNotIn(pending_review.pk, ids)

    def test_customer_can_see_approved_reviews_and_own_pending_reviews(self):
        approved_review = ProductReview.objects.create(
            customer=self.other_customer,
            product=self.other_product,
            rating=4,
            title="Approved review",
            comment="Approved review comment.",
            status=ProductReview.StatusChoices.APPROVED,
            is_verified_purchase=False,
        )

        own_pending_review = ProductReview.objects.create(
            customer=self.customer,
            product=self.product,
            order_item=self.order_item,
            rating=5,
            title="Own pending review",
            comment="Own pending review comment.",
            status=ProductReview.StatusChoices.PENDING,
            is_verified_purchase=True,
        )

        other_pending_review = ProductReview.objects.create(
            customer=self.other_customer,
            product=self.product,
            rating=2,
            title="Other pending review",
            comment="Other pending review comment.",
            status=ProductReview.StatusChoices.PENDING,
            is_verified_purchase=False,
        )

        self.authenticate_customer()

        url = reverse("product-review-list")

        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        items = self.get_response_items(response)
        ids = [item["id"] for item in items]

        self.assertIn(approved_review.pk, ids)
        self.assertIn(own_pending_review.pk, ids)
        self.assertNotIn(other_pending_review.pk, ids)

    def test_admin_can_approve_review(self):
        review = ProductReview.objects.create(
            customer=self.customer,
            product=self.product,
            order_item=self.order_item,
            rating=5,
            title="Pending review",
            comment="Pending review comment.",
            status=ProductReview.StatusChoices.PENDING,
            is_verified_purchase=True,
        )

        self.authenticate_admin()

        url = reverse("product-review-approve", args=[review.pk])

        response = self.client.post(url, data={}, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        review.refresh_from_db()

        self.assertEqual(review.status, ProductReview.StatusChoices.APPROVED)
        self.assertEqual(review.approved_by, self.admin_user)
        self.assertIsNotNone(review.approved_at)
        self.assertEqual(review.rejected_reason, "")

    def test_admin_can_reject_review(self):
        review = ProductReview.objects.create(
            customer=self.customer,
            product=self.product,
            order_item=self.order_item,
            rating=2,
            title="Bad review",
            comment="Bad review comment.",
            status=ProductReview.StatusChoices.PENDING,
            is_verified_purchase=True,
        )

        self.authenticate_admin()

        url = reverse("product-review-reject", args=[review.pk])

        response = self.client.post(
            url,
            data={
                "reason": "Contains inappropriate language.",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        review.refresh_from_db()

        self.assertEqual(review.status, ProductReview.StatusChoices.REJECTED)
        self.assertIsNone(review.approved_by)
        self.assertIsNone(review.approved_at)
        self.assertEqual(
            review.rejected_reason,
            "Contains inappropriate language.",
        )

    def test_admin_can_hide_review(self):
        review = ProductReview.objects.create(
            customer=self.customer,
            product=self.product,
            order_item=self.order_item,
            rating=3,
            title="Approved review",
            comment="Approved review comment.",
            status=ProductReview.StatusChoices.APPROVED,
            is_verified_purchase=True,
        )

        self.authenticate_admin()

        url = reverse("product-review-hide", args=[review.pk])

        response = self.client.post(url, data={}, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        review.refresh_from_db()

        self.assertEqual(review.status, ProductReview.StatusChoices.HIDDEN)

    def test_non_admin_cannot_approve_review(self):
        review = ProductReview.objects.create(
            customer=self.customer,
            product=self.product,
            order_item=self.order_item,
            rating=5,
            title="Pending review",
            comment="Pending review comment.",
            status=ProductReview.StatusChoices.PENDING,
            is_verified_purchase=True,
        )

        self.authenticate_customer()

        url = reverse("product-review-approve", args=[review.pk])

        response = self.client.post(url, data={}, format="json")

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        review.refresh_from_db()

        self.assertEqual(review.status, ProductReview.StatusChoices.PENDING)
