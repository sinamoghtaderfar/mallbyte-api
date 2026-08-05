from datetime import timedelta
from decimal import Decimal
from typing import cast

from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from apps import analytics
from apps.accounts.models import User
from apps.content.models import Announcement, Banner, ContentPage, FAQCategory, FAQItem
from apps.inventory.models import Stock, Warehouse
from apps.orders.models import Order, OrderItem
from apps.payments.models import Payment
from apps.products.models import Category, Product
from apps.returns.models import ReturnRequest
from apps.reviews.models import ProductReview
from apps.support.models import SupportTicket


class DashboardAnalyticsAPITests(APITestCase):
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
            phone="+989991000001",
            email="analytics_admin@example.com",
            full_name="Analytics Admin",
            is_staff=True,
            is_superuser=True,
        )

        self.customer = self.create_test_user(
            phone="+989991000002",
            email="analytics_customer@example.com",
            full_name="Analytics Customer",
        )

        self.seller = self.create_test_user(
            phone="+989991000003",
            email="analytics_seller@example.com",
            full_name="Analytics Seller",
            is_seller=True,
        )

        self.category = Category.objects.create(
            name="Analytics Category",
            slug="analytics-category",
        )

        self.product = Product.objects.create(
            seller=self.seller,
            category=self.category,
            name="Analytics Product",
            slug="analytics-product",
            description="Analytics product description.",
            price=Decimal("100000"),
            sku="ANALYTICS-SKU-001",
            status=Product.StatusChoices.APPROVED,
            is_active=True,
            is_featured=True,
        )

        self.second_product = Product.objects.create(
            seller=self.seller,
            category=self.category,
            name="Second Analytics Product",
            slug="second-analytics-product",
            description="Second analytics product description.",
            price=Decimal("50000"),
            sku="ANALYTICS-SKU-002",
            status=Product.StatusChoices.APPROVED,
            is_active=True,
            is_featured=False,
        )

        self.warehouse = Warehouse.objects.create(
            name="Analytics Warehouse",
            code="ANW",
            type=Warehouse.TypeChoices.MAIN,
            province="Tehran",
            city="Tehran",
            address="Analytics warehouse address",
            postal_code="1234567890",
            phone="02100000000",
            email="warehouse@example.com",
            manager_name="Warehouse Manager",
            manager_phone="09120000000",
            is_active=True,
            created_by=self.admin_user,
        )

        Stock.objects.create(
            product=self.product,
            warehouse=self.warehouse,
            quantity=10,
            reserved_quantity=2,
            low_stock_threshold=5,
            updated_by=self.admin_user,
        )

        Stock.objects.create(
            product=self.second_product,
            warehouse=self.warehouse,
            quantity=0,
            reserved_quantity=0,
            low_stock_threshold=5,
            updated_by=self.admin_user,
        )

        self.paid_order = Order.objects.create(
            user=self.customer,
            status=Order.StatusChoices.PAID,
            payment_status=Order.PaymentStatusChoices.PAID,
            subtotal=Decimal("200000"),
            discount_amount=Decimal("0"),
            shipping_cost=Decimal("0"),
            tax_amount=Decimal("0"),
            receiver_name="Analytics Customer",
            receiver_phone="09120000001",
            province="Tehran",
            city="Tehran",
            address="Customer address",
            postal_code="1234567890",
            paid_at=timezone.now(),
        )

        self.pending_order = Order.objects.create(
            user=self.customer,
            status=Order.StatusChoices.PENDING_PAYMENT,
            payment_status=Order.PaymentStatusChoices.UNPAID,
            subtotal=Decimal("50000"),
            discount_amount=Decimal("0"),
            shipping_cost=Decimal("0"),
            tax_amount=Decimal("0"),
            receiver_name="Analytics Customer",
            receiver_phone="09120000001",
            province="Tehran",
            city="Tehran",
            address="Customer address",
            postal_code="1234567890",
        )

        self.order_item = OrderItem.objects.create(
            order=self.paid_order,
            product=self.product,
            warehouse=self.warehouse,
            product_name=self.product.name,
            product_sku=self.product.sku,
            quantity=2,
            unit_price=Decimal("100000"),
            total_price=Decimal("200000"),
        )

        Payment.objects.create(
            order=self.paid_order,
            user=self.customer,
            provider=Payment.ProviderChoices.MOCK,
            status=Payment.StatusChoices.SUCCESS,
            amount=Decimal("200000"),
            currency="IRR",
            paid_at=timezone.now(),
            created_by=self.admin_user,
        )

        Payment.objects.create(
            order=self.pending_order,
            user=self.customer,
            provider=Payment.ProviderChoices.MOCK,
            status=Payment.StatusChoices.FAILED,
            amount=Decimal("50000"),
            currency="IRR",
            failed_at=timezone.now(),
            failure_reason="Test failed payment.",
            created_by=self.admin_user,
        )

        ProductReview.objects.create(
            customer=self.customer,
            product=self.product,
            order_item=self.order_item,
            rating=4,
            title="Good product",
            comment="This product is good.",
            status=ProductReview.StatusChoices.APPROVED,
            is_verified_purchase=True,
            approved_by=self.admin_user,
            approved_at=timezone.now(),
        )

        ProductReview.objects.create(
            customer=self.customer,
            product=self.second_product,
            rating=3,
            title="Pending review",
            comment="This review is pending.",
            status=ProductReview.StatusChoices.PENDING,
            is_verified_purchase=False,
        )

        SupportTicket.objects.create(
            customer=self.customer,
            assigned_to=self.admin_user,
            subject="Analytics support ticket",
            category=SupportTicket.CategoryChoices.ORDER,
            priority=SupportTicket.PriorityChoices.URGENT,
            status=SupportTicket.StatusChoices.OPEN,
        )

        SupportTicket.objects.create(
            customer=self.customer,
            subject="Unassigned analytics ticket",
            category=SupportTicket.CategoryChoices.PAYMENT,
            priority=SupportTicket.PriorityChoices.HIGH,
            status=SupportTicket.StatusChoices.PENDING,
        )

        ReturnRequest.objects.create(
            customer=self.customer,
            order=self.paid_order,
            status=ReturnRequest.Status.SUBMITTED,
            reason=ReturnRequest.Reason.DAMAGED,
            requested_resolution=ReturnRequest.RequestedResolution.REFUND,
            total_requested_amount=Decimal("50000.00"),
            total_approved_amount=Decimal("0.00"),
        )

        ContentPage.objects.create(
            title="Analytics Page",
            slug="analytics-page",
            page_type=ContentPage.PageTypeChoices.LANDING,
            content="Analytics page content.",
            status=ContentPage.StatusChoices.PUBLISHED,
            published_at=timezone.now(),
            is_featured=True,
            created_by=self.admin_user,
            updated_by=self.admin_user,
        )

        Banner.objects.create(
            title="Analytics Banner",
            subtitle="Analytics banner subtitle.",
            image=SimpleUploadedFile(
                "analytics-banner.jpg",
                b"fake-image-content",
                content_type="image/jpeg",
            ),
            placement=Banner.PlacementChoices.HOME_HERO,
            status=Banner.StatusChoices.PUBLISHED,
            published_at=timezone.now(),
        )

        Announcement.objects.create(
            title="Analytics Announcement",
            message="Analytics announcement message.",
            level=Announcement.LevelChoices.INFO,
            placement=Announcement.PlacementChoices.GLOBAL,
            status=Announcement.StatusChoices.PUBLISHED,
            published_at=timezone.now(),
        )

        self.faq_category = FAQCategory.objects.create(
            name="Analytics FAQ Category",
            slug="analytics-faq-category",
            is_active=True,
        )

        FAQItem.objects.create(
            category=self.faq_category,
            question="Analytics FAQ?",
            answer="Analytics FAQ answer.",
            is_active=True,
            is_featured=True,
        )

    def get_api_client(self) -> APIClient:
        return cast(APIClient, self.client)

    def authenticate_admin(self):
        self.get_api_client().force_authenticate(user=self.admin_user)

    def authenticate_customer(self):
        self.get_api_client().force_authenticate(user=self.customer)

    def test_anonymous_user_cannot_access_dashboard(self):
        url = reverse("analytics-dashboard")

        response = self.client.get(url)

        self.assertIn(
            response.status_code,
            [
                status.HTTP_401_UNAUTHORIZED,
                status.HTTP_403_FORBIDDEN,
            ],
        )

    def test_customer_cannot_access_dashboard(self):
        self.authenticate_customer()

        url = reverse("analytics-dashboard")

        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_admin_can_access_dashboard(self):
        self.authenticate_admin()

        url = reverse("analytics-dashboard")

        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()

        self.assertIn("filters", data)
        self.assertIn("sales", data)
        self.assertIn("orders", data)
        self.assertIn("payments", data)
        self.assertIn("products", data)
        self.assertIn("customers", data)
        self.assertIn("reviews", data)
        self.assertIn("support", data)
        self.assertIn("returns", data)
        self.assertIn("content", data)
        self.assertIn("trends", data)
        
    def test_dashboard_sales_and_orders_summary(self):
        self.authenticate_admin()

        url = reverse("analytics-dashboard")

        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()

        self.assertEqual(data["sales"]["total_revenue"], "200000.00")
        self.assertEqual(data["sales"]["paid_orders_count"], 1)
        self.assertEqual(data["sales"]["average_order_value"], "200000.00")

        self.assertEqual(data["orders"]["total_orders"], 2)
        self.assertEqual(data["orders"]["by_status"][Order.StatusChoices.PAID], 1)
        self.assertEqual(
            data["orders"]["by_status"][Order.StatusChoices.PENDING_PAYMENT],
            1,
        )
        self.assertEqual(
            data["orders"]["by_payment_status"][Order.PaymentStatusChoices.PAID],
            1,
        )
        self.assertEqual(
            data["orders"]["by_payment_status"][Order.PaymentStatusChoices.UNPAID],
            1,
        )

    def test_dashboard_payments_summary(self):
        self.authenticate_admin()

        url = reverse("analytics-dashboard")

        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()

        self.assertEqual(data["payments"]["total_payments"], 2)
        self.assertEqual(data["payments"]["successful_amount"], "200000.00")
        self.assertEqual(data["payments"]["failed_payments"], 1)
        self.assertEqual(
            data["payments"]["by_status"][Payment.StatusChoices.SUCCESS],
            1,
        )
        self.assertEqual(
            data["payments"]["by_status"][Payment.StatusChoices.FAILED],
            1,
        )
        self.assertEqual(data["payments"]["by_provider"][Payment.ProviderChoices.MOCK], 2)

    def test_dashboard_products_and_inventory_summary(self):
        self.authenticate_admin()

        url = reverse("analytics-dashboard")

        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()

        self.assertEqual(data["products"]["total_products"], 2)
        self.assertEqual(data["products"]["active_products"], 2)
        self.assertEqual(data["products"]["approved_products"], 2)
        self.assertEqual(data["products"]["featured_products"], 1)
        self.assertEqual(data["products"]["total_stock_quantity"], 10)
        self.assertEqual(data["products"]["reserved_stock_quantity"], 2)
        self.assertEqual(data["products"]["out_of_stock_items"], 1)

        top_products = data["products"]["top_products"]

        self.assertEqual(len(top_products), 1)
        self.assertEqual(top_products[0]["product_id"], self.product.id)
        self.assertEqual(top_products[0]["quantity_sold"], 2)
        self.assertEqual(top_products[0]["revenue"], "200000.00")

    def test_dashboard_customers_reviews_support_returns_and_content_summary(self):
        self.authenticate_admin()

        url = reverse("analytics-dashboard")

        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()

        self.assertEqual(data["customers"]["total_users"], 3)
        self.assertEqual(data["customers"]["customers"], 1)
        self.assertEqual(data["customers"]["sellers"], 1)
        self.assertEqual(data["customers"]["staff_users"], 1)

        self.assertEqual(data["reviews"]["total_reviews"], 2)
        self.assertEqual(data["reviews"]["average_rating"], "4.00")
        self.assertEqual(data["reviews"]["verified_reviews"], 1)
        self.assertEqual(
            data["reviews"]["by_status"][ProductReview.StatusChoices.APPROVED],
            1,
        )
        self.assertEqual(
            data["reviews"]["by_status"][ProductReview.StatusChoices.PENDING],
            1,
        )

        self.assertEqual(data["support"]["total_tickets"], 2)
        self.assertEqual(data["support"]["unassigned_tickets"], 1)
        self.assertEqual(data["support"]["urgent_tickets"], 1)
        self.assertEqual(data["support"]["high_priority_tickets"], 1)
        self.assertEqual(
            data["support"]["by_status"][SupportTicket.StatusChoices.OPEN],
            1,
        )
        self.assertEqual(
            data["support"]["by_status"][SupportTicket.StatusChoices.PENDING],
            1,
        )

        self.assertEqual(data["returns"]["total_returns"], 1)
        self.assertEqual(data["returns"]["requested_amount"], "50000.00")
        self.assertEqual(data["returns"]["approved_amount"], "0.00")
        self.assertEqual(
            data["returns"]["by_status"][ReturnRequest.Status.SUBMITTED],
            1,
        )

        self.assertEqual(data["content"]["pages"]["total"], 1)
        self.assertEqual(data["content"]["pages"]["published"], 1)
        self.assertEqual(data["content"]["pages"]["featured"], 1)
        self.assertEqual(data["content"]["banners"]["published"], 1)
        self.assertEqual(data["content"]["announcements"]["published"], 1)
        self.assertEqual(data["content"]["faqs"]["active"], 1)
        self.assertEqual(data["content"]["faqs"]["featured"], 1)

    def test_dashboard_period_filter_is_applied(self):
        self.authenticate_admin()

        old_order = Order.objects.create(
            user=self.customer,
            status=Order.StatusChoices.PAID,
            payment_status=Order.PaymentStatusChoices.PAID,
            subtotal=Decimal("300000"),
            discount_amount=Decimal("0"),
            shipping_cost=Decimal("0"),
            tax_amount=Decimal("0"),
            receiver_name="Old Customer",
            receiver_phone="09120000002",
            province="Tehran",
            city="Tehran",
            address="Old address",
            postal_code="1234567890",
            paid_at=timezone.now() - timedelta(days=90),
        )

        old_payment = Payment.objects.create(
            order=old_order,
            user=self.customer,
            provider=Payment.ProviderChoices.MOCK,
            status=Payment.StatusChoices.SUCCESS,
            amount=Decimal("300000"),
            currency="IRR",
            paid_at=timezone.now() - timedelta(days=90),
            created_by=self.admin_user,
        )

        old_datetime = timezone.now() - timedelta(days=90)

        Order.objects.filter(pk=old_order.pk).update(created_at=old_datetime)
        Payment.objects.filter(pk=old_payment.pk).update(created_at=old_datetime)

        url = reverse("analytics-dashboard")

        month_response = self.client.get(
            url,
            data={
                "period": "month",
            },
        )

        self.assertEqual(month_response.status_code, status.HTTP_200_OK)

        month_data = month_response.json()

        self.assertEqual(month_data["sales"]["total_revenue"], "200000.00")
        self.assertEqual(month_data["orders"]["total_orders"], 2)

        all_response = self.client.get(
            url,
            data={
                "period": "all",
            },
        )

        self.assertEqual(all_response.status_code, status.HTTP_200_OK)

        all_data = all_response.json()

        self.assertEqual(all_data["sales"]["total_revenue"], "500000.00")
        self.assertEqual(all_data["orders"]["total_orders"], 3)

    def test_dashboard_custom_date_range_filter(self):
        self.authenticate_admin()

        url = reverse("analytics-dashboard")
        today = timezone.now().date()

        response = self.client.get(
            url,
            data={
                "start_date": today.isoformat(),
                "end_date": today.isoformat(),
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()

        self.assertEqual(data["filters"]["period"], "month")
        self.assertIsNotNone(data["filters"]["start_at"])
        self.assertIsNotNone(data["filters"]["end_at"])
        self.assertEqual(data["sales"]["total_revenue"], "200000.00")

    def test_dashboard_invalid_date_range_returns_error(self):
        self.authenticate_admin()

        url = reverse("analytics-dashboard")
        today = timezone.now().date()
        yesterday = today - timedelta(days=1)

        response = self.client.get(
            url,
            data={
                "start_date": today.isoformat(),
                "end_date": yesterday.isoformat(),
            },
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_dashboard_requires_both_start_and_end_date(self):
        self.authenticate_admin()

        url = reverse("analytics-dashboard")
        today = timezone.now().date()

        response = self.client.get(
            url,
            data={
                "start_date": today.isoformat(),
            },
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)