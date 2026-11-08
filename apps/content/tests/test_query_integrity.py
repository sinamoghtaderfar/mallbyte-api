import threading
from unittest import skipUnless
from unittest.mock import patch

from django.db import close_old_connections, connection, transaction
from django.test import TransactionTestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from rest_framework.test import APIClient, APITestCase

from apps.accounts.models import User
from apps.content.models import ContentPage, FAQCategory, FAQItem, NavigationItem, NavigationMenu
from apps.content.permissions import ContentPermission
from apps.content.serializers import FAQCategorySerializer
from apps.rbac.models import Role
from apps.rbac.utils import assign_role, clear_user_permissions_cache


class CMSQueryIntegrityTests(APITestCase):
    def test_numeric_filters_return_field_errors_instead_of_server_errors(self):
        for endpoint, key in (("faq-item-list", "category"), ("navigation-item-list", "menu"), ("navigation-item-list", "parent")):
            for value in ("bad", "1.2", "-1", str(2 ** 63)):
                with self.subTest(endpoint=endpoint, key=key, value=value):
                    response = self.client.get(reverse(endpoint), {key: value})
                    self.assertEqual(response.status_code, 400)
                    self.assertIn(key, response.data)

    def test_public_faq_category_serialization_has_constant_queries_and_hides_inactive_items(self):
        for index in range(5):
            category = FAQCategory.objects.create(name=f"Category {index}", slug=f"faq-query-{index}")
            FAQItem.objects.create(category=category, question=f"Visible {index}", answer="Answer", is_active=True)
            FAQItem.objects.create(category=category, question=f"Hidden {index}", answer="Answer", is_active=False)
        with CaptureQueriesContext(connection) as queries:
            response = self.client.get(reverse("faq-category-list"))
        self.assertEqual(response.status_code, 200)
        self.assertLessEqual(len(queries), 5)
        self.assertEqual(len(response.data["results"]), 5)
        self.assertTrue(all(len(category["items"]) == 1 for category in response.data["results"]))

    def test_public_navigation_serialization_has_constant_queries_and_preserves_visibility(self):
        page = ContentPage.objects.create(title="Draft page", content="Draft", status="draft")
        for index in range(5):
            menu = NavigationMenu.objects.create(name=f"Menu {index}", slug=f"menu-query-{index}")
            root = NavigationItem.objects.create(menu=menu, label="Root", link_url="/")
            NavigationItem.objects.create(menu=menu, parent=root, label="Child", link_url="/child")
            NavigationItem.objects.create(menu=menu, parent=root, label="Hidden", link_url="/hidden", is_active=False)
            NavigationItem.objects.create(menu=menu, label="Private", page=page)
            NavigationItem.objects.create(menu=menu, label="Account", link_url="/account", requires_auth=True)
        for endpoint in ("navigation-menu-list", "navigation-item-list"):
            with self.subTest(endpoint=endpoint), CaptureQueriesContext(connection) as queries:
                response = self.client.get(reverse(endpoint))
            self.assertEqual(response.status_code, 200)
            self.assertLessEqual(len(queries), 5)
            if endpoint == "navigation-menu-list":
                for menu in response.data["results"]:
                    self.assertEqual([item["label"] for item in menu["items"]], ["Root"])
                    self.assertEqual([item["label"] for item in menu["items"][0]["children"]], ["Child"])
            else:
                self.assertEqual({item["label"] for item in response.data["results"]}, {"Root", "Child"})

    def test_faq_visibility_permission_is_resolved_once_per_collection(self):
        from types import SimpleNamespace
        categories = [FAQCategory(name=f"FAQ {index}") for index in range(5)]
        for category in categories:
            category._cms_items = []
        with patch("apps.content.serializers.can_view_unpublished", return_value=False) as permission:
            result = FAQCategorySerializer(categories, many=True, context={"request": SimpleNamespace(user=None)}).data
        self.assertEqual(len(result), 5)
        permission.assert_called_once()

    def test_homepage_prefetches_featured_page_authors(self):
        author = User.objects.create_user(email="homepage-author@example.com")
        for index in range(5):
            ContentPage.objects.create(title=f"Authored {index}", content="Content", status="published", is_featured=True, created_by=author, updated_by=author)
        with CaptureQueriesContext(connection) as queries:
            response = self.client.get(reverse("content-homepage"))
        self.assertEqual(response.status_code, 200)
        self.assertLessEqual(len(queries), 5)
        self.assertEqual(len(response.data["featured_pages"]), 5)

    @override_settings(CMS_HOMEPAGE_ITEM_LIMIT=3)
    def test_homepage_sections_are_bounded_and_full_collections_remain_paginated(self):
        for index in range(5):
            ContentPage.objects.create(title=f"Featured {index}", content="Content", status="published", is_featured=True)
        response = self.client.get(reverse("content-homepage"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data["featured_pages"]), 3)
        response = self.client.get(reverse("content-page-list"))
        self.assertEqual(response.data["count"], 5)
        self.assertEqual(len(response.data["results"]), 5)

    def test_malformed_url_authority_returns_field_validation_error(self):
        admin = User.objects.create_superuser(email="cms-url-admin@example.com", password="testpass123")
        menu = NavigationMenu.objects.create(name="URL validation", slug="url-validation")
        self.client.force_authenticate(admin)
        response = self.client.post(reverse("navigation-item-list"), {"menu": menu.pk, "label": "Malformed", "link_url": "https://["})
        self.assertEqual(response.status_code, 400)
        self.assertIn("link_url", response.data)

    def test_duplicate_explicit_slug_returns_validation_error(self):
        admin = User.objects.create_superuser(email="cms-slug-admin@example.com", password="testpass123")
        ContentPage.objects.create(title="Existing", slug="taken", content="Content")
        self.client.force_authenticate(admin)
        response = self.client.post(reverse("content-page-list"), {"title": "Duplicate", "slug": "taken", "content": "Text"})
        self.assertEqual(response.status_code, 400)
        self.assertIn("slug", response.data)

    def test_navigation_parent_with_children_cannot_be_nested_to_create_a_third_level(self):
        admin = User.objects.create_superuser(email="cms-hierarchy-admin@example.com", password="testpass123")
        menu = NavigationMenu.objects.create(name="Hierarchy", slug="hierarchy")
        root = NavigationItem.objects.create(menu=menu, label="Root", link_url="/")
        other = NavigationItem.objects.create(menu=menu, label="Other", link_url="/other")
        NavigationItem.objects.create(menu=menu, parent=root, label="Child", link_url="/child")
        self.client.force_authenticate(admin)
        response = self.client.patch(reverse("navigation-item-detail", args=[root.pk]), {"parent": other.pk})
        self.assertEqual(response.status_code, 400)
        root.refresh_from_db()
        self.assertIsNone(root.parent_id)


@skipUnless(connection.vendor == "postgresql", "PostgreSQL row-lock behavior is required.")
class CMSPublicationConcurrencyTests(TransactionTestCase):
    def test_editor_permission_is_checked_after_concurrent_publication_commits(self):
        editor = User.objects.create_user(email="cms-concurrent-editor@example.com")
        assign_role(editor, Role.objects.get(name="content_editor"))
        clear_user_permissions_cache(editor)
        page = ContentPage.objects.create(title="Concurrent publication", slug="concurrent-publication", content="Approved content")
        published = threading.Event()
        release = threading.Event()
        query_started = threading.Event()
        checked = threading.Event()
        errors = []
        responses = []
        original_permission = ContentPermission.has_object_permission

        def check_permission(permission, request, view, obj):
            checked.set()
            return original_permission(permission, request, view, obj)

        def publisher():
            close_old_connections()
            try:
                with transaction.atomic():
                    locked = ContentPage.objects.select_for_update().get(pk=page.pk)
                    locked.publish()
                    published.set()
                    if not release.wait(5):
                        raise TimeoutError("Editor did not reach the read barrier.")
            except Exception as exc:
                errors.append(exc)
            finally:
                connection.close()

        def signal_query(execute, sql, params, many, context):
            if sql.lstrip().upper().startswith("SELECT") and "content_contentpage" in sql:
                query_started.set()
            return execute(sql, params, many, context)

        def edit():
            close_old_connections()
            try:
                client = APIClient()
                client.force_authenticate(editor)
                with connection.execute_wrapper(signal_query):
                    responses.append(client.patch(reverse("content-page-detail", args=[page.slug]), {"content": "Unapproved overwrite"}, format="json"))
            except Exception as exc:
                errors.append(exc)
            finally:
                connection.close()

        publish_thread = threading.Thread(target=publisher)
        edit_thread = threading.Thread(target=edit)
        with patch.object(ContentPermission, "has_object_permission", check_permission):
            publish_thread.start()
            try:
                self.assertTrue(published.wait(5))
                edit_thread.start()
                self.assertTrue(query_started.wait(5))
                checked_before_commit = checked.wait(0.2)
            finally:
                release.set()
                publish_thread.join(5)
                if edit_thread.ident is not None:
                    edit_thread.join(5)
        self.assertFalse(publish_thread.is_alive())
        self.assertFalse(edit_thread.is_alive())
        self.assertFalse(errors, errors)
        self.assertFalse(checked_before_commit, "Publication-state permission ran before the row lock was released.")
        self.assertEqual([response.status_code for response in responses], [403])
        page.refresh_from_db()
        self.assertEqual(page.status, "published")
        self.assertEqual(page.content, "Approved content")
