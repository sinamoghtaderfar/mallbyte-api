from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.content.views import (
    AnnouncementViewSet,
    BannerViewSet,
    ContentPageViewSet,
    FAQCategoryViewSet,
    FAQItemViewSet,
    HomepageContentView,
    HomepageContentView,
    NavigationMenuViewSet,
)

router = DefaultRouter()
router.register("pages", ContentPageViewSet, basename="content-page")
router.register("banners", BannerViewSet, basename="content-banner")
router.register("faq-categories", FAQCategoryViewSet, basename="faq-category")
router.register("faqs", FAQItemViewSet, basename="faq-item")
router.register("announcements", AnnouncementViewSet, basename="announcement")
router.register("navigation", NavigationMenuViewSet, basename="navigation-menu")

urlpatterns = [
    path("homepage/", HomepageContentView.as_view(), name="content-homepage"),
    path("", include(router.urls)),
]