from rest_framework import serializers

from apps.analytics.models import (
    AnalyticsGeneratedReport,
    AnalyticsReportPeriod,
    AnalyticsReportSchedule,
    AnalyticsReportType,
)


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
class TimeSeriesQuerySerializer(serializers.Serializer):
    PERIOD_CHOICES = [
        ("today", "Today"),
        ("week", "Last 7 days"),
        ("month", "Last 30 days"),
        ("year", "Last 365 days"),
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
class AnalyticsBreakdownQuerySerializer(serializers.Serializer):
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
    limit = serializers.IntegerField(
        required=False,
        default=10,
        min_value=1,
        max_value=50,
    )

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
class AnalyticsAlertsQuerySerializer(serializers.Serializer):
    limit = serializers.IntegerField(
        required=False,
        default=10,
        min_value=1,
        max_value=50,
    )

class AnalyticsExportQuerySerializer(serializers.Serializer):
    REPORT_CHOICES = [
        ("sales", "Sales"),
        ("orders", "Orders"),
        ("payments", "Payments"),
        ("products", "Products"),
        ("support", "Support"),
        ("returns", "Returns"),
        ("reviews", "Reviews"),
    ]

    PERIOD_CHOICES = [
        ("today", "Today"),
        ("week", "Last 7 days"),
        ("month", "Last 30 days"),
        ("year", "Last 365 days"),
        ("all", "All time"),
    ]

    report = serializers.ChoiceField(
        choices=REPORT_CHOICES,
        required=False,
        default="sales",
    )

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
    
class AnalyticsReportScheduleSerializer(serializers.ModelSerializer):
    created_by_name = serializers.CharField(
        source="created_by.full_name",
        read_only=True,
    )

    class Meta:
        model = AnalyticsReportSchedule
        fields = [
            "id",
            "name",
            "report_types",
            "period",
            "frequency",
            "time_of_day",
            "day_of_week",
            "day_of_month",
            "every_n_days",
            "is_active",
            "last_run_at",
            "next_run_at",
            "created_by",
            "created_by_name",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "last_run_at",
            "next_run_at",
            "created_by",
            "created_by_name",
            "created_at",
            "updated_at",
        ]

    def validate_report_types(self, value):
        if not value:
            raise serializers.ValidationError(
                "At least one report type is required."
            )

        valid_report_types = {
            choice.value for choice in AnalyticsReportType
        }

        invalid_report_types = [
            report_type
            for report_type in value
            if report_type not in valid_report_types
        ]

        if invalid_report_types:
            raise serializers.ValidationError(
                f"Invalid report type(s): {invalid_report_types}"
            )

        return value

    def validate(self, attrs):
        frequency = attrs.get(
            "frequency",
            getattr(self.instance, "frequency", None),
        )

        day_of_week = attrs.get(
            "day_of_week",
            getattr(self.instance, "day_of_week", None),
        )

        day_of_month = attrs.get(
            "day_of_month",
            getattr(self.instance, "day_of_month", None),
        )

        every_n_days = attrs.get(
            "every_n_days",
            getattr(self.instance, "every_n_days", None),
        )

        if frequency == AnalyticsReportSchedule.FrequencyChoices.WEEKLY:
            if day_of_week is None:
                raise serializers.ValidationError(
                    {
                        "day_of_week": "This field is required for weekly schedules. Use 0=Monday and 6=Sunday."
                    }
                )

        if frequency == AnalyticsReportSchedule.FrequencyChoices.MONTHLY:
            if day_of_month is None:
                raise serializers.ValidationError(
                    {
                        "day_of_month": "This field is required for monthly schedules."
                    }
                )

        if frequency == AnalyticsReportSchedule.FrequencyChoices.EVERY_N_DAYS:
            if not every_n_days or every_n_days < 1:
                raise serializers.ValidationError(
                    {
                        "every_n_days": "This field must be greater than or equal to 1."
                    }
                )

        return attrs


class AnalyticsGeneratedReportSerializer(serializers.ModelSerializer):
    schedule_name = serializers.CharField(
        source="schedule.name",
        read_only=True,
    )
    generated_by_name = serializers.CharField(
        source="generated_by.full_name",
        read_only=True,
    )
    file_url = serializers.SerializerMethodField()

    class Meta:
        model = AnalyticsGeneratedReport
        fields = [
            "id",
            "schedule",
            "schedule_name",
            "report_type",
            "period",
            "status",
            "file",
            "file_url",
            "filename",
            "rows_count",
            "error_message",
            "task_id",
            "started_at",
            "completed_at",
            "generated_by",
            "generated_by_name",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    def get_file_url(self, obj):
        if not obj.file:
            return None

        request = self.context.get("request")

        if request:
            return request.build_absolute_uri(obj.file.url)

        return obj.file.url


class GenerateAnalyticsReportNowSerializer(serializers.Serializer):
    report_types = serializers.ListField(
        child=serializers.ChoiceField(
            choices=AnalyticsReportType.choices,
        ),
        allow_empty=False,
    )

    period = serializers.ChoiceField(
        choices=AnalyticsReportPeriod.choices,
        default=AnalyticsReportPeriod.YESTERDAY,
    )