from decimal import Decimal

from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from apps.accounts.models import User
from apps.orders.models import Order, OrderItem
from apps.products.models import Category, Product
from apps.returns.models import ReturnItem, ReturnRequest, ReturnStatusHistory


class ReturnsFlowTests(APITestCase):
    def setUp(self):
        self.admin_user = User.objects.create_superuser(
            phone="+989100000001",
            email="admin_returns@example.com",
            full_name="Returns Admin",
            password="testpass123",
        )

        self.customer = User.objects.create_user(
            phone="+989100000002",
            email="customer_returns@example.com",
            full_name="Returns Customer",
            password="testpass123",
        )

        self.other_customer = User.objects.create_user(
            phone="+989100000003",
            email="other_returns@example.com",
            full_name="Other Customer",
            password="testpass123",
        )

        self.category = Category.objects.create(
            name="Returns Test Category",
            description="Test category",
            is_active=True,
        )

        self.product = Product.objects.create(
            seller=self.admin_user,
            category=self.category,
            name="Returns Test Product",
            description="Product for returns tests",
            price=Decimal("100000"),
            status=Product.StatusChoices.APPROVED,
            is_active=True,
            sku="RETURNS-SKU-001",
        )

        self.order = Order.objects.create(
            user=self.customer,
            status=Order.StatusChoices.DELIVERED,
            payment_status=Order.PaymentStatusChoices.PAID,
            subtotal=Decimal("200000"),
            discount_amount=Decimal("0"),
            shipping_cost=Decimal("0"),
            tax_amount=Decimal("0"),
            receiver_name="Returns Customer",
            receiver_phone="+989100000002",
            province="Tehran",
            city="Tehran",
            address="Test address",
            postal_code="1234567890",
        )

        self.order_item = OrderItem.objects.create(
            order=self.order,
            product=self.product,
            quantity=2,
            unit_price=Decimal("100000"),
            total_price=Decimal("200000"),
        )

    def authenticate_customer(self):
        self.client.force_authenticate(user=self.customer)

    def authenticate_admin(self):
        self.client.force_authenticate(user=self.admin_user)

    def create_return_request(self):
        self.authenticate_customer()

        url = reverse("return-request-list")

        response = self.client.post(
            url,
            data={
                "order": self.order.id,
                "reason": ReturnRequest.Reason.DAMAGED,
                "requested_resolution": ReturnRequest.RequestedResolution.REFUND,
                "refund_method": ReturnRequest.RefundMethod.ORIGINAL_PAYMENT,
                "customer_note": "The product arrived damaged.",
                "items": [
                    {
                        "order_item": self.order_item.id,
                        "quantity": 1,
                        "reason": ReturnRequest.Reason.DAMAGED,
                        "condition": ReturnItem.ItemCondition.DAMAGED,
                        "customer_note": "Box was broken.",
                    }
                ],
            },
            format="json",
        )

        return response

    def test_customer_can_create_return_request_for_delivered_order(self):
        response = self.create_return_request()

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        return_request = ReturnRequest.objects.get(order=self.order)

        self.assertEqual(return_request.customer, self.customer)
        self.assertEqual(return_request.status, ReturnRequest.Status.SUBMITTED)
        self.assertEqual(return_request.total_requested_amount, Decimal("100000.00"))
        self.assertEqual(return_request.items.count(), 1)

        return_item = return_request.items.first()

        self.assertEqual(return_item.order_item, self.order_item)
        self.assertEqual(return_item.quantity, 1)
        self.assertEqual(return_item.requested_refund_amount, Decimal("100000.00"))

        self.assertTrue(
            ReturnStatusHistory.objects.filter(
                return_request=return_request,
                new_status=ReturnRequest.Status.SUBMITTED,
            ).exists()
        )

    def test_customer_cannot_create_return_for_non_delivered_order(self):
        self.order.status = Order.StatusChoices.PAID
        self.order.save(update_fields=["status", "total_amount", "updated_at"])

        response = self.create_return_request()

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(ReturnRequest.objects.count(), 0)

    def test_customer_cannot_return_more_than_order_item_quantity(self):
        self.authenticate_customer()

        url = reverse("return-request-list")

        response = self.client.post(
            url,
            data={
                "order": self.order.id,
                "reason": ReturnRequest.Reason.DAMAGED,
                "requested_resolution": ReturnRequest.RequestedResolution.REFUND,
                "refund_method": ReturnRequest.RefundMethod.ORIGINAL_PAYMENT,
                "items": [
                    {
                        "order_item": self.order_item.id,
                        "quantity": 3,
                        "reason": ReturnRequest.Reason.DAMAGED,
                        "condition": ReturnItem.ItemCondition.DAMAGED,
                    }
                ],
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(ReturnRequest.objects.count(), 0)

    def test_customer_can_cancel_submitted_return_request(self):
        response = self.create_return_request()
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        return_request = ReturnRequest.objects.get(order=self.order)

        url = reverse("return-request-cancel", args=[return_request.id])

        cancel_response = self.client.post(
            url,
            data={
                "note": "I changed my mind.",
            },
            format="json",
        )

        self.assertEqual(cancel_response.status_code, status.HTTP_200_OK)

        return_request.refresh_from_db()

        self.assertEqual(return_request.status, ReturnRequest.Status.CANCELLED)
        self.assertIsNotNone(return_request.closed_at)

        self.assertTrue(
            ReturnStatusHistory.objects.filter(
                return_request=return_request,
                new_status=ReturnRequest.Status.CANCELLED,
            ).exists()
        )

    def test_admin_can_approve_return_request(self):
        response = self.create_return_request()
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        return_request = ReturnRequest.objects.get(order=self.order)

        self.authenticate_admin()

        url = reverse("return-request-approve", args=[return_request.id])

        approve_response = self.client.post(
            url,
            data={
                "note": "Approved by admin.",
                "approved_amount": "100000.00",
            },
            format="json",
        )

        self.assertEqual(approve_response.status_code, status.HTTP_200_OK)

        return_request.refresh_from_db()

        self.assertEqual(return_request.status, ReturnRequest.Status.APPROVED)
        self.assertEqual(return_request.reviewed_by, self.admin_user)
        self.assertEqual(return_request.total_approved_amount, Decimal("100000.00"))

        return_item = return_request.items.first()
        return_item.refresh_from_db()

        self.assertEqual(return_item.status, ReturnItem.ItemStatus.APPROVED)
        self.assertEqual(return_item.approved_refund_amount, Decimal("100000.00"))

    def test_admin_can_mark_received_and_refunded(self):
        response = self.create_return_request()
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        return_request = ReturnRequest.objects.get(order=self.order)

        self.authenticate_admin()

        approve_url = reverse("return-request-approve", args=[return_request.id])
        approve_response = self.client.post(
            approve_url,
            data={
                "note": "Approved.",
            },
            format="json",
        )
        self.assertEqual(approve_response.status_code, status.HTTP_200_OK)

        received_url = reverse("return-request-mark-received", args=[return_request.id])
        received_response = self.client.post(
            received_url,
            data={
                "note": "Item received.",
            },
            format="json",
        )

        self.assertEqual(received_response.status_code, status.HTTP_200_OK)

        return_request.refresh_from_db()
        self.assertEqual(return_request.status, ReturnRequest.Status.ITEM_RECEIVED)

        refunded_url = reverse("return-request-mark-refunded", args=[return_request.id])
        refunded_response = self.client.post(
            refunded_url,
            data={
                "note": "Refund completed.",
            },
            format="json",
        )

        self.assertEqual(refunded_response.status_code, status.HTTP_200_OK)

        return_request.refresh_from_db()
        self.assertEqual(return_request.status, ReturnRequest.Status.REFUNDED)
        self.assertIsNotNone(return_request.closed_at)

        return_item = return_request.items.first()
        return_item.refresh_from_db()

        self.assertEqual(return_item.status, ReturnItem.ItemStatus.REFUNDED)
