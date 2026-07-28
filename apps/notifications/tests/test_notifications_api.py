from typing import Any, cast

from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from apps.accounts.models import User
from apps.notifications.models import Notification
from apps.notifications.services import create_notification


class NotificationAPITests(APITestCase):
    def create_test_user(
        self,
        *,
        phone,
        email,
        full_name,
        password="testpass123",
        is_staff=False,
        is_superuser=False,
    ):
        user = User(
            phone=phone,
            email=email,
            full_name=full_name,
            is_active=True,
            is_staff=is_staff,
            is_superuser=is_superuser,
        )
        user.set_password(password)
        user.save()
        return user

    def setUp(self):
        self.user = self.create_test_user(
            phone="+989300000001",
            email="notification_user@example.com",
            full_name="Notification User",
        )

        self.other_user = self.create_test_user(
            phone="+989300000002",
            email="other_notification_user@example.com",
            full_name="Other Notification User",
        )

        self.admin_user = self.create_test_user(
            phone="+989300000003",
            email="notification_admin@example.com",
            full_name="Notification Admin",
            is_staff=True,
            is_superuser=True,
        )

        self.notification = create_notification(
            user=self.user,
            title="Order created",
            message="Your order has been created.",
            notification_type=Notification.NotificationType.ORDER,
            priority=Notification.Priority.NORMAL,
            related_object_type="order",
            related_object_id="1",
            action_url="/orders/1/",
        )

        self.read_notification = create_notification(
            user=self.user,
            title="Payment successful",
            message="Your payment was successful.",
            notification_type=Notification.NotificationType.PAYMENT,
            priority=Notification.Priority.HIGH,
            related_object_type="payment",
            related_object_id="1",
        )
        self.read_notification.mark_as_read()

        self.other_notification = create_notification(
            user=self.other_user,
            title="Other user notification",
            message="This notification belongs to another user.",
            notification_type=Notification.NotificationType.PRODUCT,
        )

    def get_api_client(self) -> APIClient:
        return cast(APIClient, self.client)

    def authenticate_user(self):
        self.get_api_client().force_authenticate(user=self.user)

    def authenticate_admin(self):
        self.get_api_client().force_authenticate(user=self.admin_user)

    def get_response_items(self, response) -> list[dict[str, Any]]:
        data = response.json()

        if isinstance(data, dict) and "results" in data:
            results = data["results"]
            if isinstance(results, list):
                return results
            return []

        if isinstance(data, list):
            return data

        return []

    def test_user_can_list_only_own_notifications(self):
        self.authenticate_user()

        url = reverse("notification-list")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        items = self.get_response_items(response)
        ids = [item["id"] for item in items]

        self.assertIn(self.notification.pk, ids)
        self.assertIn(self.read_notification.pk, ids)
        self.assertNotIn(self.other_notification.pk, ids)

    def test_user_can_retrieve_own_notification(self):
        self.authenticate_user()

        url = reverse("notification-detail", args=[self.notification.pk])
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()

        self.assertEqual(data["id"], self.notification.pk)
        self.assertEqual(data["title"], "Order created")
        self.assertEqual(data["message"], "Your order has been created.")
        self.assertEqual(data["notification_type"], Notification.NotificationType.ORDER)
        self.assertEqual(data["priority"], Notification.Priority.NORMAL)
        self.assertEqual(data["is_read"], False)

    def test_user_cannot_retrieve_other_user_notification(self):
        self.authenticate_user()

        url = reverse("notification-detail", args=[self.other_notification.pk])
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_unread_count_returns_only_current_user_unread_notifications(self):
        self.authenticate_user()

        url = reverse("notification-unread-count")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()

        self.assertEqual(data["unread_count"], 1)

    def test_user_can_mark_notification_as_read(self):
        self.authenticate_user()

        url = reverse("notification-mark-read", args=[self.notification.pk])
        response = self.client.post(url, data={}, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.notification.refresh_from_db()

        data = response.json()

        self.assertTrue(self.notification.is_read)
        self.assertIsNotNone(self.notification.read_at)
        self.assertEqual(data["is_read"], True)

    def test_user_can_mark_notification_as_unread(self):
        self.authenticate_user()

        self.assertTrue(self.read_notification.is_read)

        url = reverse("notification-mark-unread", args=[self.read_notification.pk])
        response = self.client.post(url, data={}, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.read_notification.refresh_from_db()

        data = response.json()

        self.assertFalse(self.read_notification.is_read)
        self.assertIsNone(self.read_notification.read_at)
        self.assertEqual(data["is_read"], False)

    def test_user_can_mark_all_own_notifications_as_read(self):
        self.authenticate_user()

        second_unread = create_notification(
            user=self.user,
            title="Shipping update",
            message="Your order has been shipped.",
            notification_type=Notification.NotificationType.SHIPPING,
        )

        url = reverse("notification-mark-all-read")
        response = self.client.post(url, data={}, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()

        self.assertEqual(data["marked_count"], 2)

        self.notification.refresh_from_db()
        second_unread.refresh_from_db()
        self.other_notification.refresh_from_db()

        self.assertTrue(self.notification.is_read)
        self.assertTrue(second_unread.is_read)

        # Other user's notification must not be changed.
        self.assertFalse(self.other_notification.is_read)

    def test_admin_can_list_all_notifications(self):
        self.authenticate_admin()

        url = reverse("notification-list")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        items = self.get_response_items(response)
        ids = [item["id"] for item in items]

        self.assertIn(self.notification.pk, ids)
        self.assertIn(self.read_notification.pk, ids)
        self.assertIn(self.other_notification.pk, ids)

    def test_user_can_filter_notifications_by_is_read_false(self):
        unread_notification = Notification.objects.create(
            user=self.user,
            title="Unread notification",
            message="Unread message",
            notification_type=Notification.NotificationType.ORDER,
            priority=Notification.Priority.NORMAL,
            is_read=False,
        )

        read_notification = Notification.objects.create(
            user=self.user,
            title="Read notification",
            message="Read message",
            notification_type=Notification.NotificationType.ORDER,
            priority=Notification.Priority.NORMAL,
            is_read=True,
        )

        self.get_api_client().force_authenticate(user=self.user)

        url = reverse("notification-list")

        response = self.client.get(url, {"is_read": "false"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        items = self.get_response_items(response)
        titles = [item["title"] for item in items]

        self.assertIn(unread_notification.title, titles)
        self.assertNotIn(read_notification.title, titles)

    def test_user_can_filter_notifications_by_is_read_true(self):
        unread_notification = Notification.objects.create(
            user=self.user,
            title="Unread notification",
            message="Unread message",
            notification_type=Notification.NotificationType.ORDER,
            priority=Notification.Priority.NORMAL,
            is_read=False,
        )

        read_notification = Notification.objects.create(
            user=self.user,
            title="Read notification",
            message="Read message",
            notification_type=Notification.NotificationType.ORDER,
            priority=Notification.Priority.NORMAL,
            is_read=True,
        )

        self.get_api_client().force_authenticate(user=self.user)

        url = reverse("notification-list")

        response = self.client.get(url, {"is_read": "true"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        items = self.get_response_items(response)
        titles = [item["title"] for item in items]

        self.assertIn(read_notification.title, titles)
        self.assertNotIn(unread_notification.title, titles)

    def test_user_can_filter_notifications_by_notification_type(self):
        product_notification = Notification.objects.create(
            user=self.user,
            title="Product notification",
            message="Product message",
            notification_type=Notification.NotificationType.PRODUCT,
            priority=Notification.Priority.NORMAL,
        )

        order_notification = Notification.objects.create(
            user=self.user,
            title="Order notification",
            message="Order message",
            notification_type=Notification.NotificationType.ORDER,
            priority=Notification.Priority.NORMAL,
        )

        self.get_api_client().force_authenticate(user=self.user)

        url = reverse("notification-list")

        response = self.client.get(
            url,
            {"notification_type": Notification.NotificationType.PRODUCT},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        items = self.get_response_items(response)
        titles = [item["title"] for item in items]

        self.assertIn(product_notification.title, titles)
        self.assertNotIn(order_notification.title, titles)

    def test_user_can_filter_notifications_by_priority(self):
        high_notification = Notification.objects.create(
            user=self.user,
            title="High priority notification",
            message="High priority message",
            notification_type=Notification.NotificationType.ORDER,
            priority=Notification.Priority.HIGH,
        )

        normal_notification = Notification.objects.create(
            user=self.user,
            title="Normal priority notification",
            message="Normal priority message",
            notification_type=Notification.NotificationType.ORDER,
            priority=Notification.Priority.NORMAL,
        )

        self.get_api_client().force_authenticate(user=self.user)

        url = reverse("notification-list")

        response = self.client.get(
            url,
            {"priority": Notification.Priority.HIGH},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        items = self.get_response_items(response)
        titles = [item["title"] for item in items]

        self.assertIn(high_notification.title, titles)
        self.assertNotIn(normal_notification.title, titles)

    def test_user_can_filter_notifications_by_channel(self):
        in_app_notification = Notification.objects.create(
            user=self.user,
            title="In-app notification",
            message="In-app message",
            notification_type=Notification.NotificationType.ORDER,
            channel=Notification.Channel.IN_APP,
            priority=Notification.Priority.NORMAL,
        )

        email_notification = Notification.objects.create(
            user=self.user,
            title="Email notification",
            message="Email message",
            notification_type=Notification.NotificationType.ORDER,
            channel=Notification.Channel.EMAIL,
            priority=Notification.Priority.NORMAL,
        )

        self.get_api_client().force_authenticate(user=self.user)

        url = reverse("notification-list")

        response = self.client.get(
            url,
            {"channel": Notification.Channel.IN_APP},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        items = self.get_response_items(response)
        titles = [item["title"] for item in items]

        self.assertIn(in_app_notification.title, titles)
        self.assertNotIn(email_notification.title, titles)

    def test_user_can_delete_own_notification(self):
        notification = Notification.objects.create(
            user=self.user,
            title="Delete me",
            message="This notification should be deleted.",
            notification_type=Notification.NotificationType.SYSTEM,
            priority=Notification.Priority.NORMAL,
        )

        self.get_api_client().force_authenticate(user=self.user)

        url = reverse("notification-detail", args=[notification.pk])

        response = self.client.delete(url)

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

        self.assertFalse(Notification.objects.filter(pk=notification.pk).exists())

    def test_user_cannot_delete_other_user_notification(self):
        notification = Notification.objects.create(
            user=self.other_user,
            title="Other user notification",
            message="This belongs to another user.",
            notification_type=Notification.NotificationType.SYSTEM,
            priority=Notification.Priority.NORMAL,
        )

        self.get_api_client().force_authenticate(user=self.user)

        url = reverse("notification-detail", args=[notification.pk])

        response = self.client.delete(url)

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

        self.assertTrue(Notification.objects.filter(pk=notification.pk).exists())

    def test_user_can_clear_read_notifications(self):
        read_notification_1 = Notification.objects.create(
            user=self.user,
            title="Read notification 1",
            message="Read message 1",
            notification_type=Notification.NotificationType.SYSTEM,
            priority=Notification.Priority.NORMAL,
            is_read=True,
        )

        read_notification_2 = Notification.objects.create(
            user=self.user,
            title="Read notification 2",
            message="Read message 2",
            notification_type=Notification.NotificationType.SYSTEM,
            priority=Notification.Priority.NORMAL,
            is_read=True,
        )

        unread_notification = Notification.objects.create(
            user=self.user,
            title="Unread notification",
            message="Unread message",
            notification_type=Notification.NotificationType.SYSTEM,
            priority=Notification.Priority.NORMAL,
            is_read=False,
        )

        other_user_read_notification = Notification.objects.create(
            user=self.other_user,
            title="Other user read notification",
            message="Other user read message",
            notification_type=Notification.NotificationType.SYSTEM,
            priority=Notification.Priority.NORMAL,
            is_read=True,
        )

        expected_deleted_count = Notification.objects.filter(
            user=self.user,
            is_read=True,
        ).count()

        self.get_api_client().force_authenticate(user=self.user)

        url = reverse("notification-clear-read")

        response = self.client.delete(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()

        self.assertEqual(data["deleted_count"], expected_deleted_count)

        self.assertFalse(
            Notification.objects.filter(pk=read_notification_1.pk).exists()
        )
        self.assertFalse(
            Notification.objects.filter(pk=read_notification_2.pk).exists()
        )

        self.assertTrue(Notification.objects.filter(pk=unread_notification.pk).exists())
        self.assertTrue(
            Notification.objects.filter(pk=other_user_read_notification.pk).exists()
        )

    def test_user_can_clear_all_own_notifications(self):
        notification_1 = Notification.objects.create(
            user=self.user,
            title="Notification 1",
            message="Message 1",
            notification_type=Notification.NotificationType.SYSTEM,
            priority=Notification.Priority.NORMAL,
            is_read=True,
        )

        notification_2 = Notification.objects.create(
            user=self.user,
            title="Notification 2",
            message="Message 2",
            notification_type=Notification.NotificationType.ORDER,
            priority=Notification.Priority.HIGH,
            is_read=False,
        )

        other_user_notification = Notification.objects.create(
            user=self.other_user,
            title="Other user notification",
            message="Other user message",
            notification_type=Notification.NotificationType.SYSTEM,
            priority=Notification.Priority.NORMAL,
            is_read=True,
        )

        expected_deleted_count = Notification.objects.filter(
            user=self.user,
        ).count()

        self.get_api_client().force_authenticate(user=self.user)

        url = reverse("notification-clear-all")

        response = self.client.delete(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()

        self.assertEqual(data["deleted_count"], expected_deleted_count)

        self.assertFalse(Notification.objects.filter(pk=notification_1.pk).exists())
        self.assertFalse(Notification.objects.filter(pk=notification_2.pk).exists())

        self.assertTrue(
            Notification.objects.filter(pk=other_user_notification.pk).exists()
        )

        self.assertFalse(Notification.objects.filter(user=self.user).exists())

    def test_user_can_get_notification_summary(self):
        Notification.objects.create(
            user=self.user,
            title="Order notification",
            message="Order message",
            notification_type=Notification.NotificationType.ORDER,
            priority=Notification.Priority.NORMAL,
            is_read=False,
        )

        Notification.objects.create(
            user=self.user,
            title="Product notification",
            message="Product message",
            notification_type=Notification.NotificationType.PRODUCT,
            priority=Notification.Priority.HIGH,
            is_read=True,
        )

        Notification.objects.create(
            user=self.user,
            title="System notification",
            message="System message",
            notification_type=Notification.NotificationType.SYSTEM,
            priority=Notification.Priority.NORMAL,
            is_read=False,
        )

        Notification.objects.create(
            user=self.other_user,
            title="Other user notification",
            message="Other user message",
            notification_type=Notification.NotificationType.ORDER,
            priority=Notification.Priority.URGENT,
            is_read=False,
        )

        user_notifications = Notification.objects.filter(user=self.user)

        expected_by_type = {}
        for notification_type in user_notifications.values_list(
            "notification_type",
            flat=True,
        ):
            expected_by_type[notification_type] = (
                expected_by_type.get(notification_type, 0) + 1
            )

        expected_by_priority = {}
        for priority in user_notifications.values_list("priority", flat=True):
            expected_by_priority[priority] = expected_by_priority.get(priority, 0) + 1

        self.get_api_client().force_authenticate(user=self.user)

        url = reverse("notification-summary")

        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()

        self.assertEqual(data["total_count"], user_notifications.count())
        self.assertEqual(
            data["unread_count"],
            user_notifications.filter(is_read=False).count(),
        )
        self.assertEqual(
            data["read_count"],
            user_notifications.filter(is_read=True).count(),
        )
        self.assertEqual(data["by_type"], expected_by_type)
        self.assertEqual(data["by_priority"], expected_by_priority)

    def test_user_cannot_create_notification_directly_from_api(self):
        self.get_api_client().force_authenticate(user=self.user)

        before_count = Notification.objects.count()

        url = reverse("notification-list")

        response = self.client.post(
            url,
            data={
                "title": "Fake notification",
                "message": "User should not be able to create this.",
                "notification_type": Notification.NotificationType.SYSTEM,
                "priority": Notification.Priority.NORMAL,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

        data = response.json()

        self.assertEqual(
            data["detail"],
            "Creating notifications directly is not allowed.",
        )

        self.assertEqual(Notification.objects.count(), before_count)

    def test_user_can_mark_selected_notifications_as_read(self):
        notification_1 = Notification.objects.create(
            user=self.user,
            title="Selected notification 1",
            message="Message 1",
            notification_type=Notification.NotificationType.SYSTEM,
            priority=Notification.Priority.NORMAL,
            is_read=False,
        )

        notification_2 = Notification.objects.create(
            user=self.user,
            title="Selected notification 2",
            message="Message 2",
            notification_type=Notification.NotificationType.ORDER,
            priority=Notification.Priority.NORMAL,
            is_read=False,
        )

        notification_not_selected = Notification.objects.create(
            user=self.user,
            title="Not selected notification",
            message="Message 3",
            notification_type=Notification.NotificationType.SYSTEM,
            priority=Notification.Priority.NORMAL,
            is_read=False,
        )

        other_user_notification = Notification.objects.create(
            user=self.other_user,
            title="Other user notification",
            message="Other user message",
            notification_type=Notification.NotificationType.SYSTEM,
            priority=Notification.Priority.NORMAL,
            is_read=False,
        )

        self.get_api_client().force_authenticate(user=self.user)

        url = reverse("notification-mark-selected-read")

        response = self.client.post(
            url,
            data={
                "ids": [
                    notification_1.pk,
                    notification_2.pk,
                    other_user_notification.pk,
                ],
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()

        self.assertEqual(data["marked_count"], 2)

        notification_1.refresh_from_db()
        notification_2.refresh_from_db()
        notification_not_selected.refresh_from_db()
        other_user_notification.refresh_from_db()

        self.assertTrue(notification_1.is_read)
        self.assertTrue(notification_2.is_read)

        self.assertFalse(notification_not_selected.is_read)
        self.assertFalse(other_user_notification.is_read)

    def test_mark_selected_read_requires_ids_to_be_list(self):
        self.get_api_client().force_authenticate(user=self.user)

        url = reverse("notification-mark-selected-read")

        response = self.client.post(
            url,
            data={
                "ids": "not-a-list",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        data = response.json()

        self.assertEqual(data["detail"], "ids must be a list.")

    def test_user_can_delete_selected_notifications(self):
        notification_1 = Notification.objects.create(
            user=self.user,
            title="Delete selected notification 1",
            message="Message 1",
            notification_type=Notification.NotificationType.SYSTEM,
            priority=Notification.Priority.NORMAL,
            is_read=False,
        )

        notification_2 = Notification.objects.create(
            user=self.user,
            title="Delete selected notification 2",
            message="Message 2",
            notification_type=Notification.NotificationType.ORDER,
            priority=Notification.Priority.HIGH,
            is_read=True,
        )

        notification_not_selected = Notification.objects.create(
            user=self.user,
            title="Not selected notification",
            message="Message 3",
            notification_type=Notification.NotificationType.SYSTEM,
            priority=Notification.Priority.NORMAL,
            is_read=False,
        )

        other_user_notification = Notification.objects.create(
            user=self.other_user,
            title="Other user notification",
            message="Other user message",
            notification_type=Notification.NotificationType.SYSTEM,
            priority=Notification.Priority.NORMAL,
            is_read=False,
        )

        self.get_api_client().force_authenticate(user=self.user)

        url = reverse("notification-delete-selected")

        response = self.client.post(
            url,
            data={
                "ids": [
                    notification_1.pk,
                    notification_2.pk,
                    other_user_notification.pk,
                ],
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()

        self.assertEqual(data["deleted_count"], 2)

        self.assertFalse(Notification.objects.filter(pk=notification_1.pk).exists())
        self.assertFalse(Notification.objects.filter(pk=notification_2.pk).exists())

        self.assertTrue(
            Notification.objects.filter(pk=notification_not_selected.pk).exists()
        )
        self.assertTrue(
            Notification.objects.filter(pk=other_user_notification.pk).exists()
        )

    def test_delete_selected_requires_ids_to_be_list(self):
        self.get_api_client().force_authenticate(user=self.user)

        url = reverse("notification-delete-selected")

        response = self.client.post(
            url,
            data={
                "ids": "not-a-list",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        data = response.json()

        self.assertEqual(data["detail"], "ids must be a list.")

    def test_user_can_mark_selected_notifications_as_unread(self):
        notification_1 = Notification.objects.create(
            user=self.user,
            title="Selected read notification 1",
            message="Message 1",
            notification_type=Notification.NotificationType.SYSTEM,
            priority=Notification.Priority.NORMAL,
            is_read=True,
        )

        notification_2 = Notification.objects.create(
            user=self.user,
            title="Selected read notification 2",
            message="Message 2",
            notification_type=Notification.NotificationType.ORDER,
            priority=Notification.Priority.HIGH,
            is_read=True,
        )

        notification_not_selected = Notification.objects.create(
            user=self.user,
            title="Not selected read notification",
            message="Message 3",
            notification_type=Notification.NotificationType.SYSTEM,
            priority=Notification.Priority.NORMAL,
            is_read=True,
        )

        already_unread_notification = Notification.objects.create(
            user=self.user,
            title="Already unread notification",
            message="Message 4",
            notification_type=Notification.NotificationType.SYSTEM,
            priority=Notification.Priority.NORMAL,
            is_read=False,
        )

        other_user_notification = Notification.objects.create(
            user=self.other_user,
            title="Other user read notification",
            message="Other user message",
            notification_type=Notification.NotificationType.SYSTEM,
            priority=Notification.Priority.NORMAL,
            is_read=True,
        )

        self.get_api_client().force_authenticate(user=self.user)

        url = reverse("notification-mark-selected-unread")

        response = self.client.post(
            url,
            data={
                "ids": [
                    notification_1.pk,
                    notification_2.pk,
                    already_unread_notification.pk,
                    other_user_notification.pk,
                ],
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()

        self.assertEqual(data["marked_count"], 2)

        notification_1.refresh_from_db()
        notification_2.refresh_from_db()
        notification_not_selected.refresh_from_db()
        already_unread_notification.refresh_from_db()
        other_user_notification.refresh_from_db()

        self.assertFalse(notification_1.is_read)
        self.assertFalse(notification_2.is_read)

        self.assertTrue(notification_not_selected.is_read)
        self.assertFalse(already_unread_notification.is_read)
        self.assertTrue(other_user_notification.is_read)

    def test_mark_selected_unread_requires_ids_to_be_list(self):
        self.get_api_client().force_authenticate(user=self.user)

        url = reverse("notification-mark-selected-unread")

        response = self.client.post(
            url,
            data={
                "ids": "not-a-list",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        data = response.json()

        self.assertEqual(data["detail"], "ids must be a list.")

    def test_user_can_get_notification_preferences(self):
        self.get_api_client().force_authenticate(user=self.user)

        url = reverse("notification-preferences")

        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()

        self.assertEqual(data["user"], str(self.user))
        self.assertEqual(data["muted_notification_types"], [])
        self.assertEqual(data["muted_channels"], [])
        self.assertTrue(data["email_enabled"])
        self.assertTrue(data["sms_enabled"])
        self.assertTrue(data["push_enabled"])
        self.assertTrue(data["in_app_enabled"])

    def test_user_can_get_notification_preferences(self):
        self.get_api_client().force_authenticate(user=self.user)

        url = reverse("notification-preferences")

        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()

        self.assertEqual(data["user"], str(self.user))
        self.assertEqual(data["muted_notification_types"], [])
        self.assertEqual(data["muted_channels"], [])
        self.assertTrue(data["email_enabled"])
        self.assertTrue(data["sms_enabled"])
        self.assertTrue(data["push_enabled"])
        self.assertTrue(data["in_app_enabled"])

    def test_user_can_update_notification_preferences(self):
        self.get_api_client().force_authenticate(user=self.user)

        url = reverse("notification-preferences")

        response = self.client.post(
            url,
            data={
                "muted_notification_types": [
                    Notification.NotificationType.PRODUCT,
                    Notification.NotificationType.INVENTORY,
                ],
                "muted_channels": [
                    Notification.Channel.EMAIL,
                ],
                "email_enabled": False,
                "sms_enabled": True,
                "push_enabled": True,
                "in_app_enabled": True,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()

        self.assertEqual(
            data["muted_notification_types"],
            [
                Notification.NotificationType.PRODUCT,
                Notification.NotificationType.INVENTORY,
            ],
        )
        self.assertEqual(
            data["muted_channels"],
            [
                Notification.Channel.EMAIL,
            ],
        )
        self.assertFalse(data["email_enabled"])
        self.assertTrue(data["sms_enabled"])
        self.assertTrue(data["push_enabled"])
        self.assertTrue(data["in_app_enabled"])

    def test_invalid_muted_notification_type_returns_bad_request(self):
        self.get_api_client().force_authenticate(user=self.user)

        url = reverse("notification-preferences")

        response = self.client.post(
            url,
            data={
                "muted_notification_types": [
                    "invalid_type",
                ],
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        data = response.json()

        self.assertIn("muted_notification_types", data)

    def test_invalid_muted_channel_returns_bad_request(self):
        self.get_api_client().force_authenticate(user=self.user)

        url = reverse("notification-preferences")

        response = self.client.post(
            url,
            data={
                "muted_channels": [
                    "invalid_channel",
                ],
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        data = response.json()

        self.assertIn("muted_channels", data)

    def test_mark_selected_read_rejects_empty_ids_list(self):
        self.get_api_client().force_authenticate(user=self.user)

        url = reverse("notification-mark-selected-read")

        response = self.client.post(
            url,
            data={
                "ids": [],
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        data = response.json()

        self.assertEqual(data["detail"], "ids cannot be empty.")

    def test_mark_selected_read_rejects_non_integer_ids(self):
        self.get_api_client().force_authenticate(user=self.user)

        url = reverse("notification-mark-selected-read")

        response = self.client.post(
            url,
            data={
                "ids": [1, "2", 3],
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        data = response.json()

        self.assertEqual(data["detail"], "ids must contain integers only.")

    def test_mark_selected_read_rejects_negative_ids(self):
        self.get_api_client().force_authenticate(user=self.user)

        url = reverse("notification-mark-selected-read")

        response = self.client.post(
            url,
            data={
                "ids": [1, -2, 3],
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        data = response.json()

        self.assertEqual(data["detail"], "ids must contain positive integers only.")

    def test_mark_selected_read_removes_duplicate_ids(self):
        notification_1 = Notification.objects.create(
            user=self.user,
            title="Duplicate notification 1",
            message="Message 1",
            notification_type=Notification.NotificationType.SYSTEM,
            priority=Notification.Priority.NORMAL,
            is_read=False,
        )

        notification_2 = Notification.objects.create(
            user=self.user,
            title="Duplicate notification 2",
            message="Message 2",
            notification_type=Notification.NotificationType.ORDER,
            priority=Notification.Priority.NORMAL,
            is_read=False,
        )

        self.get_api_client().force_authenticate(user=self.user)

        url = reverse("notification-mark-selected-read")

        response = self.client.post(
            url,
            data={
                "ids": [
                    notification_1.pk,
                    notification_1.pk,
                    notification_2.pk,
                    notification_2.pk,
                ],
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()

        self.assertEqual(data["marked_count"], 2)

        notification_1.refresh_from_db()
        notification_2.refresh_from_db()

        self.assertTrue(notification_1.is_read)
        self.assertTrue(notification_2.is_read)
