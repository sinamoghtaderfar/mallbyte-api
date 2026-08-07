import shutil
import tempfile
from datetime import timedelta

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from apps.content.models import (
    Announcement,
    Banner,
    ContentPage,
    FAQCategory,
    FAQItem,
)

TEST_MEDIA_ROOT = tempfile.mkdtemp()


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
class HomepageContentAPITests(APITestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEST_MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        now = timezone.now()

        self.visible_banner = Banner.objects.create(
            title="Visible Homepage Banner",
            subtitle="This banner should be visible.",
            image=SimpleUploadedFile(
                "visible-banner.jpg",
                b"fake-image-content",
                content_type="image/jpeg",
            ),
            placement=Banner.PlacementChoices.HOME_HERO,
            status=Banner.StatusChoices.PUBLISHED,
            published_at=now,
            order=1,
        )

        self.draft_banner = Banner.objects.create(
            title="Draft Homepage Banner",
            subtitle="This banner should not be visible.",
            image=SimpleUploadedFile(
                "draft-banner.jpg",
                b"fake-image-content",
                content_type="image/jpeg",
            ),
            placement=Banner.PlacementChoices.HOME_HERO,
            status=Banner.StatusChoices.DRAFT,
            order=2,
        )

        self.future_banner = Banner.objects.create(
            title="Future Homepage Banner",
            subtitle="This banner starts in the future.",
            image=SimpleUploadedFile(
                "future-banner.jpg",
                b"fake-image-content",
                content_type="image/jpeg",
            ),
            placement=Banner.PlacementChoices.HOME_TOP,
            status=Banner.StatusChoices.PUBLISHED,
            published_at=now,
            starts_at=now + timedelta(days=1),
            order=3,
        )

        self.visible_announcement = Announcement.objects.create(
            title="Visible Announcement",
            message="This announcement should be visible.",
            level=Announcement.LevelChoices.INFO,
            placement=Announcement.PlacementChoices.GLOBAL,
            status=Announcement.StatusChoices.PUBLISHED,
            published_at=now,
            order=1,
        )

        self.draft_announcement = Announcement.objects.create(
            title="Draft Announcement",
            message="This announcement should not be visible.",
            level=Announcement.LevelChoices.WARNING,
            placement=Announcement.PlacementChoices.HOME,
            status=Announcement.StatusChoices.DRAFT,
            order=2,
        )

        self.expired_announcement = Announcement.objects.create(
            title="Expired Announcement",
            message="This announcement is expired.",
            level=Announcement.LevelChoices.INFO,
            placement=Announcement.PlacementChoices.HOME,
            status=Announcement.StatusChoices.PUBLISHED,
            published_at=now - timedelta(days=5),
            ends_at=now - timedelta(days=1),
            order=3,
        )

        self.featured_page = ContentPage.objects.create(
            title="Featured Landing Page",
            slug="featured-landing-page",
            page_type=ContentPage.PageTypeChoices.LANDING,
            excerpt="Featured page excerpt.",
            content="Featured page content.",
            status=ContentPage.StatusChoices.PUBLISHED,
            published_at=now,
            is_featured=True,
            order=1,
        )

        self.not_featured_page = ContentPage.objects.create(
            title="Not Featured Page",
            slug="not-featured-page",
            page_type=ContentPage.PageTypeChoices.CUSTOM,
            excerpt="Not featured excerpt.",
            content="Not featured content.",
            status=ContentPage.StatusChoices.PUBLISHED,
            published_at=now,
            is_featured=False,
            order=2,
        )

        self.draft_featured_page = ContentPage.objects.create(
            title="Draft Featured Page",
            slug="draft-featured-page",
            page_type=ContentPage.PageTypeChoices.LANDING,
            excerpt="Draft featured excerpt.",
            content="Draft featured content.",
            status=ContentPage.StatusChoices.DRAFT,
            is_featured=True,
            order=3,
        )

        self.faq_category = FAQCategory.objects.create(
            name="Homepage FAQ",
            slug="homepage-faq",
            description="Homepage FAQ category.",
            is_active=True,
            order=1,
        )

        self.inactive_faq_category = FAQCategory.objects.create(
            name="Inactive Homepage FAQ",
            slug="inactive-homepage-faq",
            description="Inactive FAQ category.",
            is_active=False,
            order=2,
        )

        self.featured_faq = FAQItem.objects.create(
            category=self.faq_category,
            question="How does MallByte work?",
            answer="MallByte works as an ecommerce platform.",
            is_active=True,
            is_featured=True,
            order=1,
        )

        self.not_featured_faq = FAQItem.objects.create(
            category=self.faq_category,
            question="Not featured question?",
            answer="Not featured answer.",
            is_active=True,
            is_featured=False,
            order=2,
        )

        self.inactive_featured_faq = FAQItem.objects.create(
            category=self.faq_category,
            question="Inactive featured question?",
            answer="Inactive featured answer.",
            is_active=False,
            is_featured=True,
            order=3,
        )

        self.featured_faq_in_inactive_category = FAQItem.objects.create(
            category=self.inactive_faq_category,
            question="Hidden category question?",
            answer="Hidden category answer.",
            is_active=True,
            is_featured=True,
            order=1,
        )

    def get_ids(self, items):
        return {item["id"] for item in items}

    def test_homepage_endpoint_returns_expected_sections(self):
        url = reverse("content-homepage")

        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()

        self.assertIn("banners", data)
        self.assertIn("announcements", data)
        self.assertIn("featured_pages", data)
        self.assertIn("featured_faqs", data)

    def test_homepage_returns_only_visible_banners(self):
        url = reverse("content-homepage")

        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        banner_ids = self.get_ids(response.json()["banners"])

        self.assertIn(self.visible_banner.id, banner_ids)
        self.assertNotIn(self.draft_banner.id, banner_ids)
        self.assertNotIn(self.future_banner.id, banner_ids)

    def test_homepage_returns_only_visible_announcements(self):
        url = reverse("content-homepage")

        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        announcement_ids = self.get_ids(response.json()["announcements"])

        self.assertIn(self.visible_announcement.id, announcement_ids)
        self.assertNotIn(self.draft_announcement.id, announcement_ids)
        self.assertNotIn(self.expired_announcement.id, announcement_ids)

    def test_homepage_returns_only_visible_featured_pages(self):
        url = reverse("content-homepage")

        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        page_ids = self.get_ids(response.json()["featured_pages"])

        self.assertIn(self.featured_page.id, page_ids)
        self.assertNotIn(self.not_featured_page.id, page_ids)
        self.assertNotIn(self.draft_featured_page.id, page_ids)

    def test_homepage_returns_only_active_featured_faqs(self):
        url = reverse("content-homepage")

        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        faq_ids = self.get_ids(response.json()["featured_faqs"])

        self.assertIn(self.featured_faq.id, faq_ids)
        self.assertNotIn(self.not_featured_faq.id, faq_ids)
        self.assertNotIn(self.inactive_featured_faq.id, faq_ids)
        self.assertNotIn(self.featured_faq_in_inactive_category.id, faq_ids)