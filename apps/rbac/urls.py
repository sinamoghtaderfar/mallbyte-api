from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    AdminLogListView, RoleViewSet, PermissionViewSet, UserRoleViewSet,
    AssignRoleView, RemoveRoleView, UserPermissionsView,
    MyPermissionsView, CheckPermissionView, AdminLogDetailView
)

router = DefaultRouter()
router.register('roles', RoleViewSet)
router.register('permissions', PermissionViewSet)
router.register('user-roles', UserRoleViewSet)

urlpatterns = [
    path('', include(router.urls)),
    path('assign-role/', AssignRoleView.as_view(), name='assign_role'),
    path('remove-role/<int:user_id>/<int:role_id>/', RemoveRoleView.as_view(), name='remove_role'),
    path('user-permissions/<int:user_id>/', UserPermissionsView.as_view(), name='user_permissions'),
    path('my-permissions/', MyPermissionsView.as_view(), name='my_permissions'),
    path('check-permission/', CheckPermissionView.as_view(), name='check_permission'),
    
    # Admin logs
    path('admin-logs/', AdminLogListView.as_view(), name='admin_logs'),
    path('admin-logs/<int:pk>/', AdminLogDetailView.as_view(), name='admin_log_detail'),
]