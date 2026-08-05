import csv
import io
from datetime import timedelta
from decimal import Decimal
from typing import cast

from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from apps.accounts.models import User
from apps.inventory.models import Stock, Warehouse
from apps.orders.models import Order
from apps.payments.models import Payment
from apps.products.models import Category, Product
from apps.returns.models import ReturnRequest
from apps.reviews.models import ProductReview
from apps.support.models import SupportTicket


class AnalyticsExportAPITests(APITestCase):
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
            address="Analytics export address",
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
        failure_reason="",
    ):
        return Payment.objects.create(
            order=order,
            user=user,
            provider=provider,
            status=status_value,
            amount=Decimal(str(amount)),
            currency="IRR",
            failure_reason=failure_reason,
            paid_at=timezone.now()
            if status_value == Payment.StatusChoices.SUCCESS
            else None,
            failed_at=timezone.now()
            if status_value == Payment.StatusChoices.FAILED
            else None,
            created_by=self.admin_user,
        )

    def setUp(self):
        self.admin_user = self.create_test_user(
            phone="+989995000001",
            email="export_admin@example.com",
            full_name="Export Admin",
            is_staff=True,
            is_superuser=True,
        )

        self.customer = self.create_test_user(
            phone="+989995000002",
            email="export_customer@example.com",
            full_name="Export Customer",
        )

        self.seller = self.create_test_user(
            phone="+989995000003",
            email="export_seller@example.com",
            full_name="Export Seller",
            is_seller=True,
        )

        self.category = Category.objects.create(
            name="Export Category",
            slug="export-category",
        )

        self.product = Product.objects.create(
            seller=self.seller,
            category=self.category,
            name="Export Product",
            slug="export-product",
            description="Export product description.",
            price=Decimal("100000"),
            sku="EXPORT-PROD-001",
            status=Product.StatusChoices.APPROVED,
            is_active=True,
            is_featured=True,
        )

        self.warehouse = Warehouse.objects.create(
            name="Export Warehouse",
            code="EXW",
            type=Warehouse.TypeChoices.MAIN,
            province="Tehran",
            city="Tehran",
            address="Export warehouse address",
            postal_code="1234567890",
            phone="02100000000",
            email="export-warehouse@example.com",
            manager_name="Export Manager",
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

        self.paid_order = self.create_test_order(
            user=self.customer,
            status_value=Order.StatusChoices.PAID,
            payment_status=Order.PaymentStatusChoices.PAID,
            subtotal="200000",
        )

        self.pending_order = self.create_test_order(
            user=self.customer,
            status_value=Order.StatusChoices.PENDING_PAYMENT,
            payment_status=Order.PaymentStatusChoices.UNPAID,
            subtotal="50000",
        )

        self.old_paid_order = self.create_test_order(
            user=self.customer,
            status_value=Order.StatusChoices.PAID,
            payment_status=Order.PaymentStatusChoices.PAID,
            subtotal="900000",
        )

        self.success_payment = self.create_test_payment(
            order=self.paid_order,
            user=self.customer,
            provider=Payment.ProviderChoices.MOCK,
            status_value=Payment.StatusChoices.SUCCESS,
            amount="200000",
        )

        self.failed_payment = self.create_test_payment(
            order=self.pending_order,
            user=self.customer,
            provider=Payment.ProviderChoices.STRIPE,
            status_value=Payment.StatusChoices.FAILED,
            amount="50000",
            failure_reason="Export payment failed.",
        )

        self.old_success_payment = self.create_test_payment(
            order=self.old_paid_order,
            user=self.customer,
            provider=Payment.ProviderChoices.MOCK,
            status_value=Payment.StatusChoices.SUCCESS,
            amount="900000",
        )

        old_datetime = timezone.now() - timedelta(days=90)

        Order.objects.filter(pk=self.old_paid_order.pk).update(
            created_at=old_datetime
        )
        Payment.objects.filter(pk=self.old_success_payment.pk).update(
            created_at=old_datetime
        )

        self.ticket = SupportTicket.objects.create(
            customer=self.customer,
            assigned_to=self.admin_user,
            subject="Export support ticket",
            category=SupportTicket.CategoryChoices.ORDER,
            priority=SupportTicket.PriorityChoices.URGENT,
            status=SupportTicket.StatusChoices.OPEN,
            order=self.paid_order,
            product=self.product,
        )

        self.return_request = ReturnRequest.objects.create(
            customer=self.customer,
            order=self.paid_order,
            status=ReturnRequest.Status.SUBMITTED,
            reason=ReturnRequest.Reason.DAMAGED,
            requested_resolution=ReturnRequest.RequestedResolution.REFUND,
            total_requested_amount=Decimal("50000.00"),
            total_approved_amount=Decimal("0.00"),
        )

        self.review = ProductReview.objects.create(
            customer=self.customer,
            product=self.product,
            rating=5,
            title='=HYPERLINK("bad")',
            comment="Review export comment.",
            status=ProductReview.StatusChoices.APPROVED,
            is_verified_purchase=True,
            helpful_count=2,
            not_helpful_count=1,
            approved_by=self.admin_user,
            approved_at=timezone.now(),
        )

    def get_api_client(self) -> APIClient:
        return cast(APIClient, self.client)

    def authenticate_admin(self):
        self.get_api_client().force_authenticate(user=self.admin_user)

    def authenticate_customer(self):
        self.get_api_client().force_authenticate(user=self.customer)

    def read_csv_response(self, response):
        decoded_content = response.content.decode("utf-8")
        return list(csv.reader(io.StringIO(decoded_content)))

    def test_anonymous_user_cannot_access_export(self):
        url = reverse("analytics-export")

        response = self.client.get(url)

        self.assertIn(
            response.status_code,
            [
                status.HTTP_401_UNAUTHORIZED,
                status.HTTP_403_FORBIDDEN,
            ],
        )

    def test_customer_cannot_access_export(self):
        self.authenticate_customer()

        url = reverse("analytics-export")

        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_admin_can_export_default_sales_csv(self):
        self.authenticate_admin()

        url = reverse("analytics-export")

        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("text/csv", response["Content-Type"])
        self.assertIn(
            'attachment; filename="analytics_sales_export.csv"',
            response["Content-Disposition"],
        )

        rows = self.read_csv_response(response)

        self.assertEqual(
            rows[0],
            [
                "payment_number",
                "order_number",
                "customer_id",
                "customer_phone",
                "provider",
                "amount",
                "currency",
                "paid_at",
                "created_at",
            ],
        )

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1][0], self.success_payment.payment_number)
        self.assertEqual(rows[1][1], self.paid_order.order_number)
        self.assertEqual(rows[1][4], Payment.ProviderChoices.MOCK)
        self.assertEqual(rows[1][5], "200000.00")

    def test_orders_export_csv(self):
        self.authenticate_admin()

        url = reverse("analytics-export")

        response = self.client.get(
            url,
            data={
                "report": "orders",
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn(
            'attachment; filename="analytics_orders_export.csv"',
            response["Content-Disposition"],
        )

        rows = self.read_csv_response(response)
        headers = rows[0]
        data_rows = rows[1:]

        order_numbers = {row[headers.index("order_number")] for row in data_rows}

        self.assertIn(self.paid_order.order_number, order_numbers)
        self.assertIn(self.pending_order.order_number, order_numbers)
        self.assertNotIn(self.old_paid_order.order_number, order_numbers)

    def test_payments_export_csv(self):
        self.authenticate_admin()

        url = reverse("analytics-export")

        response = self.client.get(
            url,
            data={
                "report": "payments",
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn(
            'attachment; filename="analytics_payments_export.csv"',
            response["Content-Disposition"],
        )

        rows = self.read_csv_response(response)
        headers = rows[0]
        data_rows = rows[1:]

        payment_numbers = {
            row[headers.index("payment_number")]
            for row in data_rows
        }

        payment_statuses = {
            row[headers.index("status")]
            for row in data_rows
        }

        self.assertIn(self.success_payment.payment_number, payment_numbers)
        self.assertIn(self.failed_payment.payment_number, payment_numbers)
        self.assertNotIn(self.old_success_payment.payment_number, payment_numbers)

        self.assertIn(Payment.StatusChoices.SUCCESS, payment_statuses)
        self.assertIn(Payment.StatusChoices.FAILED, payment_statuses)

    def test_products_export_csv(self):
        self.authenticate_admin()

        url = reverse("analytics-export")

        response = self.client.get(
            url,
            data={
                "report": "products",
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn(
            'attachment; filename="analytics_products_export.csv"',
            response["Content-Disposition"],
        )

        rows = self.read_csv_response(response)
        headers = rows[0]
        product_row = rows[1]

        self.assertEqual(product_row[headers.index("name")], "Export Product")
        self.assertEqual(product_row[headers.index("sku")], "EXPORT-PROD-001")
        self.assertEqual(product_row[headers.index("category")], "Export Category")
        self.assertEqual(product_row[headers.index("price")], "100000.00")
        self.assertEqual(product_row[headers.index("total_stock")], "10")
        self.assertEqual(product_row[headers.index("reserved_stock")], "2")
        self.assertEqual(product_row[headers.index("available_stock")], "8")

    def test_support_export_csv(self):
        self.authenticate_admin()

        url = reverse("analytics-export")

        response = self.client.get(
            url,
            data={
                "report": "support",
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn(
            'attachment; filename="analytics_support_export.csv"',
            response["Content-Disposition"],
        )

        rows = self.read_csv_response(response)
        headers = rows[0]
        ticket_row = rows[1]

        self.assertEqual(
            ticket_row[headers.index("ticket_number")],
            self.ticket.ticket_number,
        )
        self.assertEqual(
            ticket_row[headers.index("subject")],
            "Export support ticket",
        )
        self.assertEqual(
            ticket_row[headers.index("priority")],
            SupportTicket.PriorityChoices.URGENT,
        )
        self.assertEqual(
            ticket_row[headers.index("status")],
            SupportTicket.StatusChoices.OPEN,
        )

    def test_returns_export_csv(self):
        self.authenticate_admin()

        url = reverse("analytics-export")

        response = self.client.get(
            url,
            data={
                "report": "returns",
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn(
            'attachment; filename="analytics_returns_export.csv"',
            response["Content-Disposition"],
        )

        rows = self.read_csv_response(response)
        headers = rows[0]
        return_row = rows[1]

        self.assertEqual(
            return_row[headers.index("request_number")],
            self.return_request.request_number,
        )
        self.assertEqual(
            return_row[headers.index("status")],
            ReturnRequest.Status.SUBMITTED,
        )
        self.assertEqual(
            return_row[headers.index("reason")],
            ReturnRequest.Reason.DAMAGED,
        )
        self.assertEqual(
            return_row[headers.index("total_requested_amount")],
            "50000.00",
        )

    def test_reviews_export_csv_and_prevents_csv_injection(self):
        self.authenticate_admin()

        url = reverse("analytics-export")

        response = self.client.get(
            url,
            data={
                "report": "reviews",
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn(
            'attachment; filename="analytics_reviews_export.csv"',
            response["Content-Disposition"],
        )

        rows = self.read_csv_response(response)
        headers = rows[0]
        review_row = rows[1]

        self.assertEqual(
            review_row[headers.index("review_id")],
            str(self.review.id),
        )
        self.assertEqual(
            review_row[headers.index("product_name")],
            "Export Product",
        )
        self.assertEqual(
            review_row[headers.index("rating")],
            "5",
        )
        self.assertEqual(
            review_row[headers.index("title")],
            '\'=HYPERLINK("bad")',
        )

    def test_export_custom_date_range(self):
        self.authenticate_admin()

        today = timezone.now().date()
        url = reverse("analytics-export")

        response = self.client.get(
            url,
            data={
                "report": "sales",
                "start_date": today.isoformat(),
                "end_date": today.isoformat(),
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        rows = self.read_csv_response(response)
        payment_numbers = {row[0] for row in rows[1:]}

        self.assertIn(self.success_payment.payment_number, payment_numbers)
        self.assertNotIn(self.old_success_payment.payment_number, payment_numbers)

    def test_export_all_period_includes_old_data(self):
        self.authenticate_admin()

        url = reverse("analytics-export")

        response = self.client.get(
            url,
            data={
                "report": "sales",
                "period": "all",
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        rows = self.read_csv_response(response)
        payment_numbers = {row[0] for row in rows[1:]}

        self.assertIn(self.success_payment.payment_number, payment_numbers)
        self.assertIn(self.old_success_payment.payment_number, payment_numbers)

    def test_export_invalid_report_returns_error(self):
        self.authenticate_admin()

        url = reverse("analytics-export")

        response = self.client.get(
            url,
            data={
                "report": "invalid_report",
            },
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_export_invalid_date_range_returns_error(self):
        self.authenticate_admin()

        today = timezone.now().date()
        yesterday = today - timedelta(days=1)
        url = reverse("analytics-export")

        response = self.client.get(
            url,
            data={
                "report": "sales",
                "start_date": today.isoformat(),
                "end_date": yesterday.isoformat(),
            },
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_export_requires_both_start_and_end_date(self):
        self.authenticate_admin()

        today = timezone.now().date()
        url = reverse("analytics-export")

        response = self.client.get(
            url,
            data={
                "report": "sales",
                "start_date": today.isoformat(),
            },
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)