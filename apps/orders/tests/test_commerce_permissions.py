from types import SimpleNamespace

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.test import override_settings
from django.urls import reverse
from rest_framework.test import APITestCase

from apps.orders.models import Order, OrderItem
from apps.payments.models import Payment, PaymentEvent
from apps.payments.serializers import PaymentCreateSerializer
from apps.products.models import Category, Product
from apps.rbac.models import Permission, Role, RolePermission
from apps.rbac.utils import assign_role
from apps.returns.models import ReturnItem, ReturnRequest
from apps.returns.services import approve_return_request
from apps.shipping.models import Shipment
from apps.shipping.serializers import ShipmentCreateSerializer


class CommercePermissionTests(APITestCase):
    def setUp(self):
        cache.clear()
        User = get_user_model()
        self.owner = User.objects.create_user(email="commerce-owner@example.com", password="TestPass123!")
        self.staff = User.objects.create_user(email="commerce-staff@example.com", password="TestPass123!", is_staff=True)
        self.operator = User.objects.create_user(email="commerce-operator@example.com", password="TestPass123!")
        self.order = Order.objects.create(
            user=self.owner, subtotal=100, admin_note="private operations note",
            receiver_name="Owner", receiver_phone="1234567890", province="Test",
            city="Test", address="Test address", postal_code="12345",
        )
        self.product = Product.objects.create(
            seller=self.owner, category=Category.objects.create(name="Commerce auth"),
            name="Commerce auth", sku="COMMERCE-AUTH", price=100,
        )
        self.item = OrderItem.objects.create(order=self.order, product=self.product, quantity=1, unit_price=100)
        self.payment = Payment.objects.create(order=self.order, user=self.owner, amount=100, gateway_response={"private": "payment metadata"})
        PaymentEvent.objects.create(payment=self.payment, event_type="test", data={"private": "event metadata"})
        self.shipment = Shipment.objects.create(order=self.order, user=self.owner)
        self.claim = ReturnRequest.objects.create(order=self.order, customer=self.owner, total_requested_amount=100)
        ReturnItem.objects.create(return_request=self.claim, order_item=self.item, quantity=1, requested_refund_amount=100)

    def grant(self, *permissions):
        role = Role.objects.create(name=f"commerce-test-{Role.objects.count()}")
        for name in permissions:
            RolePermission.objects.create(role=role, permission=Permission.objects.get(codename=name))
        assign_role(self.operator, role)

    def authenticate(self, user):
        self.client.force_authenticate(user)

    def test_unrelated_staff_cannot_read_other_customer_details(self):
        self.authenticate(self.staff)
        urls = [
            f"/api/orders/orders/{self.order.pk}/",
            f"/api/payments/payments/{self.payment.pk}/",
            f"/api/shipping/shipments/{self.shipment.pk}/",
            reverse("return-request-detail", args=[self.claim.pk]),
        ]
        for url in urls:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 404)

    def test_explicit_readers_can_read_other_customer_records(self):
        self.grant("view_all_orders", "view_all_payments", "view_all_shipments", "view_all_returns")
        self.authenticate(self.operator)
        urls = [
            f"/api/orders/orders/{self.order.pk}/",
            f"/api/payments/payments/{self.payment.pk}/",
            f"/api/shipping/shipments/{self.shipment.pk}/",
            reverse("return-request-detail", args=[self.claim.pk]),
        ]
        for url in urls:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_read_permissions_do_not_grant_mutations(self):
        self.grant("view_all_orders", "view_all_payments", "view_all_shipments", "view_all_returns")
        self.authenticate(self.operator)
        cases = [
            (f"/api/orders/orders/{self.order.pk}/update-status/", {"status": "processing"}, 403),
            (f"/api/orders/orders/{self.order.pk}/cancel/", {}, 404),
            (f"/api/payments/payments/{self.payment.pk}/cancel/", {}, 404),
            (f"/api/shipping/shipments/{self.shipment.pk}/mark-ready/", {}, 403),
            (reverse("return-request-approve", args=[self.claim.pk]), {}, 403),
        ]
        for url, body, expected in cases:
            with self.subTest(url=url):
                self.assertEqual(self.client.post(url, body, format="json").status_code, expected)

    def test_staff_cannot_create_payment_attempt_for_another_customer(self):
        serializer = PaymentCreateSerializer(data={"order": self.order.pk}, context={"request": SimpleNamespace(user=self.staff)})
        self.assertFalse(serializer.is_valid())

    def test_nonstaff_payment_manager_can_create_other_customer_attempt(self):
        self.grant("manage_payments")
        serializer = PaymentCreateSerializer(data={"order": self.order.pk}, context={"request": SimpleNamespace(user=self.operator)})
        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(serializer.save().user_id, self.owner.pk)

    def test_staff_cannot_bypass_shipment_serializer_permission(self):
        serializer = ShipmentCreateSerializer(data={"order": self.order.pk}, context={"request": SimpleNamespace(user=self.staff)})
        self.assertFalse(serializer.is_valid())
        self.assertIn("permission", str(serializer.errors).lower())

    def test_service_rejects_staff_and_readonly_return_decisions(self):
        self.grant("view_all_returns")
        for actor in [self.staff, self.operator]:
            with self.subTest(actor=actor.pk), self.assertRaises(ValidationError):
                approve_return_request(return_request=self.claim, user=actor)

    def test_nonstaff_return_manager_can_approve(self):
        self.grant("manage_returns")
        result = approve_return_request(return_request=self.claim, user=self.operator)
        self.assertEqual(result.status, ReturnRequest.Status.APPROVED)

    def test_nonstaff_order_manager_can_prepare_paid_order(self):
        self.grant("manage_orders")
        self.order.status = Order.StatusChoices.PAID
        self.order.payment_status = Order.PaymentStatusChoices.PAID
        self.order.save(update_fields=["status", "payment_status", "total_amount", "updated_at"])
        self.authenticate(self.operator)
        result = self.client.post(f"/api/orders/orders/{self.order.pk}/update-status/", {"status": "processing"}, format="json")
        self.assertEqual(result.status_code, 200, result.data)

    def test_owner_details_hide_internal_order_and_payment_metadata(self):
        self.authenticate(self.owner)
        order = self.client.get(f"/api/orders/orders/{self.order.pk}/")
        payment = self.client.get(f"/api/payments/payments/{self.payment.pk}/")
        self.assertEqual(order.status_code, 200)
        self.assertEqual(payment.status_code, 200)
        self.assertNotIn("admin_note", order.data)
        self.assertNotIn("gateway_response", payment.data)
        self.assertNotIn("data", payment.data["events"][0])

    def test_authorized_readers_can_read_internal_metadata(self):
        self.grant("view_all_orders", "view_all_payments")
        self.authenticate(self.operator)
        order = self.client.get(f"/api/orders/orders/{self.order.pk}/")
        payment = self.client.get(f"/api/payments/payments/{self.payment.pk}/")
        self.assertEqual(order.data["admin_note"], "private operations note")
        self.assertIn("gateway_response", payment.data)
        self.assertIn("data", payment.data["events"][0])

    @override_settings(SETTLEMENTS_ALLOW_MOCK_SUCCESS=False)
    def test_management_permission_does_not_enable_disabled_mock_capture(self):
        self.grant("manage_payments")
        self.authenticate(self.operator)
        result = self.client.post(f"/api/payments/payments/{self.payment.pk}/mark-success/", {}, format="json")
        self.assertEqual(result.status_code, 403)
