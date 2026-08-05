from rest_framework import serializers


class DashboardQuerySerializer(serializers.Serializer):
    PERIOD_CHOICES = [
        ("today", "Today"),
        ("week", "Last 7 days"),
        ("month", "Last 30 days"),
        ("year", "Last 365 days"),
        ("all", "All time"),
    ]

    period = serializers.ChoiceField(
        choices=PERIOD_CHOICES,
        required=False,
        default="month",
    )
    start_date = serializers.DateField(required=False)
    end_date = serializers.DateField(required=False)

    def validate(self, attrs):
        start_date = attrs.get("start_date")
        end_date = attrs.get("end_date")

        if bool(start_date) != bool(end_date):
            raise serializers.ValidationError(
                "Both start_date and end_date are required for custom date range."
            )

        if start_date and end_date and start_date > end_date:
            raise serializers.ValidationError(
                "start_date cannot be after end_date."
            )

        return attrs