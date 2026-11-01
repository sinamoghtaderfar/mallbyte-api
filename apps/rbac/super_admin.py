"""Super administrator operations. Privileged actions never trust frontend gates."""
from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Q, Sum
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import Seller
from apps.orders.models import Order
from apps.products.models import Product
from apps.support.models import SupportTicket
from .models import Role, RolePermission, UserRole, AdminLog
from .permissions import IsSuperAdmin
from .serializers import RoleSerializer, PermissionSerializer, AdminLogSerializer, UserRoleSerializer
from .utils import assign_role, remove_role, clear_role_permissions_cache, log_admin_action

User = get_user_model()


class ConsoleUserSerializer(serializers.ModelSerializer):
    roles = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ("id", "email", "full_name", "phone", "is_active", "is_staff",
                  "is_superuser", "is_seller", "email_verified", "date_joined", "roles")
        read_only_fields = fields

    def get_roles(self, obj):
        return [
            {"id": ur.role_id, "name": ur.role.name}
            for ur in obj.user_roles.all()
            if ur.is_active and not ur.is_expired
        ]


class UserStatusSerializer(serializers.Serializer):
    is_active = serializers.BooleanField()
    reason = serializers.CharField(max_length=500, min_length=5, trim_whitespace=True)


class ConsoleUsersViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = ConsoleUserSerializer
    permission_classes = [IsSuperAdmin]

    def get_queryset(self):
        queryset = User.objects.select_related().prefetch_related("user_roles__role")
        search = self.request.query_params.get("search", "").strip()
        if search:
            queryset = queryset.filter(
                Q(email__icontains=search) | Q(full_name__icontains=search)
            )
        active = self.request.query_params.get("active")
        if active in ("true", "false"):
            queryset = queryset.filter(is_active=(active == "true"))
        return queryset.order_by("-date_joined")

    @action(detail=True, methods=["post"], url_path="set-status")
    def set_status(self, request, pk=None):
        target = self.get_object()
        payload = UserStatusSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        desired = payload.validated_data["is_active"]
        if target.is_superuser or target.is_staff or target.pk == request.user.pk:
            return Response(
                {"detail": "Privileged accounts cannot be changed here."},
                status=status.HTTP_403_FORBIDDEN,
            )
        with transaction.atomic():
            target.is_active = desired
            target.save(update_fields=["is_active"])
            log_admin_action(
                admin=request.user,
                action="activate_user" if desired else "suspend_user",
                target_user=target,
                details={"reason": payload.validated_data["reason"]},
                request=request,
            )
        return Response(self.get_serializer(target).data)


class ConsoleOverviewView(APIView):
    permission_classes = [IsSuperAdmin]

    def get(self, request):
        return Response({
            "users": User.objects.count(),
            "active_users": User.objects.filter(is_active=True).count(),
            "sellers": Seller.objects.count(),
            "pending_sellers": Seller.objects.filter(status=Seller.StatusChoices.PENDING).count(),
            "products": Product.objects.count(),
            "pending_products": Product.objects.filter(status=Product.StatusChoices.PENDING).count(),
            "orders": Order.objects.count(),
            "open_tickets": SupportTicket.objects.exclude(status__in=[
                SupportTicket.StatusChoices.RESOLVED, SupportTicket.StatusChoices.CLOSED
            ]).count(),
            "roles": Role.objects.count(),
            "recent_admin_actions": AdminLog.objects.count(),
        })


class ConsoleProductSerializer(serializers.ModelSerializer):
    seller_email = serializers.EmailField(source="seller.email", read_only=True)

    class Meta:
        model = Product
        fields = ("id", "name", "sku", "status", "is_active", "is_featured", "seller_email", "created_at")
        read_only_fields = fields


class ConsoleProductsViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [IsSuperAdmin]
    serializer_class = ConsoleProductSerializer

    def get_queryset(self):
        queryset = Product.objects.select_related("seller")
        requested = self.request.query_params.get("status", "")
        if requested in dict(Product.StatusChoices.choices):
            queryset = queryset.filter(status=requested)
        search = self.request.query_params.get("search", "").strip()
        if search:
            queryset = queryset.filter(Q(name__icontains=search) | Q(sku__icontains=search))
        return queryset.order_by("-created_at")


class ConsoleRolesView(APIView):
    permission_classes = [IsSuperAdmin]

    def get(self, request):
        return Response({
            "roles": RoleSerializer(Role.objects.prefetch_related("role_permissions__permission"), many=True).data,
            "permissions": PermissionSerializer(__import__("apps.rbac.models", fromlist=["Permission"]).Permission.objects.all(), many=True).data,
        })


class ConsoleRolePermissionView(APIView):
    permission_classes = [IsSuperAdmin]

    def post(self, request, pk):
        role = Role.objects.filter(pk=pk).first()
        if not role:
            return Response({"detail": "Role not found."}, status=404)
        if role.is_system_role:
            return Response({"detail": "System role permissions are protected."}, status=403)
        permission_id = request.data.get("permission_id")
        from .models import Permission
        permission = Permission.objects.filter(pk=permission_id).first()
        if not permission:
            raise ValidationError({"permission_id": "Invalid permission."})
        enabled = request.data.get("enabled")
        if not isinstance(enabled, bool):
            raise ValidationError({"enabled": "Expected boolean."})
        with transaction.atomic():
            if enabled:
                RolePermission.objects.get_or_create(role=role, permission=permission)
            else:
                RolePermission.objects.filter(role=role, permission=permission).delete()
            clear_role_permissions_cache(role)
            log_admin_action(
                admin=request.user, action="change_permission", target_role=role,
                details={"permission": permission.codename, "enabled": enabled}, request=request,
            )
        return Response(RoleSerializer(role).data)
