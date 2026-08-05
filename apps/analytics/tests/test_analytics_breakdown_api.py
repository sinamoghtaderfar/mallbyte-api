from datetime import timedelta
from decimal import Decimal
from typing import cast

from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from apps.accounts.models import User
from apps.orders.models import Order, OrderItem
from apps.payments.models import Payment
from apps.products.models import Category, Product
from apps.returns.models import ReturnRequest
from apps.reviews.models import ProductReview
from apps.support.models import SupportTicket


class AnalyticsBreakdownAPITests(APITestCase):
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

    def create_test_order(
        self,
        *,
        user,
        status_value,
        payment_status,
        subtotal,
    ):
        return Order.objects.create(
            user=user,
            status=status_value,
            payment_status=payment_status,
            subtotal=Decimal(str(subtotal)),
            discount_amount=Decimal("0"),
            shipping_cost=Decimal("0"),
            tax_amount=Decimal("0"),
            receiver_name=user.full_name,
            receiver_phone=user.phone,
            province="Tehran",
            city="Tehran",
            address="Analytics breakdown address",
            postal_code="1234567890",
        )

    def create_test_payment(
        self,
        *,
        order,
        user,
        provider,
        status_value,
        amount,
    ):
        return Payment.objects.create(
            order=order,
            user=user,
            provider=provider,
            status=status_value,
            amount=Decimal(str(amount)),
            currency="IRR",
            created_by=self.admin_user,
        )

    def setUp(self):
        self.admin_user = self.create_test_user(
            phone="+989993000001",
            email="breakdown_admin@example.com",
            full_name="Breakdown Admin",
            is_staff=True,
            is_superuser=True,
        )

        self.customer = self.create_test_user(
            phone="+989993000002",
            email="breakdown_customer@example.com",
            full_name="Breakdown Customer",
        )

        self.seller = self.create_test_user(
            phone="+989993000003",
            email="breakdown_seller@example.com",
            full_name="Breakdown Seller",
            is_seller=True,
        )

        self.phone_category = Category.objects.create(
            name="Phones",
            slug="phones",
        )

        self.laptop_category = Category.objects.create(
            name="Laptops",
            slug="laptops",
        )

        self.phone_product = Product.objects.create(
            seller=self.seller,
            category=self.phone_category,
            name="Analytics Phone",
            slug="analytics-phone",
            description="Analytics phone description.",
            price=Decimal("100000"),
            sku="BREAKDOWN-PHONE-001",
            status=Product.StatusChoices.APPROVED,
            is_active=True,
        )

        self.laptop_product = Product.objects.create(
            seller=self.seller,
            category=self.laptop_category,
            name="Analytics Laptop",
            slug="analytics-laptop",
            description="Analytics laptop description.",
            price=Decimal("300000"),
            sku="BREAKDOWN-LAPTOP-001",
            status=Product.StatusChoices.APPROVED,
            is_active=True,
        )

        self.paid_order = self.create_test_order(
            user=self.customer,
            status_value=Order.StatusChoices.PAID,
            payment_status=Order.PaymentStatusChoices.PAID,
            subtotal="500000",
        )

        self.pending_order = self.create_test_order(
            user=self.customer,
            status_value=Order.StatusChoices.PENDING_PAYMENT,
            payment_status=Order.PaymentStatusChoices.UNPAID,
            subtotal="50000",
        )

        self.cancelled_order = self.create_test_order(
            user=self.customer,
            status_value=Order.StatusChoices.CANCELLED,
            payment_status=Order.PaymentStatusChoices.UNPAID,
            subtotal="70000",
        )

        self.phone_order_item = OrderItem.objects.create(
            order=self.paid_order,
            product=self.phone_product,
            product_name=self.phone_product.name,
            product_sku=self.phone_product.sku,
            quantity=2,
            unit_price=Decimal("100000"),
            total_price=Decimal("200000"),
        )

        self.laptop_order_item = OrderItem.objects.create(
            order=self.paid_order,
            product=self.laptop_product,
            product_name=self.laptop_product.name,
            product_sku=self.laptop_product.sku,
            quantity=1,
            unit_price=Decimal("300000"),
            total_price=Decimal("300000"),
        )

        self.success_payment = self.create_test_payment(
            order=self.paid_order,
            user=self.customer,
            provider=Payment.ProviderChoices.MOCK,
            status_value=Payment.StatusChoices.SUCCESS,
            amount="500000",
        )

        self.failed_payment = self.create_test_payment(
            order=self.pending_order,
            user=self.customer,
            provider=Payment.ProviderChoices.STRIPE,
            status_value=Payment.StatusChoices.FAILED,
            amount="50000",
        )

        ProductReview.objects.create(
            customer=self.customer,
            product=self.phone_product,
            order_item=self.phone_order_item,
            rating=5,
            title="Approved review",
            comment="Approved review comment.",
            status=ProductReview.StatusChoices.APPROVED,
            is_verified_purchase=True,
            approved_by=self.admin_user,
            approved_at=timezone.now(),
        )

        ProductReview.objects.create(
            customer=self.customer,
            product=self.laptop_product,
            order_item=self.laptop_order_item,
            rating=4,
            title="Pending review",
            comment="Pending review comment.",
            status=ProductReview.StatusChoices.PENDING,
            is_verified_purchase=True,
        )

        SupportTicket.objects.create(
            customer=self.customer,
            assigned_to=self.admin_user,
            subject="Order support issue",
            category=SupportTicket.CategoryChoices.ORDER,
            priority=SupportTicket.PriorityChoices.URGENT,
            status=SupportTicket.StatusChoices.OPEN,
        )

        SupportTicket.objects.create(
            customer=self.customer,
            subject="Payment support issue",
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
            total_requested_amount=Decimal("100000.00"),
            total_approved_amount=Decimal("0.00"),
        )

        ReturnRequest.objects.create(
            customer=self.customer,
            order=self.paid_order,
            status=ReturnRequest.Status.APPROVED,
            reason=ReturnRequest.Reason.WRONG_ITEM,
            requested_resolution=ReturnRequest.RequestedResolution.REPLACEMENT,
            total_requested_amount=Decimal("50000.00"),
            total_approved_amount=Decimal("50000.00"),
        )

    def get_api_client(self) -> APIClient:
        return cast(APIClient, self.client)

    def authenticate_admin(self):
        self.get_api_client().force_authenticate(user=self.admin_user)

    def authenticate_customer(self):
        self.get_api_client().force_authenticate(user=self.customer)

    def get_item(self, items, key, value):
        return next(item for item in items if item[key] == value)

    def test_anonymous_user_cannot_access_breakdown(self):
        url = reverse("analytics-breakdown")

        response = self.client.get(url)

        self.assertIn(
            response.status_code,
            [
                status.HTTP_401_UNAUTHORIZED,
                status.HTTP_403_FORBIDDEN,
            ],
        )

    def test_customer_cannot_access_breakdown(self):
        self.authenticate_customer()

        url = reverse("analytics-breakdown")

        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_admin_can_access_breakdown(self):
        self.authenticate_admin()

        url = reverse("analytics-breakdown")

        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()

        self.assertIn("filters", data)
        self.assertIn("orders_by_status", data)
        self.assertIn("payments_by_provider", data)
        self.assertIn("revenue_by_category", data)
        self.assertIn("top_selling_products", data)
        self.assertIn("reviews_by_status", data)
        self.assertIn("support_by_category", data)
        self.assertIn("returns_by_reason", data)

    def test_orders_by_status_breakdown(self):
        self.authenticate_admin()

        url = reverse("analytics-breakdown")

        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        orders_by_status = response.json()["orders_by_status"]

        paid_row = self.get_item(
            orders_by_status,
            "status",
            Order.StatusChoices.PAID,
        )
        pending_row = self.get_item(
            orders_by_status,
            "status",
            Order.StatusChoices.PENDING_PAYMENT,
        )
        cancelled_row = self.get_item(
            orders_by_status,
            "status",
            Order.StatusChoices.CANCELLED,
        )

        self.assertEqual(paid_row["count"], 1)
        self.assertEqual(pending_row["count"], 1)
        self.assertEqual(cancelled_row["count"], 1)

    def test_payments_by_provider_breakdown(self):
        self.authenticate_admin()

        url = reverse("analytics-breakdown")

        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        payments_by_provider = response.json()["payments_by_provider"]

        mock_row = self.get_item(
            payments_by_provider,
            "provider",
            Payment.ProviderChoices.MOCK,
        )
        stripe_row = self.get_item(
            payments_by_provider,
            "provider",
            Payment.ProviderChoices.STRIPE,
        )

        self.assertEqual(mock_row["count"], 1)
        self.assertEqual(mock_row["success_count"], 1)
        self.assertEqual(mock_row["total_amount"], "500000.00")

        self.assertEqual(stripe_row["count"], 1)
        self.assertEqual(stripe_row["success_count"], 0)
        self.assertEqual(stripe_row["total_amount"], "50000.00")

    def test_revenue_by_category_breakdown(self):
        self.authenticate_admin()

        url = reverse("analytics-breakdown")

        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        revenue_by_category = response.json()["revenue_by_category"]

        phone_row = self.get_item(
            revenue_by_category,
            "category_id",
            self.phone_category.id,
        )
        laptop_row = self.get_item(
            revenue_by_category,
            "category_id",
            self.laptop_category.id,
        )

        self.assertEqual(phone_row["category_name"], "Phones")
        self.assertEqual(phone_row["revenue"], "200000.00")
        self.assertEqual(phone_row["quantity_sold"], 2)
        self.assertEqual(phone_row["orders_count"], 1)

        self.assertEqual(laptop_row["category_name"], "Laptops")
        self.assertEqual(laptop_row["revenue"], "300000.00")
        self.assertEqual(laptop_row["quantity_sold"], 1)
        self.assertEqual(laptop_row["orders_count"], 1)

    def test_top_selling_products_breakdown(self):
        self.authenticate_admin()

        url = reverse("analytics-breakdown")

        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        top_products = response.json()["top_selling_products"]

        phone_row = self.get_item(
            top_products,
            "product_id",
            self.phone_product.id,
        )
        laptop_row = self.get_item(
            top_products,
            "product_id",
            self.laptop_product.id,
        )

        self.assertEqual(phone_row["name"], "Analytics Phone")
        self.assertEqual(phone_row["sku"], "BREAKDOWN-PHONE-001")
        self.assertEqual(phone_row["category_name"], "Phones")
        self.assertEqual(phone_row["quantity_sold"], 2)
        self.assertEqual(phone_row["revenue"], "200000.00")
        self.assertEqual(phone_row["orders_count"], 1)

        self.assertEqual(laptop_row["name"], "Analytics Laptop")
        self.assertEqual(laptop_row["sku"], "BREAKDOWN-LAPTOP-001")
        self.assertEqual(laptop_row["category_name"], "Laptops")
        self.assertEqual(laptop_row["quantity_sold"], 1)
        self.assertEqual(laptop_row["revenue"], "300000.00")
        self.assertEqual(laptop_row["orders_count"], 1)

    def test_review_support_and_return_breakdowns(self):
        self.authenticate_admin()

        url = reverse("analytics-breakdown")

        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()

        approved_review_row = self.get_item(
            data["reviews_by_status"],
            "status",
            ProductReview.StatusChoices.APPROVED,
        )
        pending_review_row = self.get_item(
            data["reviews_by_status"],
            "status",
            ProductReview.StatusChoices.PENDING,
        )

        self.assertEqual(approved_review_row["count"], 1)
        self.assertEqual(pending_review_row["count"], 1)

        order_support_row = self.get_item(
            data["support_by_category"],
            "category",
            SupportTicket.CategoryChoices.ORDER,
        )
        payment_support_row = self.get_item(
            data["support_by_category"],
            "category",
            SupportTicket.CategoryChoices.PAYMENT,
        )

        self.assertEqual(order_support_row["count"], 1)
        self.assertEqual(order_support_row["open_count"], 1)
        self.assertEqual(order_support_row["urgent_count"], 1)

        self.assertEqual(payment_support_row["count"], 1)
        self.assertEqual(payment_support_row["open_count"], 0)
        self.assertEqual(payment_support_row["urgent_count"], 0)

        damaged_return_row = self.get_item(
            data["returns_by_reason"],
            "reason",
            ReturnRequest.Reason.DAMAGED,
        )
        wrong_item_return_row = self.get_item(
            data["returns_by_reason"],
            "reason",
            ReturnRequest.Reason.WRONG_ITEM,
        )

        self.assertEqual(damaged_return_row["count"], 1)
        self.assertEqual(damaged_return_row["requested_amount"], "100000.00")
        self.assertEqual(damaged_return_row["approved_amount"], "0.00")

        self.assertEqual(wrong_item_return_row["count"], 1)
        self.assertEqual(wrong_item_return_row["requested_amount"], "50000.00")
        self.assertEqual(wrong_item_return_row["approved_amount"], "50000.00")

    def test_breakdown_limit_is_applied(self):
        self.authenticate_admin()

        url = reverse("analytics-breakdown")

        response = self.client.get(
            url,
            data={
                "limit": 1,
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()

        self.assertEqual(data["filters"]["limit"], 1)
        self.assertEqual(len(data["revenue_by_category"]), 1)
        self.assertEqual(len(data["top_selling_products"]), 1)

    def test_breakdown_period_filter_excludes_old_data(self):
        self.authenticate_admin()

        old_order = self.create_test_order(
            user=self.customer,
            status_value=Order.StatusChoices.PAID,
            payment_status=Order.PaymentStatusChoices.PAID,
            subtotal="900000",
        )

        old_item = OrderItem.objects.create(
            order=old_order,
            product=self.phone_product,
            product_name=self.phone_product.name,
            product_sku=self.phone_product.sku,
            quantity=9,
            unit_price=Decimal("100000"),
            total_price=Decimal("900000"),
        )

        old_payment = self.create_test_payment(
            order=old_order,
            user=self.customer,
            provider=Payment.ProviderChoices.MOCK,
            status_value=Payment.StatusChoices.SUCCESS,
            amount="900000",
        )

        old_datetime = timezone.now() - timedelta(days=90)

        Order.objects.filter(pk=old_order.pk).update(created_at=old_datetime)
        OrderItem.objects.filter(pk=old_item.pk).update(created_at=old_datetime)
        Payment.objects.filter(pk=old_payment.pk).update(created_at=old_datetime)

        url = reverse("analytics-breakdown")

        month_response = self.client.get(
            url,
            data={
                "period": "month",
            },
        )

        self.assertEqual(month_response.status_code, status.HTTP_200_OK)

        month_data = month_response.json()

        phone_row_month = self.get_item(
            month_data["revenue_by_category"],
            "category_id",
            self.phone_category.id,
        )

        self.assertEqual(phone_row_month["revenue"], "200000.00")
        self.assertEqual(phone_row_month["quantity_sold"], 2)

        all_response = self.client.get(
            url,
            data={
                "period": "all",
            },
        )

        self.assertEqual(all_response.status_code, status.HTTP_200_OK)

        all_data = all_response.json()

        phone_row_all = self.get_item(
            all_data["revenue_by_category"],
            "category_id",
            self.phone_category.id,
        )

        self.assertEqual(phone_row_all["revenue"], "1100000.00")
        self.assertEqual(phone_row_all["quantity_sold"], 11)

    def test_breakdown_custom_date_range_filter(self):
        self.authenticate_admin()

        today = timezone.now().date()
        url = reverse("analytics-breakdown")

        response = self.client.get(
            url,
            data={
                "start_date": today.isoformat(),
                "end_date": today.isoformat(),
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()

        self.assertIsNotNone(data["filters"]["start_at"])
        self.assertIsNotNone(data["filters"]["end_at"])

        paid_order_row = self.get_item(
            data["orders_by_status"],
            "status",
            Order.StatusChoices.PAID,
        )

        self.assertEqual(paid_order_row["count"], 1)

    def test_breakdown_invalid_date_range_returns_error(self):
        self.authenticate_admin()

        today = timezone.now().date()
        yesterday = today - timedelta(days=1)
        url = reverse("analytics-breakdown")

        response = self.client.get(
            url,
            data={
                "start_date": today.isoformat(),
                "end_date": yesterday.isoformat(),
            },
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_breakdown_requires_both_start_and_end_date(self):
        self.authenticate_admin()

        today = timezone.now().date()
        url = reverse("analytics-breakdown")

        response = self.client.get(
            url,
            data={
                "start_date": today.isoformat(),
            },
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_breakdown_limit_validation(self):
        self.authenticate_admin()

        url = reverse("analytics-breakdown")

        response = self.client.get(
            url,
            data={
                "limit": 100,
            },
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)