"""Customer evidence and tracking submissions, serialized with return transitions."""
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers
from rest_framework.exceptions import APIException
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle
from rest_framework.views import APIView

from apps.returns.models import ReturnAttachment, ReturnItem, ReturnRequest, ReturnShipment, ReturnStatusHistory
from apps.returns.serializers import ReturnAttachmentSerializer, ReturnShipmentSerializer
from apps.support.attachment_validation import validate_support_attachment


class ReturnConflict(APIException):
    status_code = 409
    default_detail = "The return no longer permits this operation."


class EvidenceThrottle(UserRateThrottle):
    scope = "return_evidence"
    rate = "20/hour"


class EvidenceInput(serializers.Serializer):
    file = serializers.FileField(validators=[validate_support_attachment])
    return_item = serializers.IntegerField(min_value=1, required=False)
    attachment_type = serializers.ChoiceField(choices=ReturnAttachment.AttachmentType.choices, required=False)
    caption = serializers.CharField(max_length=255, required=False, allow_blank=True)


class TrackingInput(serializers.Serializer):
    carrier = serializers.CharField(max_length=100)
    tracking_number = serializers.CharField(max_length=120)
    tracking_url = serializers.URLField(required=False, allow_blank=True)

    def validate_tracking_url(self, value):
        if value and urlsplit(value).scheme != "https":
            raise serializers.ValidationError("Use an HTTPS tracking URL.")
        return value


class ReturnEvidenceUploadView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]
    throttle_classes = [EvidenceThrottle]

    def post(self, request, pk):
        data = EvidenceInput(data=request.data)
        data.is_valid(raise_exception=True)
        attachment = None
        try:
            with transaction.atomic():
                claim = get_object_or_404(ReturnRequest.objects.select_for_update(), pk=pk, customer=request.user)
                if claim.status in {ReturnRequest.Status.REJECTED, ReturnRequest.Status.REFUNDED,
                                    ReturnRequest.Status.REPLACED, ReturnRequest.Status.CANCELLED, ReturnRequest.Status.CLOSED}:
                    raise ReturnConflict()
                values = dict(data.validated_data)
                item_id = values.pop("return_item", None)
                item = None
                if item_id is not None:
                    item = ReturnItem.objects.filter(pk=item_id, return_request=claim).first()
                    if item is None:
                        raise serializers.ValidationError({"return_item": "Select an item belonging to this return."})
                upload = values.pop("file")
                # Keep original names out of persistent paths and stay within the
                # model FileField length even for long browser-supplied names.
                filename = uuid4().hex + Path(upload.name).suffix.lower()
                attachment = ReturnAttachment(return_request=claim, return_item=item, uploaded_by=request.user, **values)
                attachment.file.save(filename, upload, save=False)
                attachment.save()
                ReturnStatusHistory.objects.create(
                    return_request=claim, old_status=claim.status, new_status=claim.status,
                    changed_by=request.user, note="Customer added private return evidence.",
                )
        except Exception:
            # Database rollback cannot undo a newly written private file.
            if attachment is not None and attachment.file:
                attachment.file.storage.delete(attachment.file.name)
            raise
        return Response(ReturnAttachmentSerializer(attachment, context={"request": request}).data, status=201)


class CustomerReturnShipmentView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def post(self, request, pk):
        data = TrackingInput(data=request.data)
        data.is_valid(raise_exception=True)
        values = dict(data.validated_data)
        values.setdefault("tracking_url", "")
        with transaction.atomic():
            claim = get_object_or_404(ReturnRequest.objects.select_for_update(), pk=pk, customer=request.user)
            if claim.status not in {ReturnRequest.Status.APPROVED, ReturnRequest.Status.WAITING_FOR_ITEM}:
                raise ReturnConflict("Return approval is required before submitting a shipment.")
            shipment, _ = ReturnShipment.objects.get_or_create(return_request=claim)
            if shipment.received_at:
                raise ReturnConflict("The shipment has already been received.")
            if shipment.shipped_at:
                if any(getattr(shipment, key) != value for key, value in values.items()):
                    raise ReturnConflict("Tracking was already submitted. Contact support to correct it.")
                return Response(ReturnShipmentSerializer(shipment, context={"request": request}).data)
            for key, value in values.items():
                setattr(shipment, key, value)
            shipment.shipped_at = timezone.now()
            shipment.save(update_fields=[*values, "shipped_at", "updated_at"])
            old_status = claim.status
            claim.status = ReturnRequest.Status.WAITING_FOR_ITEM
            claim.save(update_fields=["status", "updated_at"])
            ReturnStatusHistory.objects.create(
                return_request=claim, old_status=old_status, new_status=claim.status,
                changed_by=request.user, note="Customer submitted return shipment tracking.",
            )
        return Response(ReturnShipmentSerializer(shipment, context={"request": request}).data)
