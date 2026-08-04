from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone
from rest_framework import serializers

from apps.support.notifications import create_support_notification
from apps.support.models import SupportTicket, TicketMessage

User = get_user_model()


class TicketMessageSerializer(serializers.ModelSerializer):
    sender_display = serializers.CharField(source="sender.full_name", read_only=True)

    class Meta:
        model = TicketMessage
        fields = [
            "id",
            "ticket",
            "sender",
            "sender_display",
            "message",
            "is_internal_note",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "ticket",
            "sender",
            "sender_display",
            "created_at",
            "updated_at",
        ]


class SupportTicketSerializer(serializers.ModelSerializer):
    customer_display = serializers.CharField(source="customer.full_name", read_only=True)
    assigned_to_display = serializers.CharField(source="assigned_to.full_name", read_only=True)
    messages = serializers.SerializerMethodField()
    initial_message = serializers.CharField(write_only=True, required=True)

    class Meta:
        model = SupportTicket
        fields = [
            "id",
            "ticket_number",
            "customer",
            "customer_display",
            "assigned_to",
            "assigned_to_display",
            "subject",
            "category",
            "priority",
            "status",
            "order",
            "product",
            "return_request",
            "last_message_at",
            "resolved_at",
            "closed_at",
            "messages",
            "initial_message",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "ticket_number",
            "customer",
            "customer_display",
            "assigned_to",
            "assigned_to_display",
            "status",
            "last_message_at",
            "resolved_at",
            "closed_at",
            "messages",
            "created_at",
            "updated_at",
        ]

    def get_messages(self, obj):
        request = self.context.get("request")
        messages = obj.messages.all()

        if not (
            request
            and request.user.is_authenticated
            and (request.user.is_staff or request.user.is_superuser)
        ):
            messages = messages.filter(is_internal_note=False)

        return TicketMessageSerializer(messages, many=True).data

    def validate(self, attrs):
        request = self.context.get("request")

        if request is None or request.user.is_anonymous:
            raise serializers.ValidationError("Authentication is required.")

        order = attrs.get("order")
        return_request = attrs.get("return_request")

        if order and not (request.user.is_staff or request.user.is_superuser):
            if order.user_id != request.user.id:
                raise serializers.ValidationError(
                    "You can only create tickets for your own orders."
                )

        if return_request and not (request.user.is_staff or request.user.is_superuser):
            if return_request.customer_id != request.user.id:
                raise serializers.ValidationError(
                    "You can only create tickets for your own return requests."
                )

        return attrs

    @transaction.atomic
    def create(self, validated_data):
        request = self.context["request"]
        initial_message = validated_data.pop("initial_message")

        ticket = SupportTicket.objects.create(
            customer=request.user,
            last_message_at=timezone.now(),
            **validated_data,
        )

        TicketMessage.objects.create(
            ticket=ticket,
            sender=request.user,
            message=initial_message,
        )
        
        create_support_notification(
            user=ticket.customer,
            ticket=ticket,
            template_key="support_ticket_created",
            ticket_number=ticket.ticket_number,
        )

        return ticket


class TicketReplySerializer(serializers.Serializer):
    message = serializers.CharField()
    is_internal_note = serializers.BooleanField(required=False, default=False)

    def validate(self, attrs):
        request = self.context.get("request")
        is_internal_note = attrs.get("is_internal_note", False)

        if is_internal_note and not (
            request
            and request.user.is_authenticated
            and (request.user.is_staff or request.user.is_superuser)
        ):
            raise serializers.ValidationError(
                "Only support staff can create internal notes."
            )

        return attrs


class TicketAssignSerializer(serializers.Serializer):
    assigned_to = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.filter(is_staff=True)
    )