"""Explicit OpenAPI contracts; runtime API views and authorization stay intact."""
from importlib import import_module

from django.conf import settings
from drf_spectacular.contrib.rest_framework_simplejwt import SimpleJWTScheme
from drf_spectacular.extensions import OpenApiViewExtension
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, PolymorphicProxySerializer, extend_schema, extend_schema_view
from rest_framework import serializers

from apps.accounts.mfa_views import SetupInput, VerifyInput
from apps.accounts.models import Address
from apps.accounts.serializers import (
    ChangePasswordSerializer,
    DeleteAccountSerializer,
    EmailVerifyConfirmSerializer,
    EmailVerifyRequestSerializer,
    OTPRequestSerializer,
    OTPVerifySerializer,
    PasswordResetRequestSerializer,
    PasswordResetVerifySerializer,
    RegisterSerializer,
    SellerSerializer,
    UserSerializer,
)
from apps.rbac.serializers import AssignRoleSerializer, BulkAssignRoleSerializer, CheckPermissionSerializer, PermissionSerializer, RoleSerializer, UserPermissionsSerializer, UserRoleSerializer


class MFAGuardedJWTScheme(SimpleJWTScheme):
    """The custom authenticator retains the SimpleJWT Bearer header contract."""

    target_class = "apps.accounts.mfa_authentication.MFAGuardedJWTAuthentication"
    priority = 1


def _document_view(target, *, model=None, **methods):
    """Return a schema-only subclass, leaving the routed class untouched."""

    class Contract(OpenApiViewExtension):
        target_class = target

        def view_replacement(self):
            attributes = {}
            if model is not None:
                def get_queryset(view):
                    # Schema inference has no authenticated user or real rows.
                    return model.objects.none()
                attributes["get_queryset"] = get_queryset
            documented = type(f"{self.target.__name__}OpenAPI", (self.target,), attributes)
            return extend_schema_view(**methods)(documented)


class MessageResponse(serializers.Serializer):
    message = serializers.CharField()


class DetailErrorResponse(serializers.Serializer):
    detail = serializers.CharField()


class ErrorResponse(serializers.Serializer):
    error = serializers.CharField()


class AccessTokenResponse(serializers.Serializer):
    access = serializers.CharField()


class EmailPasswordInput(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)


class AuthenticatedUserResponse(AccessTokenResponse):
    user = UserSerializer()
    is_new = serializers.BooleanField()


class MFAEnrollmentResponse(AuthenticatedUserResponse):
    recovery_codes = serializers.ListField(child=serializers.CharField(), min_length=10, max_length=10)


class MFAChallengeResponse(serializers.Serializer):
    mfa_required = serializers.BooleanField()
    challenge = serializers.CharField()
    mfa_enrolled = serializers.BooleanField()


class MFASetupResponse(MessageResponse):
    secret = serializers.CharField()
    otpauth_uri = serializers.CharField()


class RegistrationResponse(MessageResponse):
    user = UserSerializer()
    verification_required = serializers.BooleanField()


class OTPDeliveryResponse(MessageResponse):
    delivery_channel = serializers.ChoiceField(choices=["email"])
    email = serializers.CharField(help_text="Masked delivery address.")
    expires_in = serializers.IntegerField(min_value=1)


class PendingEmailResponse(MessageResponse):
    email = serializers.EmailField()


class SellerRejectionInput(serializers.Serializer):
    reason = serializers.CharField(min_length=3, max_length=2000)


class SellerDecisionResponse(MessageResponse):
    seller = SellerSerializer()


class DefaultAddressResponse(serializers.Serializer):
    status = serializers.CharField()


