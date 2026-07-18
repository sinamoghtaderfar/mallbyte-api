from decimal import Decimal
from typing import cast

from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from apps.accounts.models import Seller, User
from apps.notifications.models import Notification
from apps.products.models import Category, Product


class ProductNotificationTests(APITestCase):
    def create_test_user(
        self,
        *,
        phone,
        email,
        full_name,
        password="testpass123",
        is_staff=False,
        is_superuser=False,
        is_seller=False,
    ):
        user = User(
            phone=phone,
            email=email,
            full_name=full_name,
            is_active=True,
            is_staff=is_staff,
            is_superuser=is_superuser,
            is_seller=is_seller,
        )
        user.set_password(password)
        user.save()
        return user

    def setUp(self):
        self.admin_user = self.create_test_user(
            phone="+989600000001",
            email="admin_products@example.com",
            full_name="Products Admin",
            is_staff=True,
            is_superuser=True,
        )

        self.seller_user = self.create_test_user(
            phone="+989600000002",
            email="seller_products@example.com",
            full_name="Products Seller",
            is_seller=True,
        )

        self.seller = Seller.objects.create(
            user=self.seller_user,
            store_name="Products Test Store",
            store_slug="products-test-store",
            status=Seller.StatusChoices.APPROVED,
            business_phone="+989600000003",
            business_email="store_products@example.com",
            bank_info={},
            documents=[],
        )

        self.category = Category.objects.create(
            name="Products Test Category",
            description="Test category",
            is_active=True,
        )

    def get_api_client(self) -> APIClient:
        return cast(APIClient, self.client)

    def authenticate_seller(self):
        self.get_api_client().force_authenticate(user=self.seller_user)

    def authenticate_admin(self):
        self.get_api_client().force_authenticate(user=self.admin_user)

    def create_product(self, *, status_value=Product.StatusChoices.PENDING):
        return Product.objects.create(
            seller=self.seller_user,
            category=self.category,
            name="Notification Test Product",
            description="Product for notification tests",
            price=Decimal("100000"),
            status=status_value,
            is_active=True,
            sku="PRODUCT-NOTIF-SKU-001",
        )

    def assert_product_notification_exists(self, *, product, title):
        self.assertTrue(
            Notification.objects.filter(
                user=self.seller_user,
                notification_type=Notification.NotificationType.SYSTEM,
                related_object_type="product",
                related_object_id=str(product.pk),
                title=title,
            ).exists()
        )

    def test_create_product_creates_submitted_notification(self):
        self.authenticate_seller()

        url = reverse("product-list")

        response = self.client.post(
            url,
            data={
                "name": "New Seller Product",
                "description": "New product submitted by seller.",
                "short_description": "Short description",
                "price": "100000",
                "category": self.category.pk,
                "sku": "PRODUCT-NOTIF-SKU-002",
                "low_stock_threshold": 5,
                "is_featured": False,
                "labels": [],
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        product = Product.objects.get(sku="PRODUCT-NOTIF-SKU-002")

        self.assertEqual(product.seller, self.seller_user)
        self.assertEqual(product.status, Product.StatusChoices.PENDING)

        self.assert_product_notification_exists(
            product=product,
            title="Product submitted",
        )

    def test_approve_product_creates_approved_notification(self):
        self.authenticate_admin()

        product = self.create_product()

        url = reverse("product-approve", args=[product.pk])

        response = self.client.post(url, data={}, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        product.refresh_from_db()

        self.assertEqual(product.status, Product.StatusChoices.APPROVED)
        self.assertEqual(product.approved_by, self.admin_user)
        self.assertIsNotNone(product.approved_at)

        self.assert_product_notification_exists(
            product=product,
            title="Product approved",
        )

    def test_reject_product_creates_rejected_notification(self):
        self.authenticate_admin()

        product = self.create_product()

        url = reverse("product-reject", args=[product.pk])

        response = self.client.post(
            url,
            data={
                "reason": "Product images are not clear.",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        product.refresh_from_db()

        self.assertEqual(product.status, Product.StatusChoices.REJECTED)

        self.assert_product_notification_exists(
            product=product,
            title="Product rejected",
        )

        notification = Notification.objects.get(
            user=self.seller_user,
            related_object_type="product",
            related_object_id=str(product.pk),
            title="Product rejected",
        )

        self.assertEqual(
            notification.metadata["reason"],
            "Product images are not clear.",
        )
