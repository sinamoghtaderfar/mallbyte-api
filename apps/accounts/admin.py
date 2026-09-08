# apps/accounts/admin.py

from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from apps.accounts.models import OTP, Address, Profile, User
from apps.reviews.admin_roles import REVIEW_MODERATORS_GROUP_NAME, get_or_create_review_moderators_group

# ============================================================
# User Inlines
# ============================================================

class ProfileInline(admin.StackedInline):
    model = Profile
    extra = 0
    can_delete = False

    fields = [
        "avatar",
        "birth_date",
        "gender",
        "national_code",
        "loyalty_points",
        "created_at",
        "updated_at",
    ]

    readonly_fields = [
        "created_at",
        "updated_at",
    ]


class AddressInline(admin.TabularInline):
    model = Address
    extra = 0

    fields = [
        "title",
        "province",
        "city",
        "street",
        "postal_code",
        "receiver_name",
        "receiver_phone",
        "is_default",
        "created_at",
    ]

    readonly_fields = [
        "created_at",
    ]


# ============================================================
# User Admin
# ============================================================

@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    """
    Admin page for custom User model.

    The project uses phone number as the login field,
    so username is removed from the admin configuration.
    """

    model = User

    list_display = [
        "id",
        "phone",
        "email",
        "full_name",
        "is_seller",
        "email_verified",
        "is_staff",
        "is_review_moderator",
        "is_active",
        "is_deleted",
    ]

    list_filter = [
        "is_staff",
        "is_superuser",
        "is_active",
        "is_seller",
        "email_verified",
        "is_deleted",
        "groups",
    ]

    search_fields = [
        "phone",
        "email",
        "full_name",
    ]

    ordering = [
        "-id",
    ]

    readonly_fields = [
        "last_login",
        "date_joined",
        "deleted_at",
        "email_verified_at",
    ]

    filter_horizontal = [
        "groups",
        "user_permissions",
    ]

    inlines = [
        ProfileInline,
        AddressInline,
    ]

    fieldsets = (
        (
            "Login Info",
            {
                "fields": (
                    "phone",
                    "email",
                    "full_name",
                    "password",
                )
            },
        ),
        (
            "Business Info",
            {
                "fields": (
                    "is_seller",
                    "email_verified",
                    "email_verified_at",
                )
            },
        ),
        (
            "Permissions",
            {
                "fields": (
                    "is_active",
                    "is_staff",
                    "is_superuser",
                    "groups",
                    "user_permissions",
                )
            },
        ),
        (
            "Important Dates",
            {
                "fields": (
                    "last_login",
                    "date_joined",
                )
            },
        ),
        (
            "Soft Delete",
            {
                "fields": (
                    "is_deleted",
                    "deleted_at",
                )
            },
        ),
    )

    actions = [
        "make_review_moderators",
        "remove_review_moderator_role",
    ]

    @admin.display(boolean=True, description="Review moderator")
    def is_review_moderator(self, obj):
        return obj.groups.filter(name=REVIEW_MODERATORS_GROUP_NAME).exists()

    @admin.action(description="Make selected users review moderators")
    def make_review_moderators(self, request, queryset):
        if not request.user.is_superuser:
            self.message_user(
                request,
                "Only super admins can manage review moderator access.",
                messages.ERROR,
            )
            return

        group = get_or_create_review_moderators_group()

        updated_count = 0

        for user in queryset:
            user.is_staff = True
            user.is_superuser = False
            user.is_active = True
            user.save(update_fields=["is_staff", "is_superuser", "is_active"])
            user.groups.add(group)
            updated_count += 1

        self.message_user(
            request,
            f"{updated_count} user(s) can now moderate reviews.",
            messages.SUCCESS,
        )

    @admin.action(description="Remove review moderator role from selected users")
    def remove_review_moderator_role(self, request, queryset):
        if not request.user.is_superuser:
            self.message_user(
                request,
                "Only super admins can manage review moderator access.",
                messages.ERROR,
            )
            return

        group = get_or_create_review_moderators_group()
        updated_count = 0

        for user in queryset:
            user.groups.remove(group)
            updated_count += 1

        self.message_user(
            request,
            f"Removed review moderator access from {updated_count} user(s).",
            messages.SUCCESS,
        )

    add_fieldsets = (
        (
            "Create Admin/User",
            {
                "classes": ("wide",),
                "fields": (
                    "phone",
                    "email",
                    "full_name",
                    "password1",
                    "password2",
                    "is_active",
                    "is_staff",
                    "is_superuser",
                ),
            },
        ),
    )


# ============================================================
# Profile Admin
# ============================================================

@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "user",
        "gender",
        "national_code",
        "loyalty_points",
        "created_at",
    ]

    search_fields = [
        "user__phone",
        "user__email",
        "user__full_name",
        "national_code",
    ]

    list_filter = [
        "gender",
        "created_at",
    ]

    readonly_fields = [
        "created_at",
        "updated_at",
    ]

    list_select_related = [
        "user",
    ]


# ============================================================
# Address Admin
# ============================================================

@admin.register(Address)
class AddressAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "user",
        "title",
        "province",
        "city",
        "postal_code",
        "receiver_name",
        "receiver_phone",
        "is_default",
        "created_at",
    ]

    search_fields = [
        "user__phone",
        "user__email",
        "user__full_name",
        "title",
        "province",
        "city",
        "street",
        "postal_code",
        "receiver_name",
        "receiver_phone",
    ]

    list_filter = [
        "province",
        "city",
        "is_default",
        "created_at",
    ]

    readonly_fields = [
        "created_at",
        "updated_at",
    ]

    list_select_related = [
        "user",
    ]


# ============================================================
# OTP Admin
# ============================================================

@admin.register(OTP)
class OTPAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "phone",
        "code",
        "is_used",
        "expires_at",
        "created_at",
    ]

    search_fields = [
        "phone",
        "code",
    ]

    list_filter = [
        "is_used",
        "created_at",
        "expires_at",
    ]

    readonly_fields = [
        "phone",
        "code",
        "created_at",
        "expires_at",
        "is_used",
    ]

    date_hierarchy = "created_at"

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False