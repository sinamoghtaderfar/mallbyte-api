from django.contrib import admin

from apps.content.models import (
    Announcement,
    Banner,
    ContentPage,
    FAQCategory,
    FAQItem,
)


@admin.register(ContentPage)
class ContentPageAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "title",
        "slug",
        "page_type",
        "status",
        "is_featured",
        "order",
        "published_at",
        "created_at",
    )

    list_filter = (
        "status",
        "page_type",
        "is_featured",
        "published_at",
        "created_at",
    )

    search_fields = (
        "title",
        "slug",
        "excerpt",
        "content",
        "meta_title",
        "meta_description",
    )

    prepopulated_fields = {
        "slug": ("title",),
    }

    readonly_fields = (
        "created_at",
        "updated_at",
    )

    fieldsets = (
        (
            "Content",
            {
                "fields": (
                    "title",
                    "slug",
                    "page_type",
                    "excerpt",
                    "content",
                    "is_featured",
                    "order",
                )
            },
        ),
        (
            "Publishing",
            {
                "fields": (
                    "status",
                    "published_at",
                    "starts_at",
                    "ends_at",
                )
            },
        ),
        (
            "SEO",
            {
                "fields": (
                    "meta_title",
                    "meta_description",
                    "meta_keywords",
                )
            },
        ),
        (
            "Ownership",
            {
                "fields": (
                    "created_by",
                    "updated_by",
                )
            },
        ),
        (
            "Timestamps",
            {
                "fields": (
                    "created_at",
                    "updated_at",
                )
            },
        ),
    )


@admin.register(Banner)
class BannerAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "title",
        "placement",
        "status",
        "order",
        "starts_at",
        "ends_at",
        "created_at",
    )

    list_filter = (
        "status",
        "placement",
        "is_clickable",
        "starts_at",
        "ends_at",
        "created_at",
    )

    search_fields = (
        "title",
        "subtitle",
        "cta_text",
        "link_url",
    )

    readonly_fields = (
        "created_at",
        "updated_at",
    )

    fieldsets = (
        (
            "Banner",
            {
                "fields": (
                    "title",
                    "subtitle",
                    "image",
                    "mobile_image",
                    "placement",
                    "order",
                )
            },
        ),
        (
            "CTA",
            {
                "fields": (
                    "cta_text",
                    "link_url",
                    "is_clickable",
                )
            },
        ),
        (
            "Style",
            {
                "fields": (
                    "background_color",
                    "text_color",
                )
            },
        ),
        (
            "Publishing",
            {
                "fields": (
                    "status",
                    "published_at",
                    "starts_at",
                    "ends_at",
                )
            },
        ),
        (
            "Timestamps",
            {
                "fields": (
                    "created_at",
                    "updated_at",
                )
            },
        ),
    )


class FAQItemInline(admin.TabularInline):
    model = FAQItem
    extra = 0
    fields = (
        "question",
        "answer",
        "is_active",
        "is_featured",
        "order",
    )


@admin.register(FAQCategory)
class FAQCategoryAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "name",
        "slug",
        "is_active",
        "order",
        "created_at",
    )

    list_filter = (
        "is_active",
        "created_at",
    )

    search_fields = (
        "name",
        "slug",
        "description",
    )

    prepopulated_fields = {
        "slug": ("name",),
    }

    readonly_fields = (
        "created_at",
        "updated_at",
    )

    inlines = [FAQItemInline]


@admin.register(FAQItem)
class FAQItemAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "question",
        "category",
        "is_active",
        "is_featured",
        "order",
        "created_at",
    )

    list_filter = (
        "category",
        "is_active",
        "is_featured",
        "created_at",
    )

    search_fields = (
        "question",
        "answer",
        "category__name",
    )

    readonly_fields = (
        "created_at",
        "updated_at",
    )


@admin.register(Announcement)
class AnnouncementAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "title",
        "level",
        "placement",
        "status",
        "is_dismissible",
        "order",
        "starts_at",
        "ends_at",
        "created_at",
    )

    list_filter = (
        "status",
        "level",
        "placement",
        "is_dismissible",
        "starts_at",
        "ends_at",
        "created_at",
    )

    search_fields = (
        "title",
        "message",
        "link_text",
        "link_url",
    )

    readonly_fields = (
        "created_at",
        "updated_at",
    )

    fieldsets = (
        (
            "Announcement",
            {
                "fields": (
                    "title",
                    "message",
                    "level",
                    "placement",
                    "order",
                )
            },
        ),
        (
            "Link",
            {
                "fields": (
                    "link_text",
                    "link_url",
                    "is_dismissible",
                )
            },
        ),
        (
            "Publishing",
            {
                "fields": (
                    "status",
                    "published_at",
                    "starts_at",
                    "ends_at",
                )
            },
        ),
        (
            "Timestamps",
            {
                "fields": (
                    "created_at",
                    "updated_at",
                )
            },
        ),
    )