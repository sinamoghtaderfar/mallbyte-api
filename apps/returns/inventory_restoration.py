"""Explicit, permission-gated physical restocking; never move money here."""
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.db.models import Sum
from django.shortcuts import get_object_or_404
from rest_framework import serializers, status
from rest_framework.exceptions import APIException, PermissionDenied
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.inventory.models import Stock, StockMovement, Warehouse
from apps.orders.models import Order
from apps.rbac.utils import has_permission
from apps.returns.models import ReturnItem, ReturnRequest, ReturnShipment, ReturnStockRestoration

MAX_QUANTITY = 2_147_483_647


def can_restore_inventory(user):
    return bool(user.is_authenticated and user.is_active and not user.is_deleted
                and has_permission(user, "restock_returns"))


class CanRestoreInventory(BasePermission):
    def has_permission(self, request, view):
        return can_restore_inventory(request.user)


class RestorationConflict(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = "The idempotency key was already used with different restock details."
    default_code = "restock_idempotency_conflict"


class SaleabilityConfirmation(serializers.BooleanField):
    def to_internal_value(self, data):
        if data is not True:
            raise serializers.ValidationError("Explicit boolean true is required after confirming the item is sellable.")
        return True


class RestorationInput(serializers.Serializer):
    warehouse = serializers.IntegerField(min_value=1, max_value=9_223_372_036_854_775_807)
    quantity = serializers.IntegerField(min_value=1, max_value=MAX_QUANTITY)
    idempotency_key = serializers.CharField(min_length=8, max_length=128)
    sellable_confirmed = SaleabilityConfirmation(required=True)
    note = serializers.CharField(required=False, default="", allow_blank=True, max_length=2000)


@transaction.atomic
def restore_return_inventory(*, user, request_id, item_id, warehouse_id, quantity,
                             idempotency_key, sellable_confirmed, note=""):
    if not can_restore_inventory(user):
        raise PermissionDenied("An explicit return inventory restoration permission is required.")
    if sellable_confirmed is not True or not isinstance(quantity, int) or isinstance(quantity, bool) or not 1 <= quantity <= MAX_QUANTITY:
        raise serializers.ValidationError("A positive quantity and explicit sellability confirmation are required.")
    if not isinstance(idempotency_key, str) or not 8 <= len(idempotency_key) <= 128:
        raise serializers.ValidationError({"idempotency_key": "Use between 8 and 128 characters."})
    if not isinstance(note, str) or len(note) > 2000:
        raise serializers.ValidationError({"note": "Use at most 2000 characters."})

    order_id = get_object_or_404(ReturnRequest.objects.only("order_id"), pk=request_id).order_id
    # Financial posting and return creation use the same leading Order -> Return
    # lock order. Warehouse NO KEY UPDATE allows unrelated FK checks to finish.
    Order.objects.select_for_update().get(pk=order_id)
    claim = get_object_or_404(ReturnRequest.objects.select_for_update(), pk=request_id, order_id=order_id)
    item = get_object_or_404(ReturnItem.objects.select_for_update(), pk=item_id, return_request_id=claim.pk)
    prior = ReturnStockRestoration.objects.filter(return_item=item, idempotency_key=idempotency_key).first()
    restored = ReturnStockRestoration.objects.filter(return_item=item).aggregate(total=Sum("quantity"))["total"] or 0
    if prior is not None:
        if (prior.warehouse_id, prior.quantity, prior.note, prior.sellable_confirmed) != (warehouse_id, quantity, note, sellable_confirmed):
            raise RestorationConflict()
        return prior, False, item.quantity - restored

    if item.order_item.order_id != claim.order_id:
        raise serializers.ValidationError("The return item does not match the order; reconcile the historical record first.")
    physical_statuses = {ReturnRequest.Status.ITEM_RECEIVED, ReturnRequest.Status.INSPECTING,
                         ReturnRequest.Status.REFUND_PENDING, ReturnRequest.Status.REFUNDED,
                         ReturnRequest.Status.REPLACED, ReturnRequest.Status.CLOSED}
    received_items = {ReturnItem.ItemStatus.RECEIVED, ReturnItem.ItemStatus.ACCEPTED,
                      ReturnItem.ItemStatus.REFUNDED, ReturnItem.ItemStatus.REPLACED}
    physically_received = ReturnShipment.objects.filter(return_request=claim, received_at__isnull=False).exists()
    if not physically_received or claim.status not in physical_statuses or item.status not in received_items:
        raise serializers.ValidationError("Physical receipt of this return item must be recorded before restocking.")
    remaining = item.quantity - restored
    if quantity > remaining:
        raise serializers.ValidationError({"quantity": f"At most {max(0, remaining)} received item(s) remain to restock."})
    warehouse = Warehouse.objects.select_for_update(no_key=True).filter(pk=warehouse_id, is_active=True).first()
    if warehouse is None:
        raise serializers.ValidationError({"warehouse": "Choose an active, existing warehouse."})
    stock, _ = Stock.objects.select_for_update().get_or_create(
        product_id=item.order_item.product_id, warehouse=warehouse,
        defaults={"quantity": 0, "reserved_quantity": 0, "updated_by": user},
    )
    if stock.quantity + quantity > MAX_QUANTITY:
        raise serializers.ValidationError({"quantity": "The target stock quantity would exceed its supported limit."})
    movement = StockMovement.objects.create(
        product_id=item.order_item.product_id, warehouse=warehouse,
        movement_type=StockMovement.MovementType.RETURN, quantity=quantity,
        reference_id=f"return-item:{item.pk}", reason="Received return confirmed sellable by an authorized manager.",
        created_by=user, notes=note,
    )
    restoration = ReturnStockRestoration.objects.create(
        return_item=item, movement=movement, warehouse=warehouse, quantity=quantity,
        idempotency_key=idempotency_key, sellable_confirmed=True, actor=user, note=note,
    )
    return restoration, True, remaining - quantity


class ReturnInventoryRestorationView(APIView):
    permission_classes = [IsAuthenticated, CanRestoreInventory]
    http_method_names = ["post", "options"]

    def post(self, request, pk, item_pk):
        payload = RestorationInput(data=request.data)
        payload.is_valid(raise_exception=True)
        data = payload.validated_data
        try:
            restoration, created, remaining = restore_return_inventory(
                user=request.user, request_id=pk, item_id=item_pk,
                warehouse_id=data["warehouse"], quantity=data["quantity"],
                idempotency_key=data["idempotency_key"], sellable_confirmed=data["sellable_confirmed"], note=data["note"],
            )
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.messages) from exc
        return Response({
            "id": restoration.pk, "return_item": restoration.return_item_id,
            "warehouse": restoration.warehouse_id, "quantity": restoration.quantity,
            "movement": restoration.movement_id, "actor": restoration.actor_id,
            "note": restoration.note, "created_at": restoration.created_at,
            "remaining_quantity": remaining, "replayed": not created,
        }, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)
