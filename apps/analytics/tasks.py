import csv
import io

from celery import shared_task
from django.core.files.base import ContentFile
from django.db import transaction
from django.utils import timezone

from apps.analytics.models import (
    AnalyticsGeneratedReport,
    AnalyticsReportSchedule,
    AnalyticsReportType,
)
from apps.analytics.services import build_csv_export_data


@shared_task
def analytics_ping():
    return "Analytics Celery is working."


@shared_task(bind=True)
def generate_analytics_report(self, generated_report_id):
    report = AnalyticsGeneratedReport.objects.get(id=generated_report_id)

    report.mark_processing(task_id=self.request.id)

    try:
        export_data = build_csv_export_data(
            report=report.report_type,
            period=report.period,
        )

        headers = export_data.get("headers", [])
        rows = export_data.get("rows", [])
        filename = export_data.get("filename") or build_report_filename(report)

        csv_buffer = io.StringIO()
        writer = csv.writer(csv_buffer)

        writer.writerow(headers)

        for row in rows:
            writer.writerow(row)

        csv_content = csv_buffer.getvalue()
        file_content = ContentFile(csv_content.encode("utf-8"))

        report.file.save(filename, file_content, save=False)

        report.mark_success(
            file=report.file.name,
            filename=filename,
            rows_count=len(rows),
        )

        return {
            "report_id": str(report.id),
            "report_type": report.report_type,
            "status": report.status,
            "rows_count": report.rows_count,
        }

    except Exception as exc:
        report.mark_failed(str(exc))

        return {
            "report_id": str(report.id),
            "report_type": report.report_type,
            "status": report.status,
            "error": str(exc),
        }


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
                generate_analytics_report.delay(str(report.id))
                queued_reports += 1

            schedule.update_next_run()
            processed_schedules += 1

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