from decimal import Decimal
from typing import cast

from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from apps.accounts.models import User
from apps.notifications.models import Notification, NotificationPreference
from apps.orders.models import Order, OrderItem
from apps.products.models import Category, Product
from apps.reviews.models import ProductReview


class ProductReviewNotificationTests(APITestCase):
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
            phone="+989920000001",
            email="admin_review_notification@example.com",
            full_name="Review Notification Admin",
            is_staff=True,
            is_superuser=True,
        )

        self.customer = self.create_test_user(
            phone="+989920000002",
            email="customer_review_notification@example.com",
            full_name="Review Notification Customer",
        )

        self.category = Category.objects.create(
            name="Review Notification Category",
            description="Category for review notification tests",
            is_active=True,
        )

        self.product = Product.objects.create(
            seller=self.admin_user,
            category=self.category,
            name="Review Notification Product",
            description="Product for review notification tests",
            price=Decimal("100000"),
            status=Product.StatusChoices.APPROVED,
            is_active=True,
            sku="REVIEW-NOTIFICATION-SKU-001",
        )

        self.order = Order.objects.create(
            user=self.customer,
            status=Order.StatusChoices.DELIVERED,
            payment_status=Order.PaymentStatusChoices.PAID,
            subtotal=Decimal("100000"),
            discount_amount=Decimal("0"),
            shipping_cost=Decimal("0"),
            tax_amount=Decimal("0"),
            receiver_name="Review Notification Customer",
            receiver_phone="+989920000002",
            province="Tehran",
            city="Tehran",
            address="Review notification address",
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

    def authenticate_admin(self):
        self.get_api_client().force_authenticate(user=self.admin_user)

    def create_pending_review(self):
        return ProductReview.objects.create(
            customer=self.customer,
            product=self.product,
            order_item=self.order_item,
            rating=5,
            title="Pending review",
            comment="Pending review comment.",
            status=ProductReview.StatusChoices.PENDING,
            is_verified_purchase=True,
        )

    def assert_review_notification_exists(self, *, review, title, template_key):
        self.assertTrue(
            Notification.objects.filter(
                user=self.customer,
                notification_type=Notification.NotificationType.PRODUCT,
                related_object_type="product_review",
                related_object_id=str(review.pk),
                title=title,
                metadata__template_key=template_key,
            ).exists()
        )

    def test_review_submitted_creates_notification(self):
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

        self.assert_review_notification_exists(
            review=review,
            title="Review submitted",
            template_key="review_submitted",
        )

    def test_review_approved_creates_notification(self):
        review = self.create_pending_review()

        self.authenticate_admin()

        url = reverse("product-review-approve", args=[review.pk])

        response = self.client.post(url, data={}, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        review.refresh_from_db()

        self.assertEqual(review.status, ProductReview.StatusChoices.APPROVED)

        self.assert_review_notification_exists(
            review=review,
            title="Review approved",
            template_key="review_approved",
        )

    def test_review_rejected_creates_notification(self):
        review = self.create_pending_review()

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

        self.assert_review_notification_exists(
            review=review,
            title="Review rejected",
            template_key="review_rejected",
        )

    def test_review_hidden_creates_notification(self):
        review = ProductReview.objects.create(
            customer=self.customer,
            product=self.product,
            order_item=self.order_item,
            rating=5,
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

        self.assert_review_notification_exists(
            review=review,
            title="Review hidden",
            template_key="review_hidden",
        )

    def test_muted_product_notifications_block_review_notifications(self):
        NotificationPreference.objects.create(
            user=self.customer,
            muted_notification_types=[
                Notification.NotificationType.PRODUCT,
            ],
        )

        self.authenticate_customer()

        url = reverse("product-review-list")

        response = self.client.post(
            url,
            data={
                "product": self.product.pk,
                "rating": 5,
                "title": "Muted notification review",
                "comment": "This review should not create a notification.",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        review = ProductReview.objects.get(
            customer=self.customer,
            product=self.product,
        )

        self.assertFalse(
            Notification.objects.filter(
                user=self.customer,
                related_object_type="product_review",
                related_object_id=str(review.pk),
                title="Review submitted",
            ).exists()
        )