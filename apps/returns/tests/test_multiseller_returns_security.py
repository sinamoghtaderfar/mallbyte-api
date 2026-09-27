from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from apps.orders.models import Order, OrderItem, SellerOrderFulfillment
from apps.products.models import Category, Product
from apps.returns.models import (
    ReturnAttachment, ReturnItem, ReturnRequest, ReturnStatusHistory,
    ReturnShipment,
)
from apps.returns.services import approve_return_request

User = get_user_model()


class MultiSellerReturnsSecurityTests(APITestCase):
    def setUp(self):
        self.buyer = User.objects.create_user(
            email="returns-multiseller-buyer@example.com",
            phone="+989300001001", password="TestPassword123!",
        )
        self.other_buyer = User.objects.create_user(
            email="returns-multiseller-other-buyer@example.com",
            phone="+989300001002", password="TestPassword123!",
        )
        self.first_seller = User.objects.create_user(
            email="returns-multiseller-seller-a@example.com",
            phone="+989300001003", password="TestPassword123!", is_seller=True,
        )
        self.second_seller = User.objects.create_user(
            email="returns-multiseller-seller-b@example.com",
            phone="+989300001004", password="TestPassword123!", is_seller=True,
        )
        self.unrelated_seller = User.objects.create_user(
            email="returns-multiseller-unrelated@example.com",
            phone="+989300001005", password="TestPassword123!", is_seller=True,
        )
        self.admin = User.objects.create_superuser(
            email="returns-multiseller-admin@example.com",
            phone="+989300001006", password="TestPassword123!",
        )
        category = Category.objects.create(
            name="Multiseller returns", slug="multiseller-returns",
        )
        first_product = Product.objects.create(
            seller=self.first_seller, category=category, name="Seller A product",
            slug="return-a-product", price=Decimal("100"), sku="RET-SELLER-A",
            status=Product.StatusChoices.APPROVED, is_active=True,
        )
        second_product = Product.objects.create(
            seller=self.second_seller, category=category, name="Seller B product",
            slug="return-b-product", price=Decimal("200"), sku="RET-SELLER-B",
            status=Product.StatusChoices.APPROVED, is_active=True,
        )
        self.order = Order.objects.create(
            user=self.buyer, status=Order.StatusChoices.DELIVERED,
            payment_status=Order.PaymentStatusChoices.PAID,
            subtotal=Decimal("300"), receiver_name="Test Buyer",
            receiver_phone="+989300001001", province="Tehran", city="Tehran",
            address="Returns test street", postal_code="1234567890",
        )
        self.first_item = OrderItem.objects.create(
            order=self.order, product=first_product,
            quantity=1, unit_price=Decimal("100"),
        )
        self.second_item = OrderItem.objects.create(
            order=self.order, product=second_product,
            quantity=1, unit_price=Decimal("200"),
        )
        self.first_fulfillment = SellerOrderFulfillment.objects.create(
            order=self.order, seller=self.first_seller,
            status=Order.StatusChoices.DELIVERED,
        )
        self.second_fulfillment = SellerOrderFulfillment.objects.create(
            order=self.order, seller=self.second_seller,
            status=Order.StatusChoices.DELIVERED,
        )
        self.claim = ReturnRequest.objects.create(
            order=self.order, customer=self.buyer,
            status=ReturnRequest.Status.SUBMITTED,
            reason=ReturnRequest.Reason.DAMAGED,
            customer_note="SHARED_CUSTOMER_NOTE_DO_NOT_EXPOSE_TO_SELLERS",
            internal_note="ADMIN_INTERNAL_SECRET",
            total_requested_amount=Decimal("300.00"),
        )
        self.claim_a = ReturnItem.objects.create(
            return_request=self.claim, order_item=self.first_item,
            quantity=1, requested_refund_amount=Decimal("100.00"),
            customer_note="Only seller A should see this item note",
            inspection_note="INSPECTION_SECRET_A",
        )
        self.claim_b = ReturnItem.objects.create(
            return_request=self.claim, order_item=self.second_item,
            quantity=1, requested_refund_amount=Decimal("200.00"),
            customer_note="Only seller B should see this item note",
            inspection_note="INSPECTION_SECRET_B",
        )
        ReturnAttachment.objects.create(
            return_request=self.claim, return_item=self.claim_a,
            file="returns/test/a.jpg", caption="Seller A attachment",
            uploaded_by=self.buyer,
        )
        ReturnAttachment.objects.create(
            return_request=self.claim, return_item=self.claim_b,
            file="returns/test/b.jpg", caption="Seller B attachment",
            uploaded_by=self.buyer,
        )
        ReturnAttachment.objects.create(
            return_request=self.claim, return_item=None,
            file="returns/test/shared.jpg", caption="Shared sensitive attachment",
            uploaded_by=self.buyer,
        )
        ReturnAttachment.objects.create(
            return_request=self.claim, return_item=self.claim_a,
            file="returns/test/internal.jpg", caption="ADMIN_ATTACHMENT_SECRET",
            uploaded_by=self.admin,
        )
        ReturnStatusHistory.objects.create(
            return_request=self.claim, old_status="", new_status="submitted",
            note="ADMIN_HISTORY_NOTE_PRIVATE", changed_by=self.admin,
        )
        ReturnShipment.objects.create(
            return_request=self.claim, carrier="dhl",
            shipping_label="returns/test/private-shipping-label.pdf",
        )

    def test_sellers_only_see_their_items_attachments_and_money(self):
        for seller, own_item, own_caption, requested in (
            (self.first_seller, self.claim_a, "Seller A attachment", "100.00"),
            (self.second_seller, self.claim_b, "Seller B attachment", "200.00"),
        ):
            self.client.force_authenticate(user=seller)
            list_response = self.client.get(reverse("return-request-seller"))
            self.assertEqual(list_response.status_code, status.HTTP_200_OK)
            rows = (list_response.data.get("results", [])
                    if isinstance(list_response.data, dict)
                    else list_response.data)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["total_requested_amount"], requested)
            self.assertEqual(rows[0]["total_approved_amount"], "0.00")
            detail = self.client.get(
                reverse("return-request-seller-detail", args=[self.claim.pk])
            )
            self.assertEqual(detail.status_code, status.HTTP_200_OK, detail.data)
            self.assertEqual([x["id"] for x in detail.data["items"]], [own_item.pk])
            self.assertEqual(detail.data["total_requested_amount"], requested)
            self.assertEqual(len(detail.data["attachments"]), 1)
            self.assertEqual(detail.data["attachments"][0]["caption"], own_caption)
            self.assertNotIn("internal_note", detail.data)
            self.assertNotIn("inspection_note", detail.data["items"][0])
            self.assertEqual(detail.data["customer_note"], "")
            self.assertNotIn("shipment", detail.data)
            self.assertEqual(detail.data["status_history"][0]["note"], "")
            self.assertIsNone(detail.data["status_history"][0]["changed_by"])
            self.assertNotIn("ADMIN_INTERNAL_SECRET", str(detail.data))
            self.assertNotIn("SHARED_CUSTOMER_NOTE", str(detail.data))
            self.assertNotIn("Shared sensitive attachment", str(detail.data))
            self.assertNotIn("ADMIN_ATTACHMENT_SECRET", str(detail.data))
            self.assertNotIn("Only seller B" if seller.pk == self.first_seller.pk
                             else "Only seller A", str(detail.data))

    def test_first_seller_cannot_retrieve_a_second_seller_only_claim(self):
        second_claim = ReturnRequest.objects.create(
            order=self.order, customer=self.buyer,
            status=ReturnRequest.Status.SUBMITTED,
            total_requested_amount=Decimal("200.00"),
        )
        ReturnItem.objects.create(
            return_request=second_claim, order_item=self.second_item,
            quantity=1, requested_refund_amount=Decimal("200.00"),
        )
        self.client.force_authenticate(user=self.first_seller)
        self.assertEqual(
            self.client.get(
                reverse("return-request-seller-detail", args=[second_claim.pk])
            ).status_code,
            status.HTTP_404_NOT_FOUND,
        )

    def test_unrelated_seller_and_unapproved_accounts_have_no_access(self):
        self.client.force_authenticate(user=self.unrelated_seller)
        response = self.client.get(reverse("return-request-seller"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        rows = (response.data.get("results", []) if isinstance(response.data, dict)
                else response.data)
        self.assertEqual(rows, [])
        self.assertEqual(
            self.client.get(reverse("return-request-seller-detail", args=[self.claim.pk])).status_code,
            status.HTTP_404_NOT_FOUND,
        )
        self.client.force_authenticate(user=self.other_buyer)
        self.assertEqual(
            self.client.get(reverse("return-request-seller")).status_code,
            status.HTTP_403_FORBIDDEN,
        )
        self.assertEqual(
            self.client.get(reverse("return-request-seller-detail", args=[self.claim.pk])).status_code,
            status.HTTP_403_FORBIDDEN,
        )

    def test_customer_details_and_action_responses_hide_admin_notes(self):
        self.client.force_authenticate(user=self.buyer)
        detail = self.client.get(reverse("return-request-detail", args=[self.claim.pk]))
        self.assertEqual(detail.status_code, status.HTTP_200_OK)
        self.assertNotIn("internal_note", detail.data)
        self.assertNotIn("inspection_note", detail.data["items"][0])
        self.assertEqual(detail.data["status_history"][0]["note"], "")
        self.assertNotIn("ADMIN_ATTACHMENT_SECRET", str(detail.data))
        self.assertEqual(len(detail.data["attachments"]), 3)
        result = self.client.post(reverse("return-request-cancel", args=[self.claim.pk]),
                                  {"note": "Buyer cancelled"}, format="json")
        self.assertEqual(result.status_code, status.HTTP_200_OK, result.data)
        self.assertNotIn("internal_note", result.data)
        self.assertEqual(result.data["status_history"][0]["note"], "")
        self.client.force_authenticate(user=self.other_buyer)
        self.assertEqual(
            self.client.get(reverse("return-request-detail", args=[self.claim.pk])).status_code,
            status.HTTP_404_NOT_FOUND,
        )

    def test_admin_still_sees_complete_return_information(self):
        self.client.force_authenticate(user=self.admin)
        response = self.client.get(reverse("return-request-detail", args=[self.claim.pk]))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["items"]), 2)
        self.assertEqual(response.data["internal_note"], "ADMIN_INTERNAL_SECRET")
        self.assertEqual(response.data["status_history"][0]["note"],
                         "ADMIN_HISTORY_NOTE_PRIVATE")
        self.assertEqual(len(response.data["attachments"]), 4)

    def test_partial_approval_is_allocated_per_item_and_per_seller(self):
        approve_return_request(
            return_request=self.claim, user=self.admin,
            approved_amount=Decimal("150.00"),
        )
        self.claim.refresh_from_db()
        self.claim_a.refresh_from_db()
        self.claim_b.refresh_from_db()
        self.assertEqual(self.claim.total_approved_amount, Decimal("150.00"))
        self.assertEqual(self.claim_a.approved_refund_amount, Decimal("50.00"))
        self.assertEqual(self.claim_b.approved_refund_amount, Decimal("100.00"))
        self.client.force_authenticate(user=self.first_seller)
        detail_a = self.client.get(
            reverse("return-request-seller-detail", args=[self.claim.pk])
        )
        self.assertEqual(detail_a.data["total_approved_amount"], "50.00")
        self.client.force_authenticate(user=self.second_seller)
        detail_b = self.client.get(
            reverse("return-request-seller-detail", args=[self.claim.pk])
        )
        self.assertEqual(detail_b.data["total_approved_amount"], "100.00")

    def test_approval_cannot_exceed_requested_total(self):
        with self.assertRaises(ValidationError):
            approve_return_request(
                return_request=self.claim, user=self.admin,
                approved_amount=Decimal("301.00"),
            )
        self.claim.refresh_from_db()
        self.assertEqual(self.claim.status, ReturnRequest.Status.SUBMITTED)
        self.assertEqual(self.claim.total_approved_amount, Decimal("0.00"))

    def test_delivered_seller_can_be_returned_before_entire_order_delivered(self):
        self.claim.status = ReturnRequest.Status.CANCELLED
        self.claim.save(update_fields=["status"])
        self.order.status = Order.StatusChoices.PROCESSING
        self.order.save(update_fields=["status", "total_amount", "updated_at"])
        self.second_fulfillment.status = Order.StatusChoices.PAID
        self.second_fulfillment.save(update_fields=["status"])
        self.client.force_authenticate(user=self.buyer)
        url = reverse("return-request-list")
        payload = {
            "order": self.order.pk,
            "reason": ReturnRequest.Reason.DAMAGED,
            "items": [
                {"order_item": self.first_item.pk, "quantity": 1},
                {"order_item": self.second_item.pk, "quantity": 1},
            ],
        }
        rejected = self.client.post(url, payload, format="json")
        self.assertEqual(rejected.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(ReturnRequest.objects.filter(order=self.order).count(), 1)
        rejected = self.client.post(url, {
            **payload, "items": [{"order_item": self.second_item.pk, "quantity": 1}],
        }, format="json")
        self.assertEqual(rejected.status_code, status.HTTP_400_BAD_REQUEST)
        accepted = self.client.post(url, {
            **payload, "items": [{"order_item": self.first_item.pk, "quantity": 1}],
        }, format="json")
        self.assertEqual(accepted.status_code, status.HTTP_201_CREATED, accepted.data)
        self.assertEqual(accepted.data["items"][0]["order_item_id"], self.first_item.pk)
        self.assertNotIn("internal_note", accepted.data)
        self.assertEqual(ReturnRequest.objects.filter(order=self.order).count(), 2)

    def test_seller_cannot_modify_return(self):
        self.client.force_authenticate(user=self.first_seller)
        response = self.client.post(reverse("return-request-mark-refunded", args=[self.claim.pk]),
                                    {}, format="json")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
