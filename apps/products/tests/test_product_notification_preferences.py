from decimal import Decimal
from typing import cast

from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from apps.accounts.models import Seller, User
from apps.notifications.models import Notification, NotificationPreference
from apps.products.models import Category, Product


class ProductNotificationPreferenceIntegrationTests(APITestCase):
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
            phone="+989710000001",
            email="admin_product_pref@example.com",
            full_name="Product Preference Admin",
            is_staff=True,
            is_superuser=True,
        )

        self.seller_user = self.create_test_user(
            phone="+989710000002",
            email="seller_product_pref@example.com",
            full_name="Product Preference Seller",
            is_seller=True,
        )

        self.seller = Seller.objects.create(
            user=self.seller_user,
            store_name="Product Preference Store",
            store_slug="product-preference-store",
            status=Seller.StatusChoices.APPROVED,
            business_phone="+989710000003",
            business_email="store_product_pref@example.com",
            bank_info={},
            documents=[],
        )

        self.category = Category.objects.create(
            name="Product Preference Category",
            description="Test category",
            is_active=True,
        )

        NotificationPreference.objects.create(
            user=self.seller_user,
            muted_notification_types=[
                Notification.NotificationType.PRODUCT,
            ],
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
            name="Muted Product Notification Test",
            description="Product for muted notification tests",
            price=Decimal("100000"),
            status=status_value,
            is_active=True,
            sku="PRODUCT-PREF-SKU-001",
        )

    def assert_product_notification_does_not_exist(self, *, product, title):
        self.assertFalse(
            Notification.objects.filter(
                user=self.seller_user,
                notification_type=Notification.NotificationType.PRODUCT,
                related_object_type="product",
                related_object_id=str(product.pk),
                title=title,
            ).exists()
        )

    def test_muted_product_type_blocks_submitted_notification(self):
        self.authenticate_seller()

        url = reverse("product-list")

        response = self.client.post(
            url,
            data={
                "name": "Muted Submitted Product",
                "description": "This product should not create a notification.",
                "short_description": "Short description",
                "price": "100000",
                "category": self.category.pk,
                "sku": "PRODUCT-PREF-SKU-002",
                "low_stock_threshold": 5,
                "is_featured": False,
                "labels": [],
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        product = Product.objects.get(sku="PRODUCT-PREF-SKU-002")

        self.assertEqual(product.status, Product.StatusChoices.PENDING)

        self.assert_product_notification_does_not_exist(
            product=product,
            title="Product submitted",
        )

    def test_muted_product_type_blocks_approved_notification(self):
        self.authenticate_admin()

        product = self.create_product()

        url = reverse("product-approve", args=[product.pk])

        response = self.client.post(url, data={}, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        product.refresh_from_db()

        self.assertEqual(product.status, Product.StatusChoices.APPROVED)

        self.assert_product_notification_does_not_exist(
            product=product,
            title="Product approved",
        )

    def test_muted_product_type_blocks_rejected_notification(self):
        self.authenticate_admin()

        product = self.create_product()

        url = reverse("product-reject", args=[product.pk])

        response = self.client.post(
            url,
            data={
                "reason": "Product information is incomplete.",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        product.refresh_from_db()

        self.assertEqual(product.status, Product.StatusChoices.REJECTED)

        self.assert_product_notification_does_not_exist(
            product=product,
            title="Product rejected",
        )
