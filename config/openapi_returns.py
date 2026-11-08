"""Contracts for return endpoints when their independently reviewed PRs exist."""
from importlib.util import find_spec

from drf_spectacular.extensions import OpenApiSerializerFieldExtension
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema, extend_schema_field
from rest_framework import serializers

from config.openapi import DetailErrorResponse, _document_view


@extend_schema_field(OpenApiTypes.BINARY)
class EvidenceFileField(serializers.FileField):
    """Schema-only multipart file bytes, rather than a response download link."""


if find_spec("apps.returns.private_media_views") is not None:
    for _name in ("ReturnAttachmentDownloadView", "ReturnShippingLabelDownloadView"):
        _document_view(f"apps.returns.private_media_views.{_name}", get=extend_schema(
            responses={
                (200, "*/*"): OpenApiResponse(OpenApiTypes.BINARY, description="Authorized attachment download; media type follows the stored file."),
                401: DetailErrorResponse, 404: DetailErrorResponse,
            },
            parameters=[
                OpenApiParameter("Cache-Control", str, OpenApiParameter.HEADER, response=[200], description="private, no-store"),
                OpenApiParameter("X-Content-Type-Options", str, OpenApiParameter.HEADER, response=[200], description="nosniff"),
            ],
            description="Download private return media after object authorization. Unauthorized object access is hidden with404; no public storage URL is returned.",
        ))


if find_spec("apps.returns.customer_workflows") is not None:
    from apps.returns.customer_workflows import EvidenceInput, TrackingInput

    from apps.returns.serializers import ReturnAttachmentSerializer, ReturnShipmentSerializer

    class EvidenceUploadInput(EvidenceInput):
        file = EvidenceFileField()

    _document_view("apps.returns.customer_workflows.ReturnEvidenceUploadView", post=extend_schema(
        request={"multipart/form-data": EvidenceUploadInput}, responses={201: ReturnAttachmentSerializer, 409: DetailErrorResponse},
        description="The return owner uploads private evidence, optionally linked to one of its own return items. Existing file-type/size validation applies.",
    ))
    _document_view("apps.returns.customer_workflows.CustomerReturnShipmentView", post=extend_schema(
        request=TrackingInput, responses={200: ReturnShipmentSerializer, 409: DetailErrorResponse},
        description="Submit tracking after return approval. An identical replay is idempotent; changing already-submitted tracking requires support.",
    ))


if find_spec("apps.returns.inventory_restoration") is not None:
    from apps.returns.inventory_restoration import RestorationInput

    class SaleabilityConfirmationSchema(OpenApiSerializerFieldExtension):
        target_class = "apps.returns.inventory_restoration.SaleabilityConfirmation"

        def map_serializer_field(self, auto_schema, direction):
            return {"type": "boolean", "enum": [True]}

    class InventoryRestorationResponse(serializers.Serializer):
        id = serializers.IntegerField()
        return_item = serializers.IntegerField()
        warehouse = serializers.IntegerField()
        quantity = serializers.IntegerField(min_value=1)
        movement = serializers.IntegerField()
        actor = serializers.IntegerField()
        note = serializers.CharField(allow_blank=True)
        created_at = serializers.DateTimeField()
        remaining_quantity = serializers.IntegerField(min_value=0)
        replayed = serializers.BooleanField()

    _document_view("apps.returns.inventory_restoration.ReturnInventoryRestorationView", post=extend_schema(
        request=RestorationInput, responses={200: InventoryRestorationResponse, 201: InventoryRestorationResponse, 409: DetailErrorResponse},
        description="Requires the explicit restock_returns permission, recorded physical receipt and literal sellable_confirmed=true after inspection. Restocks only the stated quantity into an active warehouse; no financial state changes. Same-key replays return200, newly recorded movements201.",
    ))
