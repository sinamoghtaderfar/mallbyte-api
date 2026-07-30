from decimal import Decimal

from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from apps.accounts.models import User
from apps.notifications.models import Notification, NotificationPreference
from apps.orders.models import Order, OrderItem
from apps.products.models import Category, Product
from apps.returns.models import ReturnItem, ReturnRequest


class ReturnNotificationPreferenceIntegrationTests(APITestCase):
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
            phone="+989850000001",
            email="admin_return_pref@example.com",
            full_name="Return Preference Admin",
            is_staff=True,
            is_superuser=True,
        )

        self.customer = self.create_test_user(
            phone="+989850000002",
            email="customer_return_pref@example.com",
            full_name="Return Preference Customer",
        )

        self.category = Category.objects.create(
            name="Return Preference Category",
            description="Test category",
            is_active=True,
        )

        self.product = Product.objects.create(
            seller=self.admin_user,
            category=self.category,
            name="Return Preference Product",
            description="Product for return preference tests",
            price=Decimal("100000"),
            status=Product.StatusChoices.APPROVED,
            is_active=True,
            sku="RETURN-PREF-SKU-001",
        )

        self.order = Order.objects.create(
            user=self.customer,
            status=Order.StatusChoices.DELIVERED,
            payment_status=Order.PaymentStatusChoices.PAID,
            subtotal=Decimal("200000"),
            discount_amount=Decimal("0"),
            shipping_cost=Decimal("0"),
            tax_amount=Decimal("0"),
            receiver_name="Return Preference Customer",
            receiver_phone="+989850000002",
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

        NotificationPreference.objects.create(
            user=self.customer,
            muted_notification_types=[
                Notification.NotificationType.RETURN,
            ],
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

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        return ReturnRequest.objects.get(order=self.order)

    def assert_return_notification_does_not_exist(self, *, return_request, title):
        self.assertFalse(
            Notification.objects.filter(
                user=self.customer,
                notification_type=Notification.NotificationType.RETURN,
                related_object_type="return_request",
                related_object_id=str(return_request.pk),
                title=title,
            ).exists()
        )

    def test_muted_return_type_blocks_return_submitted_notification(self):
        return_request = self.create_return_request()

        self.assertEqual(return_request.status, ReturnRequest.Status.SUBMITTED)

        self.assert_return_notification_does_not_exist(
            return_request=return_request,
            title="Return request submitted",
        )

    def test_muted_return_type_blocks_return_cancelled_notification(self):
        return_request = self.create_return_request()

        url = reverse("return-request-cancel", args=[return_request.id])

        response = self.client.post(
            url,
            data={
                "note": "I changed my mind.",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        return_request.refresh_from_db()

        self.assertEqual(return_request.status, ReturnRequest.Status.CANCELLED)

        self.assert_return_notification_does_not_exist(
            return_request=return_request,
            title="Return request cancelled",
        )

    def test_muted_return_type_blocks_return_approved_notification(self):
        return_request = self.create_return_request()

        self.authenticate_admin()

        url = reverse("return-request-approve", args=[return_request.id])

        response = self.client.post(
            url,
            data={
                "note": "Approved by admin.",
                "approved_amount": "100000.00",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        return_request.refresh_from_db()

        self.assertEqual(return_request.status, ReturnRequest.Status.APPROVED)

        self.assert_return_notification_does_not_exist(
            return_request=return_request,
            title="Return request approved",
        )

    def test_muted_return_type_blocks_return_rejected_notification(self):
        return_request = self.create_return_request()

        self.authenticate_admin()

        url = reverse("return-request-reject", args=[return_request.id])

        response = self.client.post(
            url,
            data={
                "note": "Return request rejected by admin.",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        return_request.refresh_from_db()

        self.assertEqual(return_request.status, ReturnRequest.Status.REJECTED)

        self.assert_return_notification_does_not_exist(
            return_request=return_request,
            title="Return request rejected",
        )

    def test_muted_return_type_blocks_return_received_notification(self):
        return_request = self.create_return_request()

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

        self.assert_return_notification_does_not_exist(
            return_request=return_request,
            title="Return item received",
        )

    def test_muted_return_type_blocks_return_refunded_notification(self):
        return_request = self.create_return_request()

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

        self.assert_return_notification_does_not_exist(
            return_request=return_request,
            title="Return refunded",
        )
