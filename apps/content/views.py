from django.db.models import Q
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from apps.content.models import (
    Announcement,
    Banner,
    ContentPage,
    FAQCategory,
    FAQItem,
)
from apps.content.permissions import IsContentAdmin
from apps.content.serializers import (
    AnnouncementSerializer,
    BannerSerializer,
    ContentPageSerializer,
    FAQCategorySerializer,
    FAQItemSerializer,
)


def visible_now_queryset(queryset):
    now = timezone.now()

    return queryset.filter(
        status=ContentPage.StatusChoices.PUBLISHED,
    ).filter(
        Q(starts_at__isnull=True) | Q(starts_at__lte=now),
    ).filter(
        Q(ends_at__isnull=True) | Q(ends_at__gte=now),
    )


class ContentPageViewSet(viewsets.ModelViewSet):
    serializer_class = ContentPageSerializer
    lookup_field = "slug"

    def get_permissions(self):
        if self.action in ["list", "retrieve"]:
            return [AllowAny()]

        return [IsAuthenticated(), IsContentAdmin()]

    def get_queryset(self):
        user = self.request.user

        queryset = ContentPage.objects.select_related(
            "created_by",
            "updated_by",
        ).all()

        if not (
            user.is_authenticated
            and (user.is_staff or user.is_superuser)
        ):
            queryset = visible_now_queryset(queryset)

        page_type = self.request.query_params.get("page_type")
        is_featured = self.request.query_params.get("is_featured")
        status_filter = self.request.query_params.get("status")

        if page_type:
            queryset = queryset.filter(page_type=page_type)

        if is_featured is not None:
            if is_featured.lower() == "true":
                queryset = queryset.filter(is_featured=True)
            elif is_featured.lower() == "false":
                queryset = queryset.filter(is_featured=False)

        if status_filter and user.is_authenticated and (user.is_staff or user.is_superuser):
            queryset = queryset.filter(status=status_filter)

        return queryset.order_by("order", "title")

    def perform_create(self, serializer):
        serializer.save(
            created_by=self.request.user,
            updated_by=self.request.user,
        )

    def perform_update(self, serializer):
        serializer.save(
            updated_by=self.request.user,
        )

    @action(
        detail=True,
        methods=["post"],
        url_path="publish",
        permission_classes=[IsAuthenticated, IsContentAdmin],
    )
    def publish(self, request, slug=None):
        page = self.get_object()
        page.publish()

        serializer = self.get_serializer(page)

        return Response(serializer.data, status=status.HTTP_200_OK)

    @action(
        detail=True,
        methods=["post"],
        url_path="archive",
        permission_classes=[IsAuthenticated, IsContentAdmin],
    )
    def archive(self, request, slug=None):
        page = self.get_object()
        page.archive()

        serializer = self.get_serializer(page)

        return Response(serializer.data, status=status.HTTP_200_OK)


class BannerViewSet(viewsets.ModelViewSet):
    serializer_class = BannerSerializer
    parser_classes = [MultiPartParser, FormParser]

    def get_permissions(self):
        if self.action in ["list", "retrieve"]:
            return [AllowAny()]

        return [IsAuthenticated(), IsContentAdmin()]

    def get_queryset(self):
        user = self.request.user

        queryset = Banner.objects.all()

        if not (
            user.is_authenticated
            and (user.is_staff or user.is_superuser)
        ):
            queryset = visible_now_queryset(queryset)

        placement = self.request.query_params.get("placement")
        status_filter = self.request.query_params.get("status")

        if placement:
            queryset = queryset.filter(placement=placement)

        if status_filter and user.is_authenticated and (user.is_staff or user.is_superuser):
            queryset = queryset.filter(status=status_filter)

        return queryset.order_by("placement", "order", "-created_at")

    @action(
        detail=True,
        methods=["post"],
        url_path="publish",
        permission_classes=[IsAuthenticated, IsContentAdmin],
    )
    def publish(self, request, pk=None):
        banner = self.get_object()
        banner.publish()

        serializer = self.get_serializer(banner)

        return Response(serializer.data, status=status.HTTP_200_OK)

    @action(
        detail=True,
        methods=["post"],
        url_path="archive",
        permission_classes=[IsAuthenticated, IsContentAdmin],
    )
    def archive(self, request, pk=None):
        banner = self.get_object()
        banner.archive()

        serializer = self.get_serializer(banner)

        return Response(serializer.data, status=status.HTTP_200_OK)


