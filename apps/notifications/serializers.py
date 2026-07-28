from rest_framework import serializers

from apps.notifications.models import Notification, NotificationPreference


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


class NotificationPreferenceSerializer(serializers.ModelSerializer):
    user = serializers.StringRelatedField(read_only=True)

    class Meta:
        model = NotificationPreference
        fields = [
            "id",
            "user",
            "muted_notification_types",
            "muted_channels",
            "email_enabled",
            "sms_enabled",
            "push_enabled",
            "in_app_enabled",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "user",
            "created_at",
            "updated_at",
        ]

    def validate_muted_notification_types(self, value):
        if not isinstance(value, list):
            raise serializers.ValidationError(
                "muted_notification_types must be a list."
            )

        valid_types = {choice[0] for choice in Notification.NotificationType.choices}

        invalid_types = [item for item in value if item not in valid_types]

        if invalid_types:
            raise serializers.ValidationError(
                f"Invalid notification types: {invalid_types}"
            )

        return value

    def validate_muted_channels(self, value):
        if not isinstance(value, list):
            raise serializers.ValidationError("muted_channels must be a list.")

        valid_channels = {choice[0] for choice in Notification.Channel.choices}

        invalid_channels = [item for item in value if item not in valid_channels]

        if invalid_channels:
            raise serializers.ValidationError(f"Invalid channels: {invalid_channels}")

        return value


class NotificationIdsSerializer(serializers.Serializer):
    ids = serializers.JSONField()

    def validate_ids(self, value):
        if not isinstance(value, list):
            raise serializers.ValidationError("ids must be a list.")

        if not value:
            raise serializers.ValidationError("ids cannot be empty.")

        cleaned_ids = []

        for item in value:
            if not isinstance(item, int):
                raise serializers.ValidationError("ids must contain integers only.")

            if item <= 0:
                raise serializers.ValidationError(
                    "ids must contain positive integers only."
                )

            if item not in cleaned_ids:
                cleaned_ids.append(item)

        return cleaned_ids
