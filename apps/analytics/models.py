import calendar
import uuid
from datetime import datetime, timedelta

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone


def analytics_report_upload_path(instance, filename):
    now = timezone.now()
    return f"analytics/reports/{now:%Y/%m/%d}/{filename}"


class AnalyticsReportType(models.TextChoices):
    SALES = "sales", "Sales"
    ORDERS = "orders", "Orders"
    PAYMENTS = "payments", "Payments"
    PRODUCTS = "products", "Products"
    SUPPORT = "support", "Support"
    RETURNS = "returns", "Returns"
    REVIEWS = "reviews", "Reviews"


class AnalyticsReportPeriod(models.TextChoices):
    YESTERDAY = "yesterday", "Yesterday"
    LAST_7_DAYS = "last_7_days", "Last 7 Days"
    LAST_30_DAYS = "last_30_days", "Last 30 Days"
    THIS_MONTH = "this_month", "This Month"
    PREVIOUS_MONTH = "previous_month", "Previous Month"
    ALL = "all", "All Time"


class AnalyticsReportSchedule(models.Model):
    class FrequencyChoices(models.TextChoices):
        DAILY = "daily", "Daily"
        WEEKLY = "weekly", "Weekly"
        MONTHLY = "monthly", "Monthly"
        EVERY_N_DAYS = "every_n_days", "Every N Days"

    name = models.CharField(max_length=120)

    report_types = models.JSONField(
        default=list,
        blank=True,
        help_text="Example: ['sales', 'orders', 'payments']",
    )

    period = models.CharField(
        max_length=30,
        choices=AnalyticsReportPeriod.choices,
        default=AnalyticsReportPeriod.YESTERDAY,
        db_index=True,
    )

    frequency = models.CharField(
        max_length=30,
        choices=FrequencyChoices.choices,
        default=FrequencyChoices.DAILY,
        db_index=True,
    )

    time_of_day = models.TimeField(
        default="02:00",
        help_text="Time of day when the report should be generated.",
    )

    day_of_week = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        validators=[
            MinValueValidator(0),
            MaxValueValidator(6),
        ],
        help_text="0=Monday, 6=Sunday. Used for weekly schedules.",
    )

    day_of_month = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        validators=[
            MinValueValidator(1),
            MaxValueValidator(31),
        ],
        help_text="Used for monthly schedules.",
    )

    every_n_days = models.PositiveSmallIntegerField(
        default=3,
        validators=[
            MinValueValidator(1),
            MaxValueValidator(365),
        ],
        help_text="Used when frequency is every_n_days.",
    )

    is_active = models.BooleanField(default=True, db_index=True)

    last_run_at = models.DateTimeField(null=True, blank=True)
    next_run_at = models.DateTimeField(null=True, blank=True, db_index=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_analytics_report_schedules",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Analytics Report Schedule"
        verbose_name_plural = "Analytics Report Schedules"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["is_active", "next_run_at"]),
            models.Index(fields=["frequency"]),
            models.Index(fields=["period"]),
        ]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.report_types:
            self.report_types = [
                AnalyticsReportType.SALES,
                AnalyticsReportType.ORDERS,
                AnalyticsReportType.PAYMENTS,
            ]

        if not self.next_run_at:
            self.next_run_at = self.calculate_next_run()

        super().save(*args, **kwargs)

    def calculate_next_run(self, after=None):
        after = after or timezone.now()

        if self.frequency == self.FrequencyChoices.DAILY:
            return self._calculate_daily_next_run(after)

        if self.frequency == self.FrequencyChoices.WEEKLY:
            return self._calculate_weekly_next_run(after)

        if self.frequency == self.FrequencyChoices.MONTHLY:
            return self._calculate_monthly_next_run(after)

        if self.frequency == self.FrequencyChoices.EVERY_N_DAYS:
            return self._calculate_every_n_days_next_run(after)

        return self._calculate_daily_next_run(after)

    def update_next_run(self):
        self.last_run_at = timezone.now()
        self.next_run_at = self.calculate_next_run(after=self.last_run_at)
        self.save(
            update_fields=[
                "last_run_at",
                "next_run_at",
                "updated_at",
            ]
        )

    def _make_aware_datetime(self, run_date):
        current_timezone = timezone.get_current_timezone()
        run_datetime = datetime.combine(run_date, self.time_of_day)

        if timezone.is_naive(run_datetime):
            run_datetime = timezone.make_aware(
                run_datetime,
                current_timezone,
            )

        return run_datetime

    def _calculate_daily_next_run(self, after):
        candidate = self._make_aware_datetime(after.date())

        if candidate <= after:
            candidate += timedelta(days=1)

        return candidate

    def _calculate_weekly_next_run(self, after):
        target_day = self.day_of_week

        if target_day is None:
            target_day = 0

        days_ahead = target_day - after.weekday()

        if days_ahead < 0:
            days_ahead += 7

        candidate_date = after.date() + timedelta(days=days_ahead)
        candidate = self._make_aware_datetime(candidate_date)

        if candidate <= after:
            candidate += timedelta(days=7)

        return candidate

    def _calculate_monthly_next_run(self, after):
        target_day = self.day_of_month or 1

        candidate = self._monthly_candidate(
            year=after.year,
            month=after.month,
            target_day=target_day,
        )

        if candidate <= after:
            next_year = after.year
            next_month = after.month + 1

            if next_month > 12:
                next_month = 1
                next_year += 1

            candidate = self._monthly_candidate(
                year=next_year,
                month=next_month,
                target_day=target_day,
            )

        return candidate

    def _monthly_candidate(self, *, year, month, target_day):
        last_day = calendar.monthrange(year, month)[1]
        safe_day = min(target_day, last_day)
        candidate_date = datetime(year, month, safe_day).date()

        return self._make_aware_datetime(candidate_date)

    def _calculate_every_n_days_next_run(self, after):
        days = self.every_n_days or 1

        if self.last_run_at:
            candidate_date = self.last_run_at.date() + timedelta(days=days)
        else:
            candidate_date = after.date()

        candidate = self._make_aware_datetime(candidate_date)

        while candidate <= after:
            candidate += timedelta(days=days)

        return candidate


