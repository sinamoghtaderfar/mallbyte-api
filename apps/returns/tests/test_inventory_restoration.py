from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest import skipUnless
from unittest.mock import patch

from django.core.cache import cache
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, close_old_connections, connection, transaction
from django.db.models.deletion import ProtectedError
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase, APITransactionTestCase

from apps.inventory.models import Stock, StockMovement, Warehouse
from apps.payments.models import Payment
from apps.rbac.models import Permission, Role, RolePermission
from apps.rbac.utils import assign_role
from apps.returns.models import ReturnItem, ReturnRequest, ReturnShipment, ReturnStockRestoration
from apps.returns.tests import test_returns_flow as flow
from apps.settlements.models import ConfirmedRefund, SellerLedgerEntry


class ReturnInventoryRestorationTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        flow.ReturnsFlowTests.setUp(self)
        self.warehouse = Warehouse.objects.create(name="Restored returns", code="RETURN-RESTOCK")
        self.stock = Stock.objects.create(product=self.product, warehouse=self.warehouse, quantity=5)
        self.claim = ReturnRequest.objects.create(
            customer=self.customer, order=self.order, status=ReturnRequest.Status.ITEM_RECEIVED,
            total_requested_amount=200000, total_approved_amount=200000,
        )
        self.item = ReturnItem.objects.create(
            return_request=self.claim, order_item=self.order_item, quantity=2,
            status=ReturnItem.ItemStatus.RECEIVED,
            requested_refund_amount=200000, approved_refund_amount=200000,
        )
        self.receipt = ReturnShipment.objects.create(return_request=self.claim, received_at=timezone.now())
        self.payment = Payment.objects.create(
            order=self.order, user=self.customer, amount=self.order.total_amount,
            status=Payment.StatusChoices.SUCCESS,
        )
        self.url = reverse("return-item-restock", args=[self.claim.pk, self.item.pk])
        self.payload = {"warehouse": self.warehouse.pk, "quantity": 1,
                        "idempotency_key": "restock-key-one", "sellable_confirmed": True,
                        "note": "Inspected and confirmed sellable."}
        self.client.force_authenticate(self.admin_user)

    def restock(self, **changes):
        return self.client.post(self.url, {**self.payload, **changes}, format="json")

    def grant(self, user, code="restock_returns"):
        permission, _ = Permission.objects.get_or_create(codename=code, defaults={"name": code, "module": "inventory"})
        role = Role.objects.create(name=f"restock-grant-{user.pk}-{code}")
        RolePermission.objects.create(role=role, permission=permission)
        assign_role(user, role)

    def test_explicit_restock_records_movement_audit_and_never_changes_money(self):
        before_order = self.order.__class__.objects.values().get(pk=self.order.pk)
        before_claim = ReturnRequest.objects.values().get(pk=self.claim.pk)
        before_item = ReturnItem.objects.values().get(pk=self.item.pk)
        before_payment = Payment.objects.values().get(pk=self.payment.pk)
        result = self.restock()
        self.assertEqual(result.status_code, 201, result.data)
        self.assertEqual(result.data["remaining_quantity"], 1)
        audit = ReturnStockRestoration.objects.get()
        self.assertTrue(audit.sellable_confirmed)
        self.assertEqual(audit.actor_id, self.admin_user.pk)
        self.assertEqual(audit.note, self.payload["note"])
        movement = audit.movement
        self.assertEqual(movement.movement_type, StockMovement.MovementType.RETURN)
        self.assertEqual((movement.quantity, movement.before_quantity, movement.after_quantity), (1, 5, 6))
        self.stock.refresh_from_db()
        self.assertEqual((self.stock.quantity, self.stock.reserved_quantity), (6, 0))
        self.assertEqual(self.order.__class__.objects.values().get(pk=self.order.pk), before_order)
        self.assertEqual(ReturnRequest.objects.values().get(pk=self.claim.pk), before_claim)
        self.assertEqual(ReturnItem.objects.values().get(pk=self.item.pk), before_item)
        self.assertEqual(Payment.objects.values().get(pk=self.payment.pk), before_payment)
        self.assertFalse(ConfirmedRefund.objects.exists())
        self.assertFalse(SellerLedgerEntry.objects.exists())

    def test_same_key_replays_exact_movement_without_stock_increment(self):
        first = self.restock()
        second = self.restock()
        self.assertEqual((first.status_code, second.status_code), (201, 200))
        self.assertEqual(first.data["movement"], second.data["movement"])
        self.assertTrue(second.data["replayed"])
        self.assertEqual(ReturnStockRestoration.objects.count(), 1)
        self.assertEqual(StockMovement.objects.count(), 1)
        self.stock.refresh_from_db()
        self.assertEqual(self.stock.quantity, 6)

    def test_key_cannot_change_quantity_warehouse_or_inspection_note(self):
        self.assertEqual(self.restock().status_code, 201)
        other = Warehouse.objects.create(name="Another return location", code="OTHER-RETURN")
        for changes in ({"quantity": 2}, {"warehouse": other.pk}, {"note": "Changed decision"}):
            with self.subTest(changes=changes):
                result = self.restock(**changes)
                self.assertEqual(result.status_code, 409, result.data)
        self.assertEqual(ReturnStockRestoration.objects.count(), 1)

    def test_multiple_partial_operations_are_capped_by_received_quantity(self):
        self.assertEqual(self.restock().status_code, 201)
        second = self.restock(idempotency_key="restock-key-two")
        self.assertEqual(second.status_code, 201, second.data)
        self.assertEqual(second.data["remaining_quantity"], 0)
        self.assertEqual(self.restock(idempotency_key="restock-key-three").status_code, 400)
        self.stock.refresh_from_db()
        self.assertEqual(self.stock.quantity, 7)

    def test_warehouse_is_explicit_active_and_existing(self):
        inactive = Warehouse.objects.create(name="Inactive returns", code="RETURN-INACTIVE", is_active=False)
        for target in (inactive.pk, 9_223_372_036_854_775_807):
            self.assertEqual(self.restock(warehouse=target).status_code, 400)
        target = Warehouse.objects.create(name="Chosen destination", code="RETURN-CHOSEN")
        result = self.restock(warehouse=target.pk)
        self.assertEqual(result.status_code, 201, result.data)
        self.assertEqual(Stock.objects.get(product=self.product, warehouse=target).quantity, 1)
        self.stock.refresh_from_db()
        self.assertEqual(self.stock.quantity, 5)

    def test_refund_status_without_actual_receipt_does_not_enable_restock(self):
        ReturnRequest.objects.filter(pk=self.claim.pk).update(status=ReturnRequest.Status.REFUNDED)
        ReturnItem.objects.filter(pk=self.item.pk).update(status=ReturnItem.ItemStatus.REFUNDED)
        ReturnShipment.objects.filter(pk=self.receipt.pk).update(received_at=None)
        self.assertEqual(self.restock().status_code, 400)
        self.assertFalse(StockMovement.objects.exists())
        ReturnShipment.objects.filter(pk=self.receipt.pk).update(received_at=timezone.now())
        self.assertEqual(self.restock().status_code, 201)

    def test_unreceived_or_cancelled_item_cannot_be_restocked(self):
        ReturnItem.objects.filter(pk=self.item.pk).update(status=ReturnItem.ItemStatus.REQUESTED)
        self.assertEqual(self.restock().status_code, 400)
        ReturnItem.objects.filter(pk=self.item.pk).update(status=ReturnItem.ItemStatus.RECEIVED)
        ReturnRequest.objects.filter(pk=self.claim.pk).update(status=ReturnRequest.Status.CANCELLED)
        self.assertEqual(self.restock().status_code, 400)
        self.assertFalse(StockMovement.objects.exists())

    def test_explicit_boolean_confirmation_positive_quantity_and_key_are_required(self):
        for value in (False, "true", 1, None):
            with self.subTest(value=value):
                self.assertEqual(self.restock(sellable_confirmed=value).status_code, 400)
        for value in (0, -1, 2_147_483_648):
            self.assertEqual(self.restock(quantity=value).status_code, 400)
        self.assertEqual(self.restock(idempotency_key="short").status_code, 400)
        self.assertEqual(self.client.post(self.url, {"quantity": 1}, format="json").status_code, 400)
        self.assertFalse(StockMovement.objects.exists())

    def test_unrelated_staff_customer_and_seller_have_no_restock_power(self):
        self.customer.is_staff = True
        self.customer.save(update_fields=["is_staff"])
        self.other_customer.is_seller = True
        self.other_customer.save(update_fields=["is_seller"])
        for user in (self.customer, self.other_customer):
            self.client.force_authenticate(user)
            self.assertEqual(self.restock().status_code, 403)
        self.grant(self.customer, "manage_returns")
        self.client.force_authenticate(self.customer)
        self.assertEqual(self.restock().status_code, 403)
        self.client.force_authenticate(None)
        self.assertEqual(self.restock().status_code, 401)
        self.assertFalse(StockMovement.objects.exists())

    def test_nonstaff_manager_requires_dedicated_grant_and_inactive_account_is_denied(self):
        self.grant(self.other_customer)
        self.client.force_authenticate(self.other_customer)
        self.assertEqual(self.restock().status_code, 201)
        self.other_customer.is_active = False
        self.other_customer.save(update_fields=["is_active"])
        self.assertEqual(self.restock(idempotency_key="inactive-key").status_code, 403)

    def test_permission_is_seeded_without_automatic_role_grants(self):
        permission = Permission.objects.get(codename="restock_returns")
        self.assertEqual(permission.module, "inventory")
        self.assertFalse(RolePermission.objects.filter(permission=permission).exists())

    def test_item_must_belong_to_the_requested_return(self):
        other = ReturnRequest.objects.create(customer=self.customer, order=self.order)
        self.url = reverse("return-item-restock", args=[other.pk, self.item.pk])
        self.assertEqual(self.restock().status_code, 404)

    def test_audit_failure_rolls_back_stock_movement_and_new_stock_row(self):
        target = Warehouse.objects.create(name="Rollback destination", code="RETURN-ROLLBACK")
        with patch("apps.returns.inventory_restoration.ReturnStockRestoration.objects.create", side_effect=RuntimeError("Audit unavailable")):
            with self.assertRaises(RuntimeError):
                self.restock(warehouse=target.pk)
        self.assertFalse(Stock.objects.filter(product=self.product, warehouse=target).exists())
        self.assertFalse(StockMovement.objects.exists())
        self.assertFalse(ReturnStockRestoration.objects.exists())

    def test_stock_overflow_is_validation_error_and_does_not_create_movement(self):
        Stock.objects.filter(pk=self.stock.pk).update(quantity=2_147_483_647)
        self.assertEqual(self.restock().status_code, 400)
        self.assertFalse(StockMovement.objects.exists())

    def test_audit_is_append_only_and_protects_warehouse_movement_and_item(self):
        self.assertEqual(self.restock().status_code, 201)
        audit = ReturnStockRestoration.objects.get()
        audit.note = "Rewrite history"
        with self.assertRaises(DjangoValidationError):
            audit.save()
        with self.assertRaises(DjangoValidationError):
            audit.delete()
        with self.assertRaises(DjangoValidationError):
            ReturnStockRestoration.objects.filter(pk=audit.pk).update(quantity=2)
        with self.assertRaises(DjangoValidationError):
            ReturnStockRestoration.objects.all().delete()
        with self.assertRaises(DjangoValidationError):
            ReturnStockRestoration(pk=audit.pk).save()
        with self.assertRaises(DjangoValidationError):
            ReturnStockRestoration.objects.bulk_create([audit], update_conflicts=True, update_fields=["note"], unique_fields=["pk"])
        for obj in (audit.movement, self.item, self.warehouse):
            with self.subTest(model=type(obj).__name__), self.assertRaises(ProtectedError):
                obj.delete()

    def test_database_rejects_zero_quantity_and_unconfirmed_saleability(self):
        self.assertEqual(self.restock().status_code, 201)
        audit = ReturnStockRestoration.objects.get()
        for changes in ({"quantity": 0}, {"sellable_confirmed": False}):
            with self.subTest(changes=changes), self.assertRaises(IntegrityError), transaction.atomic():
                new_movement = StockMovement.objects.create(product=self.product, warehouse=self.warehouse,
                    movement_type=StockMovement.MovementType.RETURN, quantity=1, created_by=self.admin_user)
                ReturnStockRestoration.objects.bulk_create([ReturnStockRestoration(
                    return_item=self.item, warehouse=self.warehouse, movement=new_movement,
                    actor=self.admin_user, quantity=changes.get("quantity", 1),
                    sellable_confirmed=changes.get("sellable_confirmed", True), idempotency_key=f"invalid-{new_movement.pk}",
                )])
        self.assertEqual(ReturnStockRestoration.objects.count(), 1)
        self.assertEqual(audit.movement.quantity, 1)


