from django.db.models import Q
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.support.models import SupportTicket, TicketMessage
from apps.support.permissions import (
    IsSupportStaff,
    IsTicketParticipantOrSupportStaff,
)
from apps.support.serializers import (
    SupportTicketSerializer,
    TicketAssignSerializer,
    TicketReplySerializer,
)


class SupportTicketViewSet(viewsets.ModelViewSet):
    serializer_class = SupportTicketSerializer
    permission_classes = [IsAuthenticated, IsTicketParticipantOrSupportStaff]
    http_method_names = ["get", "post", "put", "patch", "delete", "head", "options"]

    def get_queryset(self):
        user = self.request.user

        queryset = (
            SupportTicket.objects.select_related(
                "customer",
                "assigned_to",
                "order",
                "product",
                "return_request",
            )
            .prefetch_related("messages")
            .all()
        )

        if user.is_staff or user.is_superuser:
            return queryset

        return queryset.filter(customer=user)

    def get_permissions(self):
        if self.action in ["assign", "resolve", "close", "reopen"]:
            return [IsAuthenticated(), IsSupportStaff()]

        return super().get_permissions()

    @action(
        detail=True,
        methods=["post"],
        url_path="reply",
        permission_classes=[IsAuthenticated, IsTicketParticipantOrSupportStaff],
    )
    def reply(self, request, pk=None):
        ticket = self.get_object()

        if ticket.status == SupportTicket.StatusChoices.CLOSED:
            return Response(
                {"detail": "Cannot reply to a closed ticket. Reopen it first."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = TicketReplySerializer(
            data=request.data,
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)

        is_internal_note = serializer.validated_data.get("is_internal_note", False)

        TicketMessage.objects.create(
            ticket=ticket,
            sender=request.user,
            message=serializer.validated_data["message"],
            is_internal_note=is_internal_note,
        )

        update_fields = ["updated_at"]

        if not is_internal_note:
            ticket.last_message_at = timezone.now()
            update_fields.append("last_message_at")

            if request.user.is_staff or request.user.is_superuser:
                ticket.status = SupportTicket.StatusChoices.PENDING
            else:
                ticket.status = SupportTicket.StatusChoices.OPEN

            update_fields.append("status")

        ticket.save(update_fields=update_fields)

        response_serializer = self.get_serializer(ticket)

        return Response(response_serializer.data, status=status.HTTP_201_CREATED)

    @action(
        detail=True,
        methods=["post"],
        url_path="assign",
        permission_classes=[IsAuthenticated, IsSupportStaff],
    )
    def assign(self, request, pk=None):
        ticket = self.get_object()

        serializer = TicketAssignSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        ticket.assigned_to = serializer.validated_data["assigned_to"]
        ticket.save(update_fields=["assigned_to", "updated_at"])

        response_serializer = self.get_serializer(ticket)

        return Response(response_serializer.data, status=status.HTTP_200_OK)

    @action(
        detail=True,
        methods=["post"],
        url_path="resolve",
        permission_classes=[IsAuthenticated, IsSupportStaff],
    )
    def resolve(self, request, pk=None):
        ticket = self.get_object()
        ticket.mark_resolved()

        serializer = self.get_serializer(ticket)

        return Response(serializer.data, status=status.HTTP_200_OK)

    @action(
        detail=True,
        methods=["post"],
        url_path="close",
        permission_classes=[IsAuthenticated, IsSupportStaff],
    )
    def close(self, request, pk=None):
        ticket = self.get_object()
        ticket.close()

        serializer = self.get_serializer(ticket)

        return Response(serializer.data, status=status.HTTP_200_OK)

    @action(
        detail=True,
        methods=["post"],
        url_path="reopen",
        permission_classes=[IsAuthenticated, IsSupportStaff],
    )
    def reopen(self, request, pk=None):
        ticket = self.get_object()
        ticket.reopen()

        serializer = self.get_serializer(ticket)

        return Response(serializer.data, status=status.HTTP_200_OK)