_document_view("apps.accounts.views.RegisterView", post=extend_schema(
    request=RegisterSerializer, responses={201: RegistrationResponse},
    description="Create a provisional account. Email OTP verification is required before a JWT session is issued.",
))
_document_view("apps.accounts.views.OTPRequestView", post=extend_schema(
    request=OTPRequestSerializer, responses={200: OTPDeliveryResponse, 503: ErrorResponse},
))
_document_view("apps.accounts.views.OTPVerifyView", post=extend_schema(
    request=OTPVerifySerializer,
    responses={200: PolymorphicProxySerializer(
        component_name="OTPVerificationResponse", serializers=[AuthenticatedUserResponse, MFAChallengeResponse], resource_type_field_name=None,
    ), 400: ErrorResponse, 403: ErrorResponse},
    description="Ordinary accounts receive an access JWT and an HttpOnly refresh cookie. Privileged accounts receive only a short-lived MFA challenge.",
))
_document_view("apps.accounts.mfa_views.AdminMFASetupView", post=extend_schema(
    request=SetupInput, responses={200: MFASetupResponse, 400: DetailErrorResponse, 409: DetailErrorResponse},
    description="Confirm the privileged account password and provision an authenticator using the first-factor challenge.",
))
_document_view("apps.accounts.mfa_views.AdminMFACompleteView", post=extend_schema(
    request=VerifyInput, responses={200: MFAEnrollmentResponse, 400: DetailErrorResponse},
    description="Complete enrollment with a six-digit TOTP; recovery codes are returned once. Refresh credentials are set in an HttpOnly cookie.",
))
_document_view("apps.accounts.mfa_views.AdminMFAVerifyView", post=extend_schema(
    request=VerifyInput, responses={200: AuthenticatedUserResponse, 400: DetailErrorResponse},
    description="Consume a first-factor challenge and one TOTP or unused recovery code. Refresh credentials are set in an HttpOnly cookie.",
))
_document_view("apps.accounts.views.ThrottledTokenObtainPairView", post=extend_schema(
    request=EmailPasswordInput, responses={200: AccessTokenResponse, 401: DetailErrorResponse, 403: DetailErrorResponse},
    description="Password login for verified ordinary accounts. Privileged accounts must use OTP followed by MFA. Refresh tokens are cookies, never JSON response fields.",
))
_refresh_cookie_name = getattr(settings, "AUTH_REFRESH_COOKIE_NAME", "mallbyte_refresh")
_document_view("apps.accounts.views.CookieTokenRefreshView", post=extend_schema(
    request=None, auth=[], parameters=[OpenApiParameter(_refresh_cookie_name, OpenApiTypes.STR, OpenApiParameter.COOKIE, required=True)],
    responses={200: AccessTokenResponse, 401: DetailErrorResponse},
    description="Read the HttpOnly refresh cookie and issue an access token; no JSON refresh token is accepted.",
))
_document_view("apps.accounts.views.LogoutView", post=extend_schema(
    request=None, auth=[], parameters=[OpenApiParameter(_refresh_cookie_name, OpenApiTypes.STR, OpenApiParameter.COOKIE)],
    responses={200: MessageResponse},
    description="Clear the refresh cookie and revoke a valid session supplied by refresh cookie or Bearer access token. Stale credentials are also cleared.",
))
_document_view("apps.accounts.views.PasswordResetRequestView", post=extend_schema(
    request=PasswordResetRequestSerializer, responses={200: OTPDeliveryResponse, 503: ErrorResponse},
))
for _target, _request in (
    ("PasswordResetVerifyView", PasswordResetVerifySerializer),
    ("ChangePasswordView", ChangePasswordSerializer),
    ("EmailVerifyConfirmView", EmailVerifyConfirmSerializer),
):
    _document_view(f"apps.accounts.views.{_target}", post=extend_schema(request=_request, responses={200: MessageResponse}))
_document_view("apps.accounts.views.EmailVerifyRequestView", post=extend_schema(
    request=EmailVerifyRequestSerializer, responses={200: PendingEmailResponse, 503: ErrorResponse},
))
_document_view("apps.accounts.views.DeleteAccountView", delete=extend_schema(
    request=DeleteAccountSerializer, responses={200: MessageResponse},
))
_document_view("apps.accounts.views.AdminDeleteUserView", delete=extend_schema(
    request=None, responses={200: MessageResponse, 400: ErrorResponse, 404: ErrorResponse},
))
_document_view("apps.accounts.views.AdminSellerVerifyView", post=extend_schema(request=None, responses={200: SellerDecisionResponse}))
_document_view("apps.accounts.views.AdminSellerRejectView", post=extend_schema(request=SellerRejectionInput, responses={200: SellerDecisionResponse}))
_document_view("apps.accounts.views.AddressViewSet", model=Address, set_default=extend_schema(request=None, responses={200: DefaultAddressResponse}))


