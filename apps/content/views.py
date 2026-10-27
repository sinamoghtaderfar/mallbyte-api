"""CMS REST endpoints: public storefront reads, scoped editorial writes.

Only publishing permission can change a public publishable object. Authorization
never relies solely on is_staff; Next.js Content Managers need no staff flag.
"""
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import JSONParser, MultiPartParser, FormParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.content.models import (
    Announcement, Banner, ContentPage, FAQCategory, FAQItem,
    NavigationItem, NavigationMenu,
)
from apps.content.permissions import ContentPermission, EDIT, PUBLISH, VIEW
from apps.content.permissions import content_has
from apps.content.serializers import (
    AnnouncementSerializer, BannerSerializer, ContentPageSerializer,
    FAQCategorySerializer, FAQItemSerializer, NavigationItemSerializer,
    NavigationMenuSerializer,
)
from apps.content.validators import validate_publication_window
from apps.content.visibility import can_view_unpublished, visible_nav_items
from apps.observability.models import AuditLog


def visible_now_queryset(qs):
    now = timezone.now()
    return qs.filter(status=ContentPage.StatusChoices.PUBLISHED).filter(
        Q(starts_at__isnull=True) | Q(starts_at__lte=now)
    ).filter(Q(ends_at__isnull=True) | Q(ends_at__gte=now))


def log_cms_action(request, instance, action, *, detail=""):
    """Durable audit trail with no customer details or content bodies."""
    AuditLog.objects.create(
        actor=request.user,
        action=action,
        object_type=f"cms.{instance._meta.model_name}",
        object_id=str(instance.pk),
        description=f"CMS {action}: {instance._meta.model_name}",
        metadata={"detail": detail, "status": getattr(instance, "status", None)},
    )


class CMSViewSet(viewsets.ModelViewSet):
    """Inherited GET stays public; backend write and publish ACLs are separate."""

    def get_permissions(self):
        if self.action in ("list", "retrieve"):
            return [AllowAny()]
        codename = PUBLISH if self.action in ("publish", "archive") else EDIT
        return [IsAuthenticated(), ContentPermission(codename)]

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        return super().create(request, *args, **kwargs)

    @transaction.atomic
    def update(self, request, *args, **kwargs):
        return super().update(request, *args, **kwargs)

    @transaction.atomic
    def partial_update(self, request, *args, **kwargs):
        return super().partial_update(request, *args, **kwargs)

    @transaction.atomic
    def destroy(self, request, *args, **kwargs):
        obj = self.get_object()
        log_cms_action(request, obj, AuditLog.ActionChoices.DELETE)
        return super().destroy(request, *args, **kwargs)

    def perform_create(self, serializer):
        model = serializer.Meta.model
        if hasattr(model, "is_active") and not content_has(self.request.user, PUBLISH):
            if serializer.validated_data.get("is_active", False):
                raise serializers.ValidationError({
                    "is_active": "Publishing an active CMS item requires publish_content."
                })
            obj = serializer.save(is_active=False)
        else:
            obj = serializer.save()
        log_cms_action(self.request, obj, AuditLog.ActionChoices.CREATE)

    def perform_update(self, serializer):
        if (serializer.validated_data.get("is_active") is True
                and not content_has(self.request.user, PUBLISH)):
            raise serializers.ValidationError({
                "is_active": "Activating CMS content requires publish_content."
            })
        obj = serializer.save()
        log_cms_action(self.request, obj, AuditLog.ActionChoices.UPDATE)

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        # Responses depend on token permissions, and can contain unpublished data.
        response["Cache-Control"] = "private, no-store"
        return response


class PublishableCMSViewSet(CMSViewSet):
    @action(detail=True, methods=["post"], url_path="publish")
    @transaction.atomic
    def publish(self, request, **kwargs):
        obj = self.get_object()
        validate_publication_window({}, obj)
        obj.publish()
        log_cms_action(request, obj, AuditLog.ActionChoices.APPROVE, detail="publish")
        return Response(self.get_serializer(obj).data, status=status.HTTP_200_OK)

    @action(detail=True, methods=["post"], url_path="archive")
    @transaction.atomic
    def archive(self, request, **kwargs):
        obj = self.get_object()
        obj.archive()
        log_cms_action(request, obj, AuditLog.ActionChoices.UPDATE, detail="archive")
        return Response(self.get_serializer(obj).data, status=status.HTTP_200_OK)


class ContentPageViewSet(PublishableCMSViewSet):
    serializer_class = ContentPageSerializer
    lookup_field = "slug"

    def get_queryset(self):
        qs = ContentPage.objects.select_related("created_by", "updated_by")
        viewer = can_view_unpublished(self.request.user)
        if not viewer:
            qs = visible_now_queryset(qs)
        page_type = self.request.query_params.get("page_type")
        featured = self.request.query_params.get("is_featured")
        status_filter = self.request.query_params.get("status")
        if page_type:
            qs = qs.filter(page_type=page_type)
        if featured in ("true", "false"):
            qs = qs.filter(is_featured=(featured == "true"))
        if status_filter and viewer:
            qs = qs.filter(status=status_filter)
        return qs.order_by("order", "title")

    def perform_create(self, serializer):
        obj = serializer.save(created_by=self.request.user, updated_by=self.request.user)
        log_cms_action(self.request, obj, AuditLog.ActionChoices.CREATE)

    def perform_update(self, serializer):
        obj = serializer.save(updated_by=self.request.user)
        log_cms_action(self.request, obj, AuditLog.ActionChoices.UPDATE)


class BannerViewSet(PublishableCMSViewSet):
    serializer_class = BannerSerializer
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def get_queryset(self):
        qs = Banner.objects.all()
        viewer = can_view_unpublished(self.request.user)
        if not viewer:
            qs = visible_now_queryset(qs)
        placement = self.request.query_params.get("placement")
        status_filter = self.request.query_params.get("status")
        if placement:
            qs = qs.filter(placement=placement)
        if status_filter and viewer:
            qs = qs.filter(status=status_filter)
        return qs.order_by("placement", "order", "-created_at")


class FAQCategoryViewSet(CMSViewSet):
    serializer_class = FAQCategorySerializer
    lookup_field = "slug"

    def get_queryset(self):
        qs = FAQCategory.objects.prefetch_related("items")
        viewer = can_view_unpublished(self.request.user)
        if not viewer:
            qs = qs.filter(is_active=True)
        active = self.request.query_params.get("is_active")
        if active in ("true", "false") and viewer:
            qs = qs.filter(is_active=(active == "true"))
        return qs.order_by("order", "name")


class FAQItemViewSet(CMSViewSet):
    serializer_class = FAQItemSerializer

    def get_queryset(self):
        qs = FAQItem.objects.select_related("category")
        viewer = can_view_unpublished(self.request.user)
        if not viewer:
            qs = qs.filter(is_active=True, category__is_active=True)
        category = self.request.query_params.get("category")
        featured = self.request.query_params.get("is_featured")
        active = self.request.query_params.get("is_active")
        if category:
            qs = qs.filter(category_id=category)
        if featured in ("true", "false"):
            qs = qs.filter(is_featured=(featured == "true"))
        if active in ("true", "false") and viewer:
            qs = qs.filter(is_active=(active == "true"))
        return qs.order_by("category__order", "order", "question")


class AnnouncementViewSet(PublishableCMSViewSet):
    serializer_class = AnnouncementSerializer

    def get_queryset(self):
        qs = Announcement.objects.all()
        viewer = can_view_unpublished(self.request.user)
        if not viewer:
            qs = visible_now_queryset(qs)
        placement = self.request.query_params.get("placement")
        level = self.request.query_params.get("level")
        status_filter = self.request.query_params.get("status")
        if placement:
            qs = qs.filter(placement=placement)
        if level:
            qs = qs.filter(level=level)
        if status_filter and viewer:
            qs = qs.filter(status=status_filter)
        return qs.order_by("order", "-created_at")


class NavigationMenuViewSet(CMSViewSet):
    serializer_class = NavigationMenuSerializer
    lookup_field = "slug"

    def get_queryset(self):
        qs = NavigationMenu.objects.prefetch_related("items", "items__children")
        viewer = can_view_unpublished(self.request.user)
        if not viewer:
            qs = qs.filter(is_active=True)
        placement = self.request.query_params.get("placement")
        active = self.request.query_params.get("is_active")
        if placement:
            qs = qs.filter(placement=placement)
        if active in ("true", "false") and viewer:
            qs = qs.filter(is_active=(active == "true"))
        return qs.order_by("placement", "order", "name")


class NavigationItemViewSet(CMSViewSet):
    serializer_class = NavigationItemSerializer

    def get_queryset(self):
        qs = NavigationItem.objects.select_related("menu", "parent", "page")
        qs = visible_nav_items(qs, self.request.user)
        menu = self.request.query_params.get("menu")
        parent = self.request.query_params.get("parent")
        if menu:
            qs = qs.filter(menu_id=menu)
        if parent:
            qs = qs.filter(parent_id=parent)
        return qs.order_by("menu__order", "parent_id", "order", "label")


class HomepageContentView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        banners = visible_now_queryset(Banner.objects.filter(placement__in=[
            Banner.PlacementChoices.HOME_HERO, Banner.PlacementChoices.HOME_TOP,
            Banner.PlacementChoices.HOME_MIDDLE, Banner.PlacementChoices.GLOBAL,
        ])).order_by("placement", "order", "-created_at")
        announcements = visible_now_queryset(Announcement.objects.filter(placement__in=[
            Announcement.PlacementChoices.GLOBAL, Announcement.PlacementChoices.HOME,
        ])).order_by("order", "-created_at")
        pages = visible_now_queryset(ContentPage.objects.filter(
            is_featured=True
        )).order_by("order", "title")
        faqs = FAQItem.objects.select_related("category").filter(
            is_active=True, is_featured=True, category__is_active=True,
        ).order_by("category__order", "order", "question")
        response = Response({
            "banners": BannerSerializer(banners, many=True, context={"request": request}).data,
            "announcements": AnnouncementSerializer(
                announcements, many=True, context={"request": request}
            ).data,
            "featured_pages": ContentPageSerializer(
                pages, many=True, context={"request": request}
            ).data,
            "featured_faqs": FAQItemSerializer(
                faqs, many=True, context={"request": request}
            ).data,
        }, status=status.HTTP_200_OK)
        response["Cache-Control"] = "private, no-store"
        return response