class FAQCategoryViewSet(viewsets.ModelViewSet):
    serializer_class = FAQCategorySerializer
    lookup_field = "slug"

    def get_permissions(self):
        if self.action in ["list", "retrieve"]:
            return [AllowAny()]

        return [IsAuthenticated(), IsContentAdmin()]

    def get_queryset(self):
        user = self.request.user

        queryset = FAQCategory.objects.prefetch_related("items").all()

        if not (
            user.is_authenticated
            and (user.is_staff or user.is_superuser)
        ):
            queryset = queryset.filter(is_active=True)

        is_active = self.request.query_params.get("is_active")

        if is_active is not None and user.is_authenticated and (user.is_staff or user.is_superuser):
            if is_active.lower() == "true":
                queryset = queryset.filter(is_active=True)
            elif is_active.lower() == "false":
                queryset = queryset.filter(is_active=False)

        return queryset.order_by("order", "name")


class FAQItemViewSet(viewsets.ModelViewSet):
    serializer_class = FAQItemSerializer

    def get_permissions(self):
        if self.action in ["list", "retrieve"]:
            return [AllowAny()]

        return [IsAuthenticated(), IsContentAdmin()]

    def get_queryset(self):
        user = self.request.user

        queryset = FAQItem.objects.select_related("category").all()

        if not (
            user.is_authenticated
            and (user.is_staff or user.is_superuser)
        ):
            queryset = queryset.filter(
                is_active=True,
                category__is_active=True,
            )

        category = self.request.query_params.get("category")
        is_featured = self.request.query_params.get("is_featured")
        is_active = self.request.query_params.get("is_active")

        if category:
            queryset = queryset.filter(category_id=category)

        if is_featured is not None:
            if is_featured.lower() == "true":
                queryset = queryset.filter(is_featured=True)
            elif is_featured.lower() == "false":
                queryset = queryset.filter(is_featured=False)

        if is_active is not None and user.is_authenticated and (user.is_staff or user.is_superuser):
            if is_active.lower() == "true":
                queryset = queryset.filter(is_active=True)
            elif is_active.lower() == "false":
                queryset = queryset.filter(is_active=False)

        return queryset.order_by("category__order", "order", "question")


class AnnouncementViewSet(viewsets.ModelViewSet):
    serializer_class = AnnouncementSerializer

    def get_permissions(self):
        if self.action in ["list", "retrieve"]:
            return [AllowAny()]

        return [IsAuthenticated(), IsContentAdmin()]

    def get_queryset(self):
        user = self.request.user

        queryset = Announcement.objects.all()

        if not (
            user.is_authenticated
            and (user.is_staff or user.is_superuser)
        ):
            queryset = visible_now_queryset(queryset)

        placement = self.request.query_params.get("placement")
        level = self.request.query_params.get("level")
        status_filter = self.request.query_params.get("status")

        if placement:
            queryset = queryset.filter(placement=placement)

        if level:
            queryset = queryset.filter(level=level)

        if status_filter and user.is_authenticated and (user.is_staff or user.is_superuser):
            queryset = queryset.filter(status=status_filter)

        return queryset.order_by("order", "-created_at")

    @action(
        detail=True,
        methods=["post"],
        url_path="publish",
        permission_classes=[IsAuthenticated, IsContentAdmin],
    )
    def publish(self, request, pk=None):
        announcement = self.get_object()
        announcement.publish()

        serializer = self.get_serializer(announcement)

        return Response(serializer.data, status=status.HTTP_200_OK)

    @action(
        detail=True,
        methods=["post"],
        url_path="archive",
        permission_classes=[IsAuthenticated, IsContentAdmin],
    )
    def archive(self, request, pk=None):
        announcement = self.get_object()
        announcement.archive()

        serializer = self.get_serializer(announcement)

        return Response(serializer.data, status=status.HTTP_200_OK)