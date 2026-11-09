from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APITestCase

from apps.accounts.models import User
from apps.notifications.models import Notification
from apps.notifications.serializers import NotificationIdsSerializer
from apps.notifications.services import (
    mark_all_notifications_as_read,
    mark_notification_as_read,
    mark_selected_notifications_as_read,
    mark_selected_notifications_as_unread,
)


class NotificationOwnershipTests(APITestCase):
    def setUp(self):
        self.owner = User.objects.create_user(email="owner@example.test", full_name="Owner")
        self.staff = User.objects.create_user(email="staff@example.test", full_name="Staff", is_staff=True)
        self.notification = Notification.objects.create(user=self.owner, title="Private", message="Private order")
        self.client.force_authenticate(self.staff)

    def test_unrelated_staff_cannot_read_delete_or_change_notifications(self):
        detail = reverse("notification-detail", args=[self.notification.pk])
        self.assertEqual(self.client.get(detail).status_code, 404)
        self.assertEqual(self.client.delete(detail).status_code, 404)
        self.assertEqual(self.client.post(reverse("notification-mark-read", args=[self.notification.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse("notification-list")).data["count"], 0)
        with self.assertRaises(PermissionError):
            mark_notification_as_read(notification=self.notification, user=self.staff)

    def test_nonstring_preferences_are_validation_errors(self):
        for field in ["muted_channels", "muted_notification_types"]:
            for value in [[{}], [[]], [True]]:
                with self.subTest(field=field, value=value):
                    response = self.client.post(reverse("notification-preferences"), {field: value}, format="json")
                    self.assertEqual(response.status_code, 400)


class NotificationBulkTests(TestCase):
    def test_bulk_updates_use_one_query_and_preserve_ownership_and_timestamps(self):
        user = User.objects.create_user(email="bulk@example.test", full_name="Bulk")
        other = User.objects.create_user(email="other@example.test", full_name="Other")
        Notification.objects.bulk_create([Notification(user=user, title="T", message="M") for _ in range(30)])
        foreign = Notification.objects.create(user=other, title="Other", message="M")
        with self.assertNumQueries(1):
            self.assertEqual(mark_all_notifications_as_read(user=user), 30)
        ids = list(Notification.objects.filter(user=user).values_list("pk", flat=True))
        with self.assertNumQueries(1):
            self.assertEqual(mark_selected_notifications_as_unread(user=user, notification_ids=[*ids, foreign.pk]), 30)
        with self.assertNumQueries(1):
            self.assertEqual(mark_selected_notifications_as_read(user=user, notification_ids=[*ids, foreign.pk]), 30)
        self.assertFalse(Notification.objects.filter(user=user, read_at__isnull=True).exists())
        foreign.refresh_from_db()
        self.assertFalse(foreign.is_read)

    def test_bulk_ids_reject_booleans_and_excessive_input(self):
        for ids in [[True], list(range(1, 1002))]:
            self.assertFalse(NotificationIdsSerializer(data={"ids": ids}).is_valid())
