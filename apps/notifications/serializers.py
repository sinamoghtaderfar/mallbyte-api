from rest_framework import serializers

from apps.notifications.models import Notification


class NotificationSerializer(serializers.ModelSerializer):
    user = serializers.StringRelatedField(read_only=True)

    class Meta:
        model = Notification
        fields = [
            "id",
            "user",
            "title",
            "message",
            "notification_type",
            "channel",
            "priority",
            "is_read",
            "read_at",
            "related_object_type",
            "related_object_id",
            "action_url",
            "metadata",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "user",
            "is_read",
            "read_at",
            "created_at",
            "updated_at",
        ]


class UnreadCountSerializer(serializers.Serializer):
    unread_count = serializers.IntegerField()


class MarkAllReadResponseSerializer(serializers.Serializer):
    marked_count = serializers.IntegerField()


class NotificationActionSerializer(serializers.Serializer):
    detail = serializers.CharField()