@skipUnless(connection.vendor == "postgresql", "Requires PostgreSQL row locks")
class ReturnInventoryRestorationConcurrencyTests(APITransactionTestCase):
    setUp = ReturnInventoryRestorationTests.setUp

    def concurrent_restock(self, keys):
        barrier = Barrier(2)

        def call(key):
            close_old_connections()
            try:
                client = APIClient()
                client.force_authenticate(self.admin_user)
                barrier.wait(timeout=5)
                result = client.post(self.url, {**self.payload, "quantity": 2, "idempotency_key": key}, format="json")
                return result.status_code, result.data
            finally:
                connection.close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(call, key) for key in keys]
            return [future.result(timeout=12) for future in futures]

    def test_simultaneous_same_key_creates_one_movement_and_replays(self):
        results = self.concurrent_restock(["concurrent-restock", "concurrent-restock"])
        self.assertEqual(sorted(code for code, _ in results), [200, 201])
        self.assertEqual(results[0][1]["movement"], results[1][1]["movement"])
        self.assertEqual(ReturnStockRestoration.objects.count(), 1)
        self.stock.refresh_from_db()
        self.assertEqual(self.stock.quantity, 7)

    def test_different_keys_cannot_exceed_received_quantity(self):
        results = self.concurrent_restock(["concurrent-restock-one", "concurrent-restock-two"])
        self.assertEqual(sorted(code for code, _ in results), [201, 400])
        self.assertEqual(ReturnStockRestoration.objects.count(), 1)
        self.stock.refresh_from_db()
        self.assertEqual(self.stock.quantity, 7)
