from concurrent.futures import ThreadPoolExecutor, TimeoutError
from threading import Event
from unittest import skipUnless
from unittest.mock import patch

from django.core.cache import cache
from django.db import close_old_connections, connection, connections
from django.test import TransactionTestCase
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient, APITestCase

from apps.accounts.models import User
from apps.support.models import SupportTicket, TicketAuditLog, TicketMessage


class SupportTransitionIntegrityTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.owner = User.objects.create_user(email="owner@example.com")
        self.admin = User.objects.create_superuser(email="admin@example.com", password="admin-password")
        self.ticket = SupportTicket.objects.create(customer=self.owner, subject="Help")
        self.client.force_authenticate(self.owner)

    def test_reply_audit_failure_rolls_back_message_and_status(self):
        with patch("apps.support.views.TicketAuditLog.log", side_effect=RuntimeError("audit unavailable")):
            with self.assertRaises(RuntimeError):
                self.client.post(f"/api/support/tickets/{self.ticket.pk}/reply/", {"message": "Reply"})
        self.assertFalse(TicketMessage.objects.filter(ticket=self.ticket).exists())
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, SupportTicket.StatusChoices.OPEN)
        self.assertIsNone(self.ticket.last_message_at)

    def test_close_notification_failure_rolls_back_status_and_audit(self):
        self.client.force_authenticate(self.admin)
        with patch("apps.support.views.create_support_notification", side_effect=RuntimeError("notification unavailable")):
            with self.assertRaises(RuntimeError):
                self.client.post(f"/api/support/tickets/{self.ticket.pk}/close/")
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, SupportTicket.StatusChoices.OPEN)
        self.assertIsNone(self.ticket.closed_at)
        self.assertFalse(TicketAuditLog.objects.filter(ticket=self.ticket).exists())

    def test_reply_projection_includes_the_new_message(self):
        self.ticket.mark_resolved()
        response = self.client.post(f"/api/support/tickets/{self.ticket.pk}/reply/", {"message": "More information"})
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["messages"][-1]["message"], "More information")
        self.ticket.refresh_from_db()
        self.assertIsNone(self.ticket.resolved_at)

    def test_embedded_history_is_bounded_and_full_history_is_paginated(self):
        TicketMessage.objects.bulk_create([
            TicketMessage(ticket=self.ticket, sender=self.owner, message=f"Message {index}") for index in range(55)
        ])
        TicketMessage.objects.create(ticket=self.ticket, sender=self.admin, message="Internal only", is_internal_note=True)
        response = self.client.get(f"/api/support/tickets/{self.ticket.pk}/")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(len(response.data["messages"]), 50)
        self.assertTrue(response.data["messages_truncated"])
        self.assertFalse(any(item["is_internal_note"] for item in response.data["messages"]))
        response = self.client.get(f"/api/support/tickets/{self.ticket.pk}/messages/")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["count"], 55)
        self.assertIsNotNone(response.data["next"])
        self.assertFalse(any(item["is_internal_note"] for item in response.data["results"]))

    def test_ticket_list_query_count_does_not_grow_per_ticket_or_message(self):
        def query_count():
            cache.clear()
            with CaptureQueriesContext(connection) as captured:
                response = self.client.get("/api/support/tickets/")
            self.assertEqual(response.status_code, 200, response.data)
            return len(captured)

        initial = query_count()
        for index in range(5):
            ticket = SupportTicket.objects.create(customer=self.owner, subject=f"Help {index}")
            TicketMessage.objects.create(ticket=ticket, sender=self.owner, message="Visible")
            TicketMessage.objects.create(ticket=ticket, sender=self.admin, message="Hidden", is_internal_note=True)
        self.assertLessEqual(query_count(), initial + 1)

    def test_audit_array_body_has_pagination_headers(self):
        self.client.force_authenticate(self.admin)
        TicketAuditLog.objects.bulk_create([
            TicketAuditLog(ticket=self.ticket, actor=self.admin, action="replied") for _ in range(30)
        ])
        response = self.client.get(f"/api/support/tickets/{self.ticket.pk}/audit-logs/")
        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(response.data, list)
        self.assertLess(len(response.data), 30)
        self.assertEqual(response["X-Total-Count"], "30")
        self.assertIn('rel="next"', response["Link"])

    def test_repeated_close_is_idempotent(self):
        self.client.force_authenticate(self.admin)
        first = self.client.post(f"/api/support/tickets/{self.ticket.pk}/close/")
        second = self.client.post(f"/api/support/tickets/{self.ticket.pk}/close/")
        self.assertEqual(first.status_code, 200, first.data)
        self.assertEqual(second.status_code, 200, second.data)
        self.assertEqual(first.data["closed_at"], second.data["closed_at"])
        self.assertEqual(self.ticket.audit_logs.filter(action="closed").count(), 1)

    def test_invalid_numeric_filters_return_validation_errors(self):
        for field in ("order", "product", "customer"):
            response = self.client.get("/api/support/tickets/", {field: "not-a-number"})
            self.assertEqual(response.status_code, 400, response.data)



@skipUnless(connection.vendor == "postgresql", "PostgreSQL row locks required")
class SupportReplyCloseConcurrencyTests(TransactionTestCase):
    def test_reply_waits_for_concurrent_close_then_is_rejected(self):
        owner = User.objects.create_user(email="owner@example.com")
        admin = User.objects.create_superuser(email="admin@example.com", password="admin-password")
        ticket = SupportTicket.objects.create(customer=owner, subject="Concurrent ticket")
        close_started = Event()
        reply_started = Event()
        release_close = Event()
        original_close = SupportTicket.close

        def held_close(instance):
            close_started.set()
            if not release_close.wait(timeout=10):
                raise AssertionError("Close was not released")
            return original_close(instance)

        def request(actor_id, action, payload=None):
            close_old_connections()
            try:
                client = APIClient()
                client.force_authenticate(User.objects.get(pk=actor_id))
                if action == "reply":
                    reply_started.set()
                return client.post(f"/api/support/tickets/{ticket.pk}/{action}/", payload or {}, format="json").status_code
            finally:
                connections.close_all()

        with patch.object(SupportTicket, "close", held_close), ThreadPoolExecutor(max_workers=2) as executor:
            closing = executor.submit(request, admin.pk, "close")
            self.assertTrue(close_started.wait(timeout=10))
            replying = executor.submit(request, owner.pk, "reply", {"message": "Racing reply"})
            self.assertTrue(reply_started.wait(timeout=10))
            try:
                with self.assertRaises(TimeoutError):
                    replying.result(timeout=0.25)
            finally:
                release_close.set()
            self.assertEqual(closing.result(timeout=10), 200)
            self.assertEqual(replying.result(timeout=10), 400)
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, SupportTicket.StatusChoices.CLOSED)
        self.assertFalse(ticket.messages.exists())
