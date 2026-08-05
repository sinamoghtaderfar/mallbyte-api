from decimal import Decimal
from typing import cast

from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from apps.accounts.models import User
from apps.content.models import Announcement, Banner, ContentPage
from apps.inventory.models import Stock, Warehouse
from apps.orders.models import Order
from apps.payments.models import Payment
from apps.products.models import Category, Product
from apps.returns.models import ReturnRequest
from apps.reviews.models import ProductReview
from apps.support.models import SupportTicket


class AnalyticsAlertsAPITests(APITestCase):
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
            address="Analytics alerts address",
            postal_code="1234567890",
        )

    def setUp(self):
        self.admin_user = self.create_test_user(
            phone="+989994000001",
            email="alerts_admin@example.com",
            full_name="Alerts Admin",
            is_staff=True,
            is_superuser=True,
        )

        self.customer = self.create_test_user(
            phone="+989994000002",
            email="alerts_customer@example.com",
            full_name="Alerts Customer",
        )

        self.seller = self.create_test_user(
            phone="+989994000003",
            email="alerts_seller@example.com",
            full_name="Alerts Seller",
            is_seller=True,
        )

        self.category = Category.objects.create(
            name="Alerts Category",
            slug="alerts-category",
        )

        self.low_stock_product = Product.objects.create(
            seller=self.seller,
            category=self.category,
            name="Low Stock Product",
            slug="low-stock-product",
            description="Low stock product description.",
            price=Decimal("100000"),
            sku="ALERT-LOW-001",
            status=Product.StatusChoices.APPROVED,
            is_active=True,
        )

        self.out_of_stock_product = Product.objects.create(
            seller=self.seller,
            category=self.category,
            name="Out Of Stock Product",
            slug="out-of-stock-product",
            description="Out of stock product description.",
            price=Decimal("200000"),
            sku="ALERT-OUT-001",
            status=Product.StatusChoices.APPROVED,
            is_active=True,
        )

        self.normal_stock_product = Product.objects.create(
            seller=self.seller,
            category=self.category,
            name="Normal Stock Product",
            slug="normal-stock-product",
            description="Normal stock product description.",
            price=Decimal("300000"),
            sku="ALERT-NORMAL-001",
            status=Product.StatusChoices.APPROVED,
            is_active=True,
        )

        self.warehouse = Warehouse.objects.create(
            name="Alerts Warehouse",
            code="ALW",
            type=Warehouse.TypeChoices.MAIN,
            province="Tehran",
            city="Tehran",
            address="Alerts warehouse address",
            postal_code="1234567890",
            phone="02100000000",
            email="alerts-warehouse@example.com",
            manager_name="Alerts Manager",
            manager_phone="09120000000",
            is_active=True,
            created_by=self.admin_user,
        )

        Stock.objects.create(
            product=self.low_stock_product,
            warehouse=self.warehouse,
            quantity=4,
            reserved_quantity=0,
            low_stock_threshold=5,
            updated_by=self.admin_user,
        )

        Stock.objects.create(
            product=self.out_of_stock_product,
            warehouse=self.warehouse,
            quantity=0,
            reserved_quantity=0,
            low_stock_threshold=5,
            updated_by=self.admin_user,
        )

        Stock.objects.create(
            product=self.normal_stock_product,
            warehouse=self.warehouse,
            quantity=20,
            reserved_quantity=2,
            low_stock_threshold=5,
            updated_by=self.admin_user,
        )

        self.pending_payment_order = self.create_test_order(
            user=self.customer,
            status_value=Order.StatusChoices.PENDING_PAYMENT,
            payment_status=Order.PaymentStatusChoices.UNPAID,
            subtotal="150000",
        )

        self.paid_order = self.create_test_order(
            user=self.customer,
            status_value=Order.StatusChoices.PAID,
            payment_status=Order.PaymentStatusChoices.PAID,
            subtotal="200000",
        )

        self.failed_payment = Payment.objects.create(
            order=self.pending_payment_order,
            user=self.customer,
            provider=Payment.ProviderChoices.MOCK,
            status=Payment.StatusChoices.FAILED,
            amount=Decimal("150000"),
            currency="IRR",
            failure_reason="Payment gateway failed.",
            created_by=self.admin_user,
        )

        ProductReview.objects.create(
            customer=self.customer,
            product=self.low_stock_product,
            rating=3,
            title="Pending product review",
            comment="This review needs moderation.",
            status=ProductReview.StatusChoices.PENDING,
            is_verified_purchase=False,
        )

        self.urgent_ticket = SupportTicket.objects.create(
            customer=self.customer,
            assigned_to=self.admin_user,
            subject="Urgent order issue",
            category=SupportTicket.CategoryChoices.ORDER,
            priority=SupportTicket.PriorityChoices.URGENT,
            status=SupportTicket.StatusChoices.OPEN,
        )

        self.unassigned_ticket = SupportTicket.objects.create(
            customer=self.customer,
            subject="Unassigned payment issue",
            category=SupportTicket.CategoryChoices.PAYMENT,
            priority=SupportTicket.PriorityChoices.HIGH,
            status=SupportTicket.StatusChoices.PENDING,
        )

        self.pending_return = ReturnRequest.objects.create(
            customer=self.customer,
            order=self.paid_order,
            status=ReturnRequest.Status.SUBMITTED,
            reason=ReturnRequest.Reason.DAMAGED,
            requested_resolution=ReturnRequest.RequestedResolution.REFUND,
            total_requested_amount=Decimal("50000.00"),
            total_approved_amount=Decimal("0.00"),
        )

        ContentPage.objects.create(
            title="Draft Alerts Page",
            slug="draft-alerts-page",
            page_type=ContentPage.PageTypeChoices.CUSTOM,
            content="Draft alerts page content.",
            status=ContentPage.StatusChoices.DRAFT,
            created_by=self.admin_user,
            updated_by=self.admin_user,
        )

        Banner.objects.create(
            title="Draft Alerts Banner",
            subtitle="Draft banner subtitle.",
            image=SimpleUploadedFile(
                "draft-alerts-banner.jpg",
                b"fake-image-content",
                content_type="image/jpeg",
            ),
            placement=Banner.PlacementChoices.HOME_HERO,
            status=Banner.StatusChoices.DRAFT,
        )

        Announcement.objects.create(
            title="Draft Alerts Announcement",
            message="Draft announcement message.",
            level=Announcement.LevelChoices.INFO,
            placement=Announcement.PlacementChoices.GLOBAL,
            status=Announcement.StatusChoices.DRAFT,
        )

    def get_api_client(self) -> APIClient:
        return cast(APIClient, self.client)

    def authenticate_admin(self):
        self.get_api_client().force_authenticate(user=self.admin_user)

    def authenticate_customer(self):
        self.get_api_client().force_authenticate(user=self.customer)

    def get_card(self, cards, key):
        return next(card for card in cards if card["key"] == key)

    def test_anonymous_user_cannot_access_alerts(self):
        url = reverse("analytics-alerts")

        response = self.client.get(url)

        self.assertIn(
            response.status_code,
            [
                status.HTTP_401_UNAUTHORIZED,
                status.HTTP_403_FORBIDDEN,
            ],
        )

    def test_customer_cannot_access_alerts(self):
        self.authenticate_customer()

        url = reverse("analytics-alerts")

        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_admin_can_access_alerts(self):
        self.authenticate_admin()

        url = reverse("analytics-alerts")

        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()

        self.assertIn("generated_at", data)
        self.assertIn("cards", data)
        self.assertIn("inventory", data)
        self.assertIn("orders", data)
        self.assertIn("payments", data)
        self.assertIn("reviews", data)
        self.assertIn("support", data)
        self.assertIn("returns", data)
        self.assertIn("content", data)

    def test_alert_cards_have_correct_values_and_severity(self):
        self.authenticate_admin()

        url = reverse("analytics-alerts")

        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        cards = response.json()["cards"]

        out_of_stock_card = self.get_card(cards, "out_of_stock_items")
        low_stock_card = self.get_card(cards, "low_stock_items")
        failed_payments_card = self.get_card(cards, "failed_payments")
        pending_orders_card = self.get_card(cards, "pending_payment_orders")
        pending_reviews_card = self.get_card(cards, "pending_reviews")
        urgent_support_card = self.get_card(cards, "urgent_support_tickets")
        unassigned_support_card = self.get_card(cards, "unassigned_support_tickets")
        pending_returns_card = self.get_card(cards, "pending_returns")
        draft_content_card = self.get_card(cards, "draft_content")

        self.assertEqual(out_of_stock_card["value"], 1)
        self.assertEqual(out_of_stock_card["severity"], "critical")

        self.assertEqual(low_stock_card["value"], 1)
        self.assertEqual(low_stock_card["severity"], "warning")

        self.assertEqual(failed_payments_card["value"], 1)
        self.assertEqual(failed_payments_card["severity"], "warning")

        self.assertEqual(pending_orders_card["value"], 1)
        self.assertEqual(pending_orders_card["severity"], "warning")

        self.assertEqual(pending_reviews_card["value"], 1)
        self.assertEqual(pending_reviews_card["severity"], "info")

        self.assertEqual(urgent_support_card["value"], 1)
        self.assertEqual(urgent_support_card["severity"], "critical")

        self.assertEqual(unassigned_support_card["value"], 1)
        self.assertEqual(unassigned_support_card["severity"], "warning")

        self.assertEqual(pending_returns_card["value"], 1)
        self.assertEqual(pending_returns_card["severity"], "warning")

        self.assertEqual(draft_content_card["value"], 3)
        self.assertEqual(draft_content_card["severity"], "info")

    def test_inventory_alert_records_are_returned(self):
        self.authenticate_admin()

        url = reverse("analytics-alerts")

        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()

        low_stock_items = data["inventory"]["low_stock"]
        out_of_stock_items = data["inventory"]["out_of_stock"]

        self.assertEqual(len(low_stock_items), 1)
        self.assertEqual(len(out_of_stock_items), 1)

        low_stock_item = low_stock_items[0]
        out_of_stock_item = out_of_stock_items[0]

        self.assertEqual(low_stock_item["product_id"], self.low_stock_product.id)
        self.assertEqual(low_stock_item["product_name"], "Low Stock Product")
        self.assertEqual(low_stock_item["sku"], "ALERT-LOW-001")
        self.assertEqual(low_stock_item["quantity"], 4)
        self.assertEqual(low_stock_item["reserved_quantity"], 0)
        self.assertEqual(low_stock_item["available_quantity"], 4)
        self.assertEqual(low_stock_item["low_stock_threshold"], 5)

        self.assertEqual(out_of_stock_item["product_id"], self.out_of_stock_product.id)
        self.assertEqual(out_of_stock_item["product_name"], "Out Of Stock Product")
        self.assertEqual(out_of_stock_item["available_quantity"], 0)

    def test_order_payment_review_support_return_and_content_records_are_returned(self):
        self.authenticate_admin()

        url = reverse("analytics-alerts")

        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()

        pending_orders = data["orders"]["pending_payment_orders"]
        failed_payments = data["payments"]["failed_payments"]
        pending_reviews = data["reviews"]["pending_reviews"]
        urgent_tickets = data["support"]["urgent_tickets"]
        unassigned_tickets = data["support"]["unassigned_tickets"]
        pending_returns = data["returns"]["pending_returns"]
        content = data["content"]

        self.assertEqual(len(pending_orders), 1)
        self.assertEqual(pending_orders[0]["id"], self.pending_payment_order.id)
        self.assertEqual(pending_orders[0]["total_amount"], "150000.00")

        self.assertEqual(len(failed_payments), 1)
        self.assertEqual(failed_payments[0]["id"], self.failed_payment.id)
        self.assertEqual(failed_payments[0]["amount"], "150000.00")
        self.assertEqual(failed_payments[0]["provider"], Payment.ProviderChoices.MOCK)
        self.assertEqual(
            failed_payments[0]["failure_reason"],
            "Payment gateway failed.",
        )

        self.assertEqual(len(pending_reviews), 1)
        self.assertEqual(pending_reviews[0]["product_id"], self.low_stock_product.id)
        self.assertEqual(pending_reviews[0]["product_name"], "Low Stock Product")
        self.assertEqual(pending_reviews[0]["rating"], 3)
        self.assertEqual(pending_reviews[0]["title"], "Pending product review")

        self.assertEqual(len(urgent_tickets), 1)
        self.assertEqual(urgent_tickets[0]["id"], self.urgent_ticket.id)
        self.assertEqual(urgent_tickets[0]["priority"], SupportTicket.PriorityChoices.URGENT)
        self.assertEqual(urgent_tickets[0]["status"], SupportTicket.StatusChoices.OPEN)

        self.assertEqual(len(unassigned_tickets), 1)
        self.assertEqual(unassigned_tickets[0]["id"], self.unassigned_ticket.id)
        self.assertEqual(unassigned_tickets[0]["priority"], SupportTicket.PriorityChoices.HIGH)
        self.assertEqual(unassigned_tickets[0]["status"], SupportTicket.StatusChoices.PENDING)

        self.assertEqual(len(pending_returns), 1)
        self.assertEqual(pending_returns[0]["id"], self.pending_return.id)
        self.assertEqual(pending_returns[0]["status"], ReturnRequest.Status.SUBMITTED)
        self.assertEqual(pending_returns[0]["reason"], ReturnRequest.Reason.DAMAGED)
        self.assertEqual(pending_returns[0]["requested_amount"], "50000.00")

        self.assertEqual(content["draft_pages"], 1)
        self.assertEqual(content["draft_banners"], 1)
        self.assertEqual(content["draft_announcements"], 1)

    def test_alerts_limit_is_applied_to_record_lists(self):
        self.authenticate_admin()

        second_pending_order = self.create_test_order(
            user=self.customer,
            status_value=Order.StatusChoices.PENDING_PAYMENT,
            payment_status=Order.PaymentStatusChoices.UNPAID,
            subtotal="90000",
        )

        Payment.objects.create(
            order=second_pending_order,
            user=self.customer,
            provider=Payment.ProviderChoices.STRIPE,
            status=Payment.StatusChoices.FAILED,
            amount=Decimal("90000"),
            currency="IRR",
            failure_reason="Second failed payment.",
            created_by=self.admin_user,
        )

        url = reverse("analytics-alerts")

        response = self.client.get(
            url,
            data={
                "limit": 1,
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()

        failed_payments_card = self.get_card(data["cards"], "failed_payments")
        pending_orders_card = self.get_card(data["cards"], "pending_payment_orders")

        self.assertEqual(failed_payments_card["value"], 2)
        self.assertEqual(pending_orders_card["value"], 2)

        self.assertEqual(len(data["payments"]["failed_payments"]), 1)
        self.assertEqual(len(data["orders"]["pending_payment_orders"]), 1)

    def test_alerts_limit_validation(self):
        self.authenticate_admin()

        url = reverse("analytics-alerts")

        response = self.client.get(
            url,
            data={
                "limit": 100,
            },
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)