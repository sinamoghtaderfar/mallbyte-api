"""Typed CMS contracts. All HTML-like text is untrusted and remains plain text."""
from rest_framework import serializers
from apps.content.models import (
    Announcement, Banner, ContentPage, FAQCategory, FAQItem,
    NavigationItem, NavigationMenu,
)
from apps.content.validators import (
    reject_direct_publication, validate_image_upload, validate_link,
    validate_plain_text, validate_publication_window,
)
from apps.content.visibility import visible_nav_items, can_view_unpublished


class PublicationSerializerMixin:
    def validate(self, attrs):
        reject_direct_publication(self.initial_data)
        validate_publication_window(attrs, self.instance)
        return attrs


class ContentPageSerializer(PublicationSerializerMixin, serializers.ModelSerializer):
    created_by_display = serializers.CharField(source="created_by.full_name", read_only=True)
    updated_by_display = serializers.CharField(source="updated_by.full_name", read_only=True)
    is_visible = serializers.SerializerMethodField()
    slug = serializers.SlugField(required=False, allow_blank=True, max_length=255)

    class Meta:
        model = ContentPage
        fields = [
            "id", "title", "slug", "page_type", "excerpt", "content",
            "status", "published_at", "starts_at", "ends_at", "is_visible",
            "is_featured", "order", "meta_title", "meta_description",
            "meta_keywords", "created_by", "created_by_display", "updated_by",
            "updated_by_display", "created_at", "updated_at",
        ]
        read_only_fields = [
            "id", "status", "published_at", "created_by", "created_by_display",
            "updated_by", "updated_by_display", "created_at", "updated_at",
        ]

    def get_is_visible(self, obj):
        return obj.is_visible_now()

    def validate_content(self, value):
        return validate_plain_text(value)

    def validate_excerpt(self, value):
        return validate_plain_text(value)


class BannerSerializer(PublicationSerializerMixin, serializers.ModelSerializer):
    is_visible = serializers.SerializerMethodField()

    class Meta:
        model = Banner
        fields = [
            "id", "title", "subtitle", "image", "mobile_image", "placement",
            "cta_text", "link_url", "background_color", "text_color", "order",
            "is_clickable", "status", "published_at", "starts_at", "ends_at",
            "is_visible", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "status", "published_at", "created_at", "updated_at"]

    def get_is_visible(self, obj):
        return obj.is_visible_now()

    def validate_link_url(self, value):
        return validate_link(value)

    def validate_subtitle(self, value):
        return validate_plain_text(value)

    def validate_image(self, value):
        return validate_image_upload(value)

    def validate_mobile_image(self, value):
        return validate_image_upload(value)


class FAQItemSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source="category.name", read_only=True)

    class Meta:
        model = FAQItem
        fields = [
            "id", "category", "category_name", "question", "answer",
            "is_active", "is_featured", "order", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "category_name", "created_at", "updated_at"]

    def validate_answer(self, value):
        return validate_plain_text(value)


class FAQCategorySerializer(serializers.ModelSerializer):
    items = serializers.SerializerMethodField()

    class Meta:
        model = FAQCategory
        fields = [
            "id", "name", "slug", "description", "is_active", "order",
            "items", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "slug", "items", "created_at", "updated_at"]

    def get_items(self, obj):
        request = self.context.get("request")
        items = obj.items.all()
        if not request or not can_view_unpublished(request.user):
            items = items.filter(is_active=True)
        return FAQItemSerializer(items, many=True, context=self.context).data


class AnnouncementSerializer(PublicationSerializerMixin, serializers.ModelSerializer):
    is_visible = serializers.SerializerMethodField()

    class Meta:
        model = Announcement
        fields = [
            "id", "title", "message", "level", "placement", "link_text",
            "link_url", "is_dismissible", "order", "status", "published_at",
            "starts_at", "ends_at", "is_visible", "created_at", "updated_at",
        ]
        read_only_fields = [
            "id", "status", "published_at", "created_at", "updated_at",
        ]

    def get_is_visible(self, obj):
        return obj.is_visible_now()

    def validate_message(self, value):
        return validate_plain_text(value)

    def validate_link_url(self, value):
        return validate_link(value)


class NavigationItemSerializer(serializers.ModelSerializer):
    url = serializers.CharField(source="resolved_url", read_only=True)
    page_slug = serializers.CharField(source="page.slug", read_only=True, allow_null=True)
    page_title = serializers.CharField(source="page.title", read_only=True, allow_null=True)
    children = serializers.SerializerMethodField()

    class Meta:
        model = NavigationItem
        fields = [
            "id", "menu", "parent", "label", "url", "link_url", "page",
            "page_slug", "page_title", "icon", "is_active", "requires_auth",
            "open_in_new_tab", "order", "children", "created_at", "updated_at",
        ]
        read_only_fields = [
            "id", "url", "page_slug", "page_title", "children", "created_at", "updated_at",
        ]

    def validate_link_url(self, value):
        return validate_link(value)

    def validate(self, attrs):
        menu = attrs.get("menu", getattr(self.instance, "menu", None))
        parent = attrs.get("parent", getattr(self.instance, "parent", None))
        if parent:
            if parent.parent_id is not None:
                raise serializers.ValidationError({
                    "parent": "Navigation supports only two levels."
                })
            if menu and parent.menu_id != menu.pk:
                raise serializers.ValidationError({
                    "parent": "Parent item must belong to the same menu."
                })
            cursor, seen = parent, set()
            while cursor and cursor.pk not in seen:
                if self.instance and cursor.pk == self.instance.pk:
                    raise serializers.ValidationError({"parent": "Navigation hierarchy cycle."})
                seen.add(cursor.pk)
                cursor = cursor.parent
        if self.instance and menu and menu.pk != self.instance.menu_id:
            if self.instance.children.exclude(menu_id=menu.pk).exists():
                raise serializers.ValidationError({
                    "menu": "Move or remove child items before moving a parent."
                })
        return attrs

    def get_children(self, obj):
        request = self.context.get("request")
        children = obj.children.select_related("page", "menu").all()
        if request:
            children = visible_nav_items(children, request.user)
        else:
            from django.contrib.auth.models import AnonymousUser
            children = visible_nav_items(children, AnonymousUser())
        return NavigationItemSerializer(
            children.order_by("order", "label"), many=True, context=self.context
        ).data


class NavigationMenuSerializer(serializers.ModelSerializer):
    items = serializers.SerializerMethodField()

    class Meta:
        model = NavigationMenu
        fields = [
            "id", "name", "slug", "placement", "is_active", "order",
            "items", "created_at", "updated_at",
        ]
        read_only_fields = [
            "id", "slug", "items", "created_at", "updated_at",
        ]

    def get_items(self, obj):
        request = self.context.get("request")
        qs = obj.items.select_related("page", "menu").filter(parent__isnull=True)
        if request:
            qs = visible_nav_items(qs, request.user)
        else:
            from django.contrib.auth.models import AnonymousUser
            qs = visible_nav_items(qs, AnonymousUser())
        return NavigationItemSerializer(
            qs.order_by("order", "label"), many=True, context=self.context
        ).data
