from django.shortcuts import get_object_or_404
from django.db.models import F, Prefetch
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response

from apps.returns.models import ReturnAttachment, ReturnItem, ReturnRequest
from apps.returns.serializers import (
    ReturnActionSerializer,
    ReturnApproveSerializer,
    CustomerReturnRequestDetailSerializer,
    SellerReturnRequestListSerializer,
    SellerReturnRequestDetailSerializer,
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


class ReturnRequestViewSet(
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
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
        if self.action == "seller":
            return SellerReturnRequestListSerializer
        if self.action == "seller_detail":
            return SellerReturnRequestDetailSerializer
        if self.action == "retrieve" and not is_admin_user(self.request.user):
            return CustomerReturnRequestDetailSerializer
        if self.action == "create":
            return ReturnRequestCreateSerializer

        if self.action == "list":
            return ReturnRequestListSerializer

        if self.action == "approve":
            return ReturnApproveSerializer

        if self.action in ["cancel", "reject", "mark_received", "mark_refunded"]:
            return ReturnActionSerializer

        return ReturnRequestDetailSerializer

    def _detail_response(self, obj, *, response_status=status.HTTP_200_OK):
        serializer_class = (
            ReturnRequestDetailSerializer
            if is_admin_user(self.request.user)
            else CustomerReturnRequestDetailSerializer
        )
        serializer = serializer_class(obj, context=self.get_serializer_context())
        return Response(serializer.data, status=response_status)

    @staticmethod
    def _require_seller(user):
        if not getattr(user, "is_seller", False):
            raise PermissionDenied("Only sellers can access seller returns.")

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

        return self._detail_response(
            return_request, response_status=status.HTTP_201_CREATED
        )


    def _get_seller_return_queryset(self):
        seller_id = self.request.user.pk
        own_items = (
            ReturnItem.objects.filter(order_item__product__seller_id=seller_id)
            .select_related("order_item")
            .order_by("pk")
        )
        own_attachments = (
            ReturnAttachment.objects.filter(
                return_item__order_item__product__seller_id=seller_id,
                uploaded_by_id=F("return_request__customer_id"),
            )
            .order_by("-created_at")
        )
        return (
            ReturnRequest.objects.select_related("customer", "order", "reviewed_by")
            .filter(items__order_item__product__seller_id=seller_id)
            .distinct()
            .prefetch_related(
                Prefetch("items", queryset=own_items, to_attr="seller_visible_items"),
                Prefetch(
                    "attachments", queryset=own_attachments,
                    to_attr="seller_visible_attachments",
                ),
                "status_history",
            )
        )

    @action(detail=False, methods=["get"], url_path="seller")
    def seller(self, request):
        self._require_seller(request.user)
        queryset = self.filter_queryset(
            self._get_seller_return_queryset().order_by("-created_at")
        )

        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=["get"], url_path="seller-detail")
    def seller_detail(self, request, pk=None):
        self._require_seller(request.user)
        return_request = get_object_or_404(
            self._get_seller_return_queryset(),
            pk=pk,
        )

        serializer = self.get_serializer(return_request)
        return Response(serializer.data)

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

        return self._detail_response(return_request)

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

        return self._detail_response(return_request)

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

        return self._detail_response(return_request)

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

        return self._detail_response(return_request)

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

        return self._detail_response(return_request)
