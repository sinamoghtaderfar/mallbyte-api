"""Authorization is checked for every download; storage URLs never leave Django."""
from pathlib import Path

from django.http import FileResponse
from django.shortcuts import get_object_or_404
from rest_framework.exceptions import NotFound
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from apps.rbac.utils import has_permission
from apps.returns.models import ReturnAttachment, ReturnShipment


def can_manage_return_files(user):
    return has_permission(user, "view_all_returns")


def private_download(field):
    if not field:
        raise NotFound()
    try:
        response = FileResponse(field.open("rb"), as_attachment=True, filename=Path(field.name).name)
    except FileNotFoundError as exc:
        raise NotFound() from exc
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    return response


class ReturnAttachmentDownloadView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        attachment = get_object_or_404(
            ReturnAttachment.objects.select_related("return_request", "return_item__order_item__product"), pk=pk
        )
        claim = attachment.return_request
        customer_upload = attachment.uploaded_by_id == claim.customer_id
        customer_can_read = request.user.pk == claim.customer_id and customer_upload
        seller_can_read = bool(
            request.user.is_seller and customer_upload and attachment.return_item_id
            and attachment.return_item.return_request_id == claim.pk
            and attachment.return_item.order_item.product.seller_id == request.user.pk
        )
        if not (can_manage_return_files(request.user) or customer_can_read or seller_can_read):
            raise NotFound()
        return private_download(attachment.file)


class ReturnShippingLabelDownloadView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        shipment = get_object_or_404(ReturnShipment.objects.select_related("return_request"), pk=pk)
        if not (can_manage_return_files(request.user) or shipment.return_request.customer_id == request.user.pk):
            raise NotFound()
        return private_download(shipment.shipping_label)
