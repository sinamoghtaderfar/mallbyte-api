from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    RoleViewSet, PermissionViewSet, UserRoleViewSet,
    AssignRoleView, RemoveRoleView, UserPermissionsView,
    MyPermissionsView, CheckPermissionView
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
]