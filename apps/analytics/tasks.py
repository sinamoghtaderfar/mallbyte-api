import csv
import io
import logging
from datetime import timedelta
from functools import partial

from celery import shared_task
from django.core.files.base import ContentFile
from django.db import OperationalError, transaction
from django.db.models import Q
from django.utils import timezone

from apps.analytics.models import (
    AnalyticsGeneratedReport,
    AnalyticsReportSchedule,
    AnalyticsReportType,
)
from apps.analytics.services import build_csv_export_data
from apps.common.exports import safe_spreadsheet_value

logger = logging.getLogger(__name__)


@shared_task
def analytics_ping():
    return "Analytics Celery is working."


@shared_task(bind=True, max_retries=3)
def generate_analytics_report(self, generated_report_id):
    report = None
    claim_started_at = None
    try:
        with transaction.atomic():
            report = AnalyticsGeneratedReport.objects.select_for_update().get(id=generated_report_id)
            fresh_claim = (report.status == report.StatusChoices.PROCESSING and report.started_at
                           and report.started_at > timezone.now() - timedelta(minutes=35))
            if report.status == report.StatusChoices.SUCCESS or fresh_claim:
                return {"report_id": str(report.id), "status": report.status, "rows_count": report.rows_count}
            report.mark_processing(task_id=self.request.id)
            claim_started_at = report.started_at
        export_data = build_csv_export_data(
            report=report.report_type,
            period=report.period,
            scheduled=True,
            at=report.created_at,
        )

        headers = export_data.get("headers", [])
        rows = export_data.get("rows", [])
        filename = export_data.get("filename") or build_report_filename(report)

        csv_buffer = io.StringIO()
        writer = csv.writer(csv_buffer)

        writer.writerow(headers)

        for row in rows:
            writer.writerow([safe_spreadsheet_value(value) for value in row])

        csv_content = csv_buffer.getvalue()
        file_content = ContentFile(csv_content.encode("utf-8"))

        with transaction.atomic():
            current = AnalyticsGeneratedReport.objects.select_for_update().get(pk=report.pk)
            # A worker recovered after the lease expired owns a new started_at.
            # The superseded worker must never publish a file or overwrite it.
            if current.status != current.StatusChoices.PROCESSING or current.started_at != claim_started_at:
                return {"report_id": str(current.id), "status": current.status, "rows_count": current.rows_count}
            current.file.save(filename, file_content, save=False)
            current.mark_success(file=current.file.name, filename=filename, rows_count=len(rows))
            report = current

        return {
            "report_id": str(report.id),
            "report_type": report.report_type,
            "status": report.status,
            "rows_count": report.rows_count,
        }

    except Exception as exc:
        if report and claim_started_at:
            try:
                now = timezone.now()
                AnalyticsGeneratedReport.objects.filter(
                    pk=report.pk, status=report.StatusChoices.PROCESSING, started_at=claim_started_at,
                ).update(status=report.StatusChoices.FAILED,
                         error_message=f"{type(exc).__name__}: report generation failed.",
                         completed_at=now, updated_at=now)
            except OperationalError:
                pass
        if isinstance(exc, (OperationalError, OSError)):
            raise self.retry(exc=exc, countdown=min(60 * 2 ** self.request.retries, 600)) from exc
        raise


def queue_report(report_id):
    """A failed broker publish leaves a durable pending row for the scheduler."""
    try:
        generate_analytics_report.delay(str(report_id))
    except Exception as exc:
        logger.error("Analytics report dispatch failed: %s", type(exc).__name__)
    finally:
        AnalyticsGeneratedReport.objects.filter(pk=report_id).update(updated_at=timezone.now())


@shared_task
def run_due_analytics_report_schedules():
    now = timezone.now()

    due_schedule_ids = list(
        AnalyticsReportSchedule.objects.filter(
            is_active=True,
            next_run_at__lte=now,
        )
        .values_list("id", flat=True)[:50]
    )

    queued_reports = 0
    processed_schedules = 0

    for schedule_id in due_schedule_ids:
        with transaction.atomic():
            schedule = (
                AnalyticsReportSchedule.objects.select_for_update()
                .filter(
                    id=schedule_id,
                    is_active=True,
                    next_run_at__lte=now,
                )
                .first()
            )

            if not schedule:
                continue

            created_reports = create_reports_for_schedule(schedule)

            for report in created_reports:
                transaction.on_commit(partial(queue_report, str(report.id)))
                queued_reports += 1

            schedule.update_next_run()
            processed_schedules += 1

    # Recover committed jobs whose broker dispatch failed and workers that died
    # beyond the configured 30-minute task limit. Claims prevent duplicate work.
    abandoned = AnalyticsGeneratedReport.objects.filter(
        Q(status=AnalyticsGeneratedReport.StatusChoices.PENDING, updated_at__lte=now - timedelta(minutes=5))
        | Q(status=AnalyticsGeneratedReport.StatusChoices.PROCESSING, started_at__lte=now - timedelta(minutes=35))
    ).order_by("updated_at").values_list("pk", flat=True)[:50]
    for report_id in abandoned:
        transaction.on_commit(partial(queue_report, str(report_id)))
        queued_reports += 1

    return {
        "processed_schedules": processed_schedules,
        "queued_reports": queued_reports,
    }


def create_reports_for_schedule(schedule, generated_by=None):
    valid_report_types = {
        choice.value for choice in AnalyticsReportType
    }

    report_types = [
        report_type
        for report_type in schedule.report_types
        if report_type in valid_report_types
    ]

    reports = []

    for report_type in report_types:
        report = AnalyticsGeneratedReport.objects.create(
            schedule=schedule,
            report_type=report_type,
            period=schedule.period,
            generated_by=generated_by,
        )
        reports.append(report)

    return reports


def build_report_filename(report):
    timestamp = timezone.now().strftime("%Y%m%d_%H%M%S")
    return f"analytics_{report.report_type}_{report.period}_{timestamp}.csv"