class ConsoleOverviewResponse(serializers.Serializer):
    users = serializers.IntegerField()
    active_users = serializers.IntegerField()
    sellers = serializers.IntegerField()
    pending_sellers = serializers.IntegerField()
    products = serializers.IntegerField()
    pending_products = serializers.IntegerField()
    orders = serializers.IntegerField()
    open_tickets = serializers.IntegerField()
    roles = serializers.IntegerField()
    recent_admin_actions = serializers.IntegerField()


class RoleCatalogResponse(serializers.Serializer):
    roles = RoleSerializer(many=True)
    permissions = PermissionSerializer(many=True)


class PermissionIdInput(serializers.Serializer):
    permission_id = serializers.IntegerField(min_value=1, max_value=2**63 - 1)


class ConsolePermissionInput(PermissionIdInput):
    enabled = serializers.BooleanField()


class CurrentPermissionsResponse(serializers.Serializer):
    user_id = serializers.IntegerField()
    email = serializers.EmailField()
    permissions = serializers.ListField(child=serializers.CharField())
    permissions_count = serializers.IntegerField()


class PermissionCheckResponse(serializers.Serializer):
    user_id = serializers.IntegerField()
    user_email = serializers.EmailField()
    permission = serializers.CharField()
    has_permission = serializers.BooleanField()


class RoleAssignmentResult(serializers.Serializer):
    user_id = serializers.IntegerField()
    user_email = serializers.EmailField()
    role_id = serializers.IntegerField()
    role_name = serializers.CharField()
    user_role_id = serializers.IntegerField()
    assigned_at = serializers.DateTimeField()


class RoleAssignmentError(serializers.Serializer):
    user_id = serializers.IntegerField()
    user_email = serializers.EmailField()
    role_id = serializers.IntegerField()
    role_name = serializers.CharField()
    error = serializers.CharField()


class RoleAssignmentSummary(serializers.Serializer):
    total_users = serializers.IntegerField()
    total_roles = serializers.IntegerField()
    total_assignments = serializers.IntegerField()
    total_errors = serializers.IntegerField()


class BulkRoleAssignmentResponse(serializers.Serializer):
    success = serializers.BooleanField()
    assigned = RoleAssignmentResult(many=True)
    errors = RoleAssignmentError(many=True)
    summary = RoleAssignmentSummary()


_document_view("apps.rbac.super_admin.ConsoleOverviewView", get=extend_schema(responses=ConsoleOverviewResponse))
_document_view("apps.rbac.super_admin.ConsoleRolesView", get=extend_schema(responses=RoleCatalogResponse))
_document_view("apps.rbac.super_admin.ConsoleRolePermissionView", post=extend_schema(request=ConsolePermissionInput, responses=RoleSerializer))
_document_view("apps.rbac.views.MyPermissionsView", get=extend_schema(responses=CurrentPermissionsResponse))
_document_view("apps.rbac.views.UserPermissionsView", get=extend_schema(responses=UserPermissionsSerializer))
_document_view("apps.rbac.views.RemoveRoleView", delete=extend_schema(request=None, responses={200: MessageResponse}))
_document_view("apps.rbac.views.AssignRoleView", post=extend_schema(request=AssignRoleSerializer, responses={201: UserRoleSerializer}))
_document_view("apps.rbac.views.BulkAssignRolesView", post=extend_schema(request=BulkAssignRoleSerializer, responses={201: BulkRoleAssignmentResponse, 207: BulkRoleAssignmentResponse}))
_document_view("apps.rbac.views.CheckPermissionView", post=extend_schema(request=CheckPermissionSerializer, responses=PermissionCheckResponse))
_document_view("apps.rbac.views.RoleViewSet",
    add_permission=extend_schema(request=PermissionIdInput, responses={200: MessageResponse, 201: MessageResponse}),
    remove_permission=extend_schema(request=PermissionIdInput, responses={200: MessageResponse}),
    permissions=extend_schema(responses={200: {
        "type": "array", "items": {
            "type": "object", "properties": {
                "id": {"type": "integer"}, "role": {"type": "integer"}, "role_name": {"type": "string"},
                "permission": {"type": "integer"}, "permission_name": {"type": "string"}, "permission_codename": {"type": "string"},
            }, "required": ["id", "role", "role_name", "permission", "permission_name", "permission_codename"],
        },
    }}),
)

# Separate domain modules keep contracts reviewable without patching handlers.
import_module("config.openapi_fields")
import_module("config.openapi_finance")
import_module("config.openapi_commerce")
import_module("config.openapi_returns")
