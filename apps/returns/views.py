from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.returns.models import ReturnRequest
from apps.returns.serializers import (
    ReturnActionSerializer,
    ReturnApproveSerializer,
    ReturnRequestCreateSerializer,
    ReturnRequestDetailSerializer,
    ReturnRequestListSerializer,
)
from apps.returns.services import (
    approve_return_request,
    cancel_return_request,
    is_admin_user,
    mark_return_item_received,
    mark_return_refunded,
    reject_return_request,
)


class ReturnRequestViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        queryset = ReturnRequest.objects.select_related(
            "customer", "order", "reviewed_by"
        ).prefetch_related(
            "items",
            "items__order_item",
            "attachments",
            "status_history",
        )

        if is_admin_user(self.request.user):
            return queryset.all()

        return queryset.filter(customer=self.request.user)

    def get_serializer_class(self):
        if self.action == "create":
            return ReturnRequestCreateSerializer

        if self.action == "list":
            return ReturnRequestListSerializer

        if self.action == "approve":
            return ReturnApproveSerializer

        if self.action in ["cancel", "reject", "mark_received", "mark_refunded"]:
            return ReturnActionSerializer

        return ReturnRequestDetailSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(
            data=request.data,
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)

        try:
            return_request = serializer.save()
        except DjangoValidationError as exc:
            return Response(
                {"detail": exc.messages if hasattr(exc, "messages") else str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        response_serializer = ReturnRequestDetailSerializer(return_request)
        return Response(response_serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], url_path="cancel")
    def cancel(self, request, pk=None):
        return_request = self.get_object()

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            return_request = cancel_return_request(
                return_request=return_request,
                user=request.user,
                note=serializer.validated_data.get("note", ""),
            )
        except DjangoValidationError as exc:
            return Response(
                {"detail": exc.messages if hasattr(exc, "messages") else str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        response_serializer = ReturnRequestDetailSerializer(return_request)
        return Response(response_serializer.data, status=status.HTTP_200_OK)

    @action(detail=True, methods=["post"], url_path="approve")
    def approve(self, request, pk=None):
        if not is_admin_user(request.user):
            return Response(
                {"detail": "Only admins can approve return requests."},
                status=status.HTTP_403_FORBIDDEN,
            )

        return_request = self.get_object()

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            return_request = approve_return_request(
                return_request=return_request,
                user=request.user,
                note=serializer.validated_data.get("note", ""),
                approved_amount=serializer.validated_data.get("approved_amount"),
            )
        except DjangoValidationError as exc:
            return Response(
                {"detail": exc.messages if hasattr(exc, "messages") else str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        response_serializer = ReturnRequestDetailSerializer(return_request)
        return Response(response_serializer.data, status=status.HTTP_200_OK)

    @action(detail=True, methods=["post"], url_path="reject")
    def reject(self, request, pk=None):
        if not is_admin_user(request.user):
            return Response(
                {"detail": "Only admins can reject return requests."},
                status=status.HTTP_403_FORBIDDEN,
            )

        return_request = self.get_object()

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            return_request = reject_return_request(
                return_request=return_request,
                user=request.user,
                note=serializer.validated_data.get("note", ""),
            )
        except DjangoValidationError as exc:
            return Response(
                {"detail": exc.messages if hasattr(exc, "messages") else str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        response_serializer = ReturnRequestDetailSerializer(return_request)
        return Response(response_serializer.data, status=status.HTTP_200_OK)

    @action(detail=True, methods=["post"], url_path="mark-received")
    def mark_received(self, request, pk=None):
        if not is_admin_user(request.user):
            return Response(
                {"detail": "Only admins can mark return requests as received."},
                status=status.HTTP_403_FORBIDDEN,
            )

        return_request = self.get_object()

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            return_request = mark_return_item_received(
                return_request=return_request,
                user=request.user,
                note=serializer.validated_data.get("note", ""),
            )
        except DjangoValidationError as exc:
            return Response(
                {"detail": exc.messages if hasattr(exc, "messages") else str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        response_serializer = ReturnRequestDetailSerializer(return_request)
        return Response(response_serializer.data, status=status.HTTP_200_OK)

    @action(detail=True, methods=["post"], url_path="mark-refunded")
    def mark_refunded(self, request, pk=None):
        if not is_admin_user(request.user):
            return Response(
                {"detail": "Only admins can mark return requests as refunded."},
                status=status.HTTP_403_FORBIDDEN,
            )

        return_request = self.get_object()

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            return_request = mark_return_refunded(
                return_request=return_request,
                user=request.user,
                note=serializer.validated_data.get("note", ""),
            )
        except DjangoValidationError as exc:
            return Response(
                {"detail": exc.messages if hasattr(exc, "messages") else str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        response_serializer = ReturnRequestDetailSerializer(return_request)
        return Response(response_serializer.data, status=status.HTTP_200_OK)