class AnalyticsGeneratedReport(models.Model):
    class StatusChoices(models.TextChoices):
        PENDING = "pending", "Pending"
        PROCESSING = "processing", "Processing"
        SUCCESS = "success", "Success"
        FAILED = "failed", "Failed"

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    schedule = models.ForeignKey(
        AnalyticsReportSchedule,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="generated_reports",
    )

    report_type = models.CharField(
        max_length=30,
        choices=AnalyticsReportType.choices,
        db_index=True,
    )

    period = models.CharField(
        max_length=30,
        choices=AnalyticsReportPeriod.choices,
        default=AnalyticsReportPeriod.YESTERDAY,
        db_index=True,
    )

    status = models.CharField(
        max_length=30,
        choices=StatusChoices.choices,
        default=StatusChoices.PENDING,
        db_index=True,
    )

    file = models.FileField(
        upload_to=analytics_report_upload_path,
        null=True,
        blank=True,
    )

    filename = models.CharField(max_length=255, blank=True)
    rows_count = models.PositiveIntegerField(default=0)

    error_message = models.TextField(blank=True)
    task_id = models.CharField(max_length=255, blank=True)

    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    generated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="generated_analytics_reports",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Analytics Generated Report"
        verbose_name_plural = "Analytics Generated Reports"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["report_type"]),
            models.Index(fields=["period"]),
            models.Index(fields=["-created_at"]),
        ]

    def __str__(self):
        return f"{self.report_type} - {self.status} - {self.created_at:%Y-%m-%d}"

    def mark_processing(self, task_id=""):
        self.status = self.StatusChoices.PROCESSING
        self.task_id = task_id or self.task_id
        self.started_at = timezone.now()
        self.save(
            update_fields=[
                "status",
                "task_id",
                "started_at",
                "updated_at",
            ]
        )

    def mark_success(self, *, file, filename, rows_count):
        now = timezone.now()

        self.status = self.StatusChoices.SUCCESS
        self.file = file
        self.filename = filename
        self.rows_count = rows_count
        self.completed_at = now
        self.error_message = ""

        self.save(
            update_fields=[
                "status",
                "file",
                "filename",
                "rows_count",
                "completed_at",
                "error_message",
                "updated_at",
            ]
        )

    def mark_failed(self, error_message):
        self.status = self.StatusChoices.FAILED
        self.error_message = str(error_message)
        self.completed_at = timezone.now()

        self.save(
            update_fields=[
                "status",
                "error_message",
                "completed_at",
                "updated_at",
            ]
        )