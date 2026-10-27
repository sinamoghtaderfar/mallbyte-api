"""Regression for editorial RBAC, publishing and safe navigation contracts."""

from datetime import timedelta

from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.accounts.models import User
from apps.content.models import (
    ContentPage,
    NavigationItem,
    NavigationMenu,
)
from apps.observability.models import AuditLog
from apps.rbac.models import Role
from apps.rbac.utils import (
    assign_role,
    clear_user_permissions_cache,
    remove_role,
)


class CMSHardeningTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser(
            email="cms-super@example.com", full_name="Super", password="testpass123"
        )
        cls.editor = User.objects.create_user(
            email="cms-editor@example.com", full_name="Editor", password="testpass123"
        )
        cls.publisher = User.objects.create_user(
            email="cms-publisher@example.com",
            full_name="Publisher",
            password="testpass123",
        )
        cls.manager = User.objects.create_user(
            email="cms-manager@example.com", full_name="Manager", password="testpass123"
        )
        cls.viewer = User.objects.create_user(
            email="cms-viewer@example.com", full_name="Viewer", password="testpass123"
        )
        cls.staff = User.objects.create_user(
            email="cms-staff@example.com",
            full_name="Unprivileged Staff",
            password="testpass123",
            is_staff=True,
        )
        for user, role in [
            (cls.editor, "content_editor"),
            (cls.publisher, "content_publisher"),
            (cls.manager, "content_manager"),
            (cls.viewer, "content_viewer"),
        ]:
            assign_role(user, Role.objects.get(name=role))
        cls.page = ContentPage.objects.create(
            title="Draft Article",
            slug="draft-article",
            content="Draft text",
            status="draft",
        )
        cls.menu = NavigationMenu.objects.create(
            name="Primary", slug="primary", placement="header"
        )

    def _reset_permission_cache(self):
        for user in (
            self.admin,
            self.editor,
            self.publisher,
            self.manager,
            self.viewer,
            self.staff,
        ):
            clear_user_permissions_cache(user)

    def setUp(self):
        super().setUp()
        self._reset_permission_cache()

    def tearDown(self):
        try:
            self._reset_permission_cache()
        finally:
            super().tearDown()

    def auth(self, who=None):
        self.client.force_authenticate(user=who)

    def page_url(self):
        return reverse("content-page-detail", args=[self.page.slug])

    def test_public_cannot_read_draft_but_viewer_can(self):
        self.auth()
        self.assertEqual(self.client.get(self.page_url()).status_code, 404)
        self.auth(self.viewer)
        res = self.client.get(self.page_url())
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res["Cache-Control"], "private, no-store")
        self.assertEqual(
            self.client.patch(self.page_url(), {"title": "No"}).status_code, 403
        )

    def test_editor_can_manage_draft_but_cannot_publish(self):
        self.auth(self.editor)
        res = self.client.patch(self.page_url(), {"title": "Edited"}, format="json")
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(
            self.client.post(
                reverse("content-page-publish", args=[self.page.slug])
            ).status_code,
            403,
        )
        # Users cannot smuggle a status transition inside PATCH or POST.
        self.assertEqual(
            self.client.patch(
                self.page_url(), {"status": "published"}, format="json"
            ).status_code,
            400,
        )
        self.assertEqual(
            self.client.post(
                reverse("content-page-list"),
                {
                    "title": "Bad",
                    "content": "foo",
                    "status": "published",
                },
                format="json",
            ).status_code,
            400,
        )

    def test_published_content_rejects_editor_mutations(self):
        self.auth(self.manager)
        r = self.client.post(reverse("content-page-publish", args=[self.page.slug]))
        self.assertEqual(r.status_code, 200, r.data)
        self.auth(self.editor)
        self.assertEqual(
            self.client.patch(
                self.page_url(), {"content": "silent edit"}, format="json"
            ).status_code,
            403,
        )
        self.assertEqual(self.client.delete(self.page_url()).status_code, 403)
        self.auth(self.manager)
        self.assertEqual(
            self.client.patch(
                self.page_url(), {"content": "approved edit"}, format="json"
            ).status_code,
            200,
        )

    def test_publisher_can_publish_and_archive_but_not_edit(self):
        self.auth(self.publisher)
        self.assertEqual(
            self.client.patch(self.page_url(), {"title": "X"}).status_code, 403
        )
        self.assertEqual(
            self.client.post(
                reverse("content-page-publish", args=[self.page.slug])
            ).status_code,
            200,
        )
        self.assertEqual(
            self.client.post(
                reverse("content-page-archive", args=[self.page.slug])
            ).status_code,
            200,
        )
        self.page.refresh_from_db()
        self.assertEqual(self.page.status, "archived")

    def test_editor_cannot_activate_faq_or_change_live_navigation(self):
        self.auth(self.editor)
        created = self.client.post(
            reverse("faq-category-list"),
            {
                "name": "Editor Pending FAQ",
                "is_active": False,
            },
            format="json",
        )
        self.assertEqual(created.status_code, 201, created.data)
        self.assertFalse(created.data["is_active"])
        denied = self.client.post(
            reverse("faq-category-list"),
            {
                "name": "Bad Active FAQ",
                "is_active": True,
            },
            format="json",
        )
        self.assertEqual(denied.status_code, 400)
        self.assertEqual(
            self.client.post(
                reverse("navigation-item-list"),
                {"menu": self.menu.pk, "label": "Pending", "link_url": "/help"},
                format="json",
            ).data["is_active"],
            False,
        )
        self.auth(self.manager)
        self.assertEqual(
            self.client.patch(
                reverse("faq-category-detail", args=[created.data["slug"]]),
                {"is_active": True},
                format="json",
            ).status_code,
            200,
        )
        self.auth(self.editor)
        self.assertEqual(
            self.client.patch(
                reverse("faq-category-detail", args=[created.data["slug"]]),
                {"description": "Silent live edit"},
                format="json",
            ).status_code,
            403,
        )

    def test_plain_staff_without_cms_role_cannot_manage_drafts(self):
        self.auth(self.staff)
        self.assertEqual(self.client.get(self.page_url()).status_code, 404)
        self.assertEqual(
            self.client.patch(self.page_url(), {"title": "X"}).status_code, 403
        )
        self.auth(self.manager)
        self.assertEqual(
            self.client.patch(self.page_url(), {"title": "Okay"}).status_code, 200
        )

    def test_expired_or_revoked_role_loses_draft_access(self):
        self.auth(self.viewer)
        self.assertEqual(self.client.get(self.page_url()).status_code, 200)
        remove_role(self.viewer, Role.objects.get(name="content_viewer"))
        self.assertEqual(self.client.get(self.page_url()).status_code, 404)

    def test_date_window_rejected_on_edit_and_publish(self):
        self.auth(self.manager)
        now = timezone.now()
        bad = self.client.patch(
            self.page_url(),
            {
                "starts_at": (now + timedelta(days=2)).isoformat(),
                "ends_at": (now + timedelta(days=1)).isoformat(),
            },
            format="json",
        )
        self.assertEqual(bad.status_code, 400)
        # If old DB records have bad dates, publishing still refuses them.
        ContentPage.objects.filter(pk=self.page.pk).update(
            starts_at=now + timedelta(days=2), ends_at=now + timedelta(days=1)
        )
        self.assertEqual(
            self.client.post(
                reverse("content-page-publish", args=[self.page.slug])
            ).status_code,
            400,
        )

    def test_rejects_raw_html_and_unsafe_links(self):
        self.auth(self.manager)
        self.assertEqual(
            self.client.patch(
                self.page_url(), {"content": "<script>alert(1)</script>"}, format="json"
            ).status_code,
            400,
        )
        for bad_url in (
            "javascript:alert(1)",
            "//evil.example",
            "https://user:pass@evil.example/",
        ):
            with self.subTest(url=bad_url):
                res = self.client.post(
                    reverse("announcement-list"),
                    {
                        "title": "Test",
                        "message": "Plain text",
                        "link_url": bad_url,
                    },
                    format="json",
                )
                self.assertEqual(res.status_code, 400)
        self.assertEqual(
            self.client.post(
                reverse("announcement-list"),
                {
                    "title": "Safe",
                    "message": "Plain text",
                    "link_url": "/products",
                },
                format="json",
            ).status_code,
            201,
        )

    def test_navigation_items_crud_and_cycle_and_cross_menu(self):
        self.auth(self.manager)
        root_response = self.client.post(
            reverse("navigation-item-list"),
            {
                "menu": self.menu.pk,
                "label": "Home",
                "link_url": "/",
            },
            format="json",
        )
        self.assertEqual(root_response.status_code, 201, root_response.data)
        root = root_response.data["id"]
        child_response = self.client.post(
            reverse("navigation-item-list"),
            {
                "menu": self.menu.pk,
                "parent": root,
                "label": "Support",
                "link_url": "/support",
            },
            format="json",
        )
        self.assertEqual(child_response.status_code, 201, child_response.data)
        self.assertEqual(
            self.client.patch(
                reverse("navigation-item-detail", args=[root]),
                {"parent": child_response.data["id"]},
                format="json",
            ).status_code,
            400,
        )
        another = NavigationMenu.objects.create(name="Elsewhere", slug="elsewhere")
        self.assertEqual(
            self.client.post(
                reverse("navigation-item-list"),
                {
                    "menu": another.pk,
                    "parent": root,
                    "label": "Invalid",
                    "link_url": "/invalid",
                },
                format="json",
            ).status_code,
            400,
        )

    def test_nav_does_not_disclose_draft_link_or_inactive_page(self):
        NavigationItem.objects.create(menu=self.menu, page=self.page, label="Draft")
        NavigationItem.objects.create(menu=self.menu, label="Home", link_url="/")
        self.auth()
        res = self.client.get(reverse("navigation-menu-detail", args=[self.menu.slug]))
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual([row["label"] for row in res.data["items"]], ["Home"])
        self.assertEqual(
            self.client.get(reverse("navigation-item-list")).data["count"], 1
        )
        self.auth(self.viewer)
        res = self.client.get(reverse("navigation-menu-detail", args=[self.menu.slug]))
        self.assertEqual({row["label"] for row in res.data["items"]}, {"Draft", "Home"})

    def test_audit_log_tracks_create_publish_archive(self):
        self.auth(self.manager)
        res = self.client.post(
            reverse("content-page-list"),
            {"title": "Audit Example", "content": "Text only", "slug": "audit-example"},
            format="json",
        )
        self.assertEqual(res.status_code, 201, res.data)
        self.assertEqual(
            self.client.post(
                reverse("content-page-publish", args=["audit-example"])
            ).status_code,
            200,
        )
        self.assertEqual(
            self.client.post(
                reverse("content-page-archive", args=["audit-example"])
            ).status_code,
            200,
        )
        logs = AuditLog.objects.filter(
            object_type="cms.contentpage", object_id=str(res.data["id"])
        )
        self.assertEqual(logs.count(), 3)

    def test_role_does_not_grant_finance_permission(self):
        from apps.rbac.utils import has_permission

        self.assertFalse(has_permission(self.manager, "view_platform_analytics"))
        self.assertFalse(has_permission(self.manager, "manage_analytics_reports"))
