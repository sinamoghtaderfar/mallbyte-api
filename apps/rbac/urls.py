from django.urls import include, path
from .super_admin import ConsoleOverviewView, ConsoleUsersViewSet, ConsoleProductsViewSet, ConsoleRolesView, ConsoleRolePermissionView
from rest_framework.routers import DefaultRouter

from .views import (
    AdminLogDetailView,
    AdminLogListView,
    AssignRoleView,
    BulkAssignRolesView,
    CheckPermissionView,
    MyPermissionsView,
    PermissionViewSet,
    RemoveRoleView,
    RoleViewSet,
    UserPermissionsView,
    UserRoleViewSet,
)

router = DefaultRouter()
router.register("roles", RoleViewSet, basename="role")
router.register("console/users", ConsoleUsersViewSet, basename="console-users")
router.register("console/products", ConsoleProductsViewSet, basename="console-products")
router.register("permissions", PermissionViewSet, basename="permission")
router.register("user-roles", UserRoleViewSet, basename="user-role")


urlpatterns = [
    path("console/overview/", ConsoleOverviewView.as_view(), name="console-overview"),
    path("console/role-catalog/", ConsoleRolesView.as_view(), name="console-role-catalog"),
    path("console/roles/<int:pk>/permissions/", ConsoleRolePermissionView.as_view(), name="console-role-permissions"),
    path("", include(router.urls)),
    path("assign-role/", AssignRoleView.as_view(), name="assign_role"),
    path(
        "remove-role/<int:user_id>/<int:role_id>/",
        RemoveRoleView.as_view(),
        name="remove_role",
    ),
    path(
        "user-permissions/<int:user_id>/",
        UserPermissionsView.as_view(),
        name="user_permissions",
    ),
    path("my-permissions/", MyPermissionsView.as_view(), name="my_permissions"),
    path(
        "check-permission/",
        CheckPermissionView.as_view(),
        name="check_permission",
    ),
    path("admin-logs/", AdminLogListView.as_view(), name="admin_logs"),
    path(
        "admin-logs/<int:pk>/",
        AdminLogDetailView.as_view(),
        name="admin_log_detail",
    ),
    path("bulk-assign/", BulkAssignRolesView.as_view(), name="bulk_assign_roles"),
]