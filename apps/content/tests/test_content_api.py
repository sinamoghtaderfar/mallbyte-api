import shutil
import tempfile
from typing import cast

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from apps.accounts.models import User
from apps.content.models import (
    Announcement,
    Banner,
    ContentPage,
    FAQCategory,
    FAQItem,
)

TEST_MEDIA_ROOT = tempfile.mkdtemp()


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
class ContentAPITests(APITestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEST_MEDIA_ROOT, ignore_errors=True)

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
        self.admin_user = self.create_test_user(
            phone="+989980000001",
            email="content_admin@example.com",
            full_name="Content Admin",
            is_staff=True,
            is_superuser=True,
        )

        self.customer = self.create_test_user(
            phone="+989980000002",
            email="content_customer@example.com",
            full_name="Content Customer",
        )

        self.published_page = ContentPage.objects.create(
            title="About MallByte",
            slug="about-mallbyte",
            page_type=ContentPage.PageTypeChoices.ABOUT,
            excerpt="About page excerpt.",
            content="About page content.",
            status=ContentPage.StatusChoices.PUBLISHED,
            published_at=timezone.now(),
            created_by=self.admin_user,
            updated_by=self.admin_user,
        )

        self.draft_page = ContentPage.objects.create(
            title="Draft Terms",
            slug="draft-terms",
            page_type=ContentPage.PageTypeChoices.TERMS,
            excerpt="Draft terms excerpt.",
            content="Draft terms content.",
            status=ContentPage.StatusChoices.DRAFT,
            created_by=self.admin_user,
            updated_by=self.admin_user,
        )

        self.banner = Banner.objects.create(
            title="Home Hero Banner",
            subtitle="Big sale is live.",
            image=SimpleUploadedFile(
                "hero.jpg",
                b"fake-image-content",
                content_type="image/jpeg",
            ),
            placement=Banner.PlacementChoices.HOME_HERO,
            cta_text="Shop now",
            link_url="/products/",
            status=Banner.StatusChoices.PUBLISHED,
            published_at=timezone.now(),
            order=1,
        )

        self.draft_banner = Banner.objects.create(
            title="Draft Banner",
            subtitle="Draft banner.",
            image=SimpleUploadedFile(
                "draft.jpg",
                b"fake-image-content",
                content_type="image/jpeg",
            ),
            placement=Banner.PlacementChoices.HOME_TOP,
            status=Banner.StatusChoices.DRAFT,
        )

        self.faq_category = FAQCategory.objects.create(
            name="Orders",
            slug="orders",
            description="Order questions.",
            is_active=True,
            order=1,
        )

        self.inactive_faq_category = FAQCategory.objects.create(
            name="Inactive Category",
            slug="inactive-category",
            description="Inactive FAQ category.",
            is_active=False,
            order=2,
        )

        self.active_faq = FAQItem.objects.create(
            category=self.faq_category,
            question="How can I track my order?",
            answer="You can track it from your account.",
            is_active=True,
            is_featured=True,
            order=1,
        )

        self.inactive_faq = FAQItem.objects.create(
            category=self.faq_category,
            question="Inactive question?",
            answer="Inactive answer.",
            is_active=False,
            is_featured=False,
            order=2,
        )

        self.announcement = Announcement.objects.create(
            title="Maintenance Notice",
            message="The shop will be under maintenance tonight.",
            level=Announcement.LevelChoices.WARNING,
            placement=Announcement.PlacementChoices.GLOBAL,
            status=Announcement.StatusChoices.PUBLISHED,
            published_at=timezone.now(),
            order=1,
        )

        self.draft_announcement = Announcement.objects.create(
            title="Draft Announcement",
            message="Draft announcement message.",
            level=Announcement.LevelChoices.INFO,
            placement=Announcement.PlacementChoices.HOME,
            status=Announcement.StatusChoices.DRAFT,
            order=2,
        )

    def get_api_client(self) -> APIClient:
        return cast(APIClient, self.client)

    def authenticate_admin(self):
        self.get_api_client().force_authenticate(user=self.admin_user)

    def authenticate_customer(self):
        self.get_api_client().force_authenticate(user=self.customer)

    def get_response_items(self, response):
        data = response.json()

        if isinstance(data, dict) and "results" in data:
            return data["results"]

        return data

    def get_ids(self, response):
        return {item["id"] for item in self.get_response_items(response)}

    def test_public_user_only_sees_published_pages(self):
        url = reverse("content-page-list")

        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        ids = self.get_ids(response)

        self.assertIn(self.published_page.id, ids)
        self.assertNotIn(self.draft_page.id, ids)

    def test_admin_can_see_draft_pages(self):
        self.authenticate_admin()

        url = reverse("content-page-list")

        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        ids = self.get_ids(response)

        self.assertIn(self.published_page.id, ids)
        self.assertIn(self.draft_page.id, ids)

    def test_public_can_retrieve_published_page_by_slug(self):
        url = reverse("content-page-detail", args=[self.published_page.slug])

        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["slug"], self.published_page.slug)

    def test_public_cannot_retrieve_draft_page(self):
        url = reverse("content-page-detail", args=[self.draft_page.slug])

        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_customer_cannot_create_content_page(self):
        self.authenticate_customer()

        url = reverse("content-page-list")

        response = self.client.post(
            url,
            data={
                "title": "Customer Page",
                "slug": "customer-page",
                "page_type": ContentPage.PageTypeChoices.CUSTOM,
                "content": "Customer page content.",
                "status": ContentPage.StatusChoices.PUBLISHED,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_admin_can_create_publish_and_archive_content_page(self):
        self.authenticate_admin()

        create_url = reverse("content-page-list")

        create_response = self.client.post(
            create_url,
            data={
                "title": "Privacy Policy",
                "slug": "privacy-policy",
                "page_type": ContentPage.PageTypeChoices.PRIVACY,
                "excerpt": "Privacy excerpt.",
                "content": "Privacy content.",
                "status": ContentPage.StatusChoices.DRAFT,
            },
            format="json",
        )

        self.assertEqual(create_response.status_code, status.HTTP_201_CREATED)

        page = ContentPage.objects.get(slug="privacy-policy")

        self.assertEqual(page.created_by, self.admin_user)
        self.assertEqual(page.updated_by, self.admin_user)

        publish_url = reverse("content-page-publish", args=[page.slug])

        publish_response = self.client.post(publish_url, data={}, format="json")

        self.assertEqual(publish_response.status_code, status.HTTP_200_OK)

        page.refresh_from_db()

        self.assertEqual(page.status, ContentPage.StatusChoices.PUBLISHED)
        self.assertIsNotNone(page.published_at)

        archive_url = reverse("content-page-archive", args=[page.slug])

        archive_response = self.client.post(archive_url, data={}, format="json")

        self.assertEqual(archive_response.status_code, status.HTTP_200_OK)

        page.refresh_from_db()

        self.assertEqual(page.status, ContentPage.StatusChoices.ARCHIVED)

    def test_public_only_sees_published_banners(self):
        url = reverse("content-banner-list")

        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        ids = self.get_ids(response)

        self.assertIn(self.banner.id, ids)
        self.assertNotIn(self.draft_banner.id, ids)

    def test_banner_filter_by_placement(self):
        url = reverse("content-banner-list")

        response = self.client.get(
            url,
            data={
                "placement": Banner.PlacementChoices.HOME_HERO,
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        ids = self.get_ids(response)

        self.assertIn(self.banner.id, ids)
        self.assertNotIn(self.draft_banner.id, ids)

    def test_public_only_sees_active_faq_categories_and_items(self):
        url = reverse("faq-category-list")

        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        items = self.get_response_items(response)
        category_ids = {item["id"] for item in items}

        self.assertIn(self.faq_category.id, category_ids)
        self.assertNotIn(self.inactive_faq_category.id, category_ids)

        orders_category = next(
            item for item in items if item["id"] == self.faq_category.id
        )

        faq_ids = {item["id"] for item in orders_category["items"]}

        self.assertIn(self.active_faq.id, faq_ids)
        self.assertNotIn(self.inactive_faq.id, faq_ids)

    def test_admin_can_see_inactive_faq_items(self):
        self.authenticate_admin()

        url = reverse("faq-item-list")

        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        ids = self.get_ids(response)

        self.assertIn(self.active_faq.id, ids)
        self.assertIn(self.inactive_faq.id, ids)

    def test_faq_filter_by_featured(self):
        url = reverse("faq-item-list")

        response = self.client.get(
            url,
            data={
                "is_featured": "true",
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        ids = self.get_ids(response)

        self.assertIn(self.active_faq.id, ids)
        self.assertNotIn(self.inactive_faq.id, ids)

    def test_public_only_sees_published_announcements(self):
        url = reverse("announcement-list")

        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        ids = self.get_ids(response)

        self.assertIn(self.announcement.id, ids)
        self.assertNotIn(self.draft_announcement.id, ids)

    def test_announcement_filter_by_placement_and_level(self):
        url = reverse("announcement-list")

        response = self.client.get(
            url,
            data={
                "placement": Announcement.PlacementChoices.GLOBAL,
                "level": Announcement.LevelChoices.WARNING,
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        ids = self.get_ids(response)

        self.assertIn(self.announcement.id, ids)
        self.assertNotIn(self.draft_announcement.id, ids)

    def test_admin_can_publish_and_archive_announcement(self):
        self.authenticate_admin()

        publish_url = reverse(
            "announcement-publish",
            args=[self.draft_announcement.pk],
        )

        publish_response = self.client.post(publish_url, data={}, format="json")

        self.assertEqual(publish_response.status_code, status.HTTP_200_OK)

        self.draft_announcement.refresh_from_db()

        self.assertEqual(
            self.draft_announcement.status,
            Announcement.StatusChoices.PUBLISHED,
        )

        archive_url = reverse(
            "announcement-archive",
            args=[self.draft_announcement.pk],
        )

        archive_response = self.client.post(archive_url, data={}, format="json")

        self.assertEqual(archive_response.status_code, status.HTTP_200_OK)

        self.draft_announcement.refresh_from_db()

        self.assertEqual(
            self.draft_announcement.status,
            Announcement.StatusChoices.ARCHIVED,
        )