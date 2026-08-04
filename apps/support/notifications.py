from apps.notifications.services import create_notification
from apps.notifications.templates import render_notification_template


def create_support_notification(*, user, ticket, template_key, metadata=None, **context):
    if metadata is None:
        metadata = {}

    template_data = render_notification_template(template_key, **context)

    return create_notification(
        user=user,
        title=template_data["title"],
        message=template_data["message"],
        notification_type=template_data["notification_type"],
        priority=template_data["priority"],
        related_object_type="support_ticket",
        related_object_id=str(ticket.pk),
        action_url=f"/support/tickets/{ticket.pk}/",
        metadata={
            "ticket_id": ticket.pk,
            "ticket_number": ticket.ticket_number,
            "template_key": template_key,
            **metadata,
        },
    )