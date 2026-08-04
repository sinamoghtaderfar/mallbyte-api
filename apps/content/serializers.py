from rest_framework import serializers

from apps.content.models import (
    Announcement,
    Banner,
    ContentPage,
    FAQCategory,
    FAQItem,
    NavigationItem,
    NavigationMenu,
)

class ContentPageSerializer(serializers.ModelSerializer):
    created_by_display = serializers.CharField(
        source="created_by.full_name",
        read_only=True,
    )
    updated_by_display = serializers.CharField(
        source="updated_by.full_name",
        read_only=True,
    )
    is_visible = serializers.SerializerMethodField()

    class Meta:
        model = ContentPage
        fields = [
            "id",
            "title",
            "slug",
            "page_type",
            "excerpt",
            "content",
            "status",
            "published_at",
            "starts_at",
            "ends_at",
            "is_visible",
            "is_featured",
            "order",
            "meta_title",
            "meta_description",
            "meta_keywords",
            "created_by",
            "created_by_display",
            "updated_by",
            "updated_by_display",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "created_by",
            "created_by_display",
            "updated_by",
            "updated_by_display",
            "created_at",
            "updated_at",
            "is_visible",
        ]

    def get_is_visible(self, obj):
        return obj.is_visible_now()


class BannerSerializer(serializers.ModelSerializer):
    is_visible = serializers.SerializerMethodField()

    class Meta:
        model = Banner
        fields = [
            "id",
            "title",
            "subtitle",
            "image",
            "mobile_image",
            "placement",
            "cta_text",
            "link_url",
            "background_color",
            "text_color",
            "order",
            "is_clickable",
            "status",
            "published_at",
            "starts_at",
            "ends_at",
            "is_visible",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "created_at",
            "updated_at",
            "is_visible",
        ]

    def get_is_visible(self, obj):
        return obj.is_visible_now()


class FAQItemSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(
        source="category.name",
        read_only=True,
    )

    class Meta:
        model = FAQItem
        fields = [
            "id",
            "category",
            "category_name",
            "question",
            "answer",
            "is_active",
            "is_featured",
            "order",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "category_name",
            "created_at",
            "updated_at",
        ]


class FAQCategorySerializer(serializers.ModelSerializer):
    items = serializers.SerializerMethodField()

    class Meta:
        model = FAQCategory
        fields = [
            "id",
            "name",
            "slug",
            "description",
            "is_active",
            "order",
            "items",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "slug",
            "items",
            "created_at",
            "updated_at",
        ]

    def get_items(self, obj):
        request = self.context.get("request")

        items = obj.items.all()

        if not (
            request
            and request.user.is_authenticated
            and (request.user.is_staff or request.user.is_superuser)
        ):
            items = items.filter(is_active=True)

        return FAQItemSerializer(items, many=True).data


class AnnouncementSerializer(serializers.ModelSerializer):
    is_visible = serializers.SerializerMethodField()

    class Meta:
        model = Announcement
        fields = [
            "id",
            "title",
            "message",
            "level",
            "placement",
            "link_text",
            "link_url",
            "is_dismissible",
            "order",
            "status",
            "published_at",
            "starts_at",
            "ends_at",
            "is_visible",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "is_visible",
            "created_at",
            "updated_at",
        ]

    def get_is_visible(self, obj):
        return obj.is_visible_now()
    
class NavigationItemSerializer(serializers.ModelSerializer):
    url = serializers.CharField(source="resolved_url", read_only=True)
    page_slug = serializers.CharField(source="page.slug", read_only=True)
    page_title = serializers.CharField(source="page.title", read_only=True)
    children = serializers.SerializerMethodField()

    class Meta:
        model = NavigationItem
        fields = [
            "id",
            "label",
            "url",
            "link_url",
            "page",
            "page_slug",
            "page_title",
            "icon",
            "is_active",
            "requires_auth",
            "open_in_new_tab",
            "order",
            "children",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "url",
            "page_slug",
            "page_title",
            "children",
            "created_at",
            "updated_at",
        ]

    def get_children(self, obj):
        request = self.context.get("request")

        children = obj.children.select_related("page").all()

        if not (
            request
            and request.user.is_authenticated
            and (request.user.is_staff or request.user.is_superuser)
        ):
            children = children.filter(is_active=True)

        if not (request and request.user.is_authenticated):
            children = children.filter(requires_auth=False)

        children = children.order_by("order", "label")

        return NavigationItemSerializer(
            children,
            many=True,
            context=self.context,
        ).data


class NavigationMenuSerializer(serializers.ModelSerializer):
    items = serializers.SerializerMethodField()

    class Meta:
        model = NavigationMenu
        fields = [
            "id",
            "name",
            "slug",
            "placement",
            "is_active",
            "order",
            "items",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "slug",
            "items",
            "created_at",
            "updated_at",
        ]

    def get_items(self, obj):
        request = self.context.get("request")

        items = obj.items.select_related("page").filter(parent__isnull=True)

        if not (
            request
            and request.user.is_authenticated
            and (request.user.is_staff or request.user.is_superuser)
        ):
            items = items.filter(is_active=True)

        if not (request and request.user.is_authenticated):
            items = items.filter(requires_auth=False)

        items = items.order_by("order", "label")

        return NavigationItemSerializer(
            items,
            many=True,
            context=self.context,
        ).data