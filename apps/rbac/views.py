from rest_framework import generics, viewsets, status, permissions
from rest_framework.response import Response
from rest_framework.decorators import action
from django.contrib.auth import get_user_model
from .models import Role, Permission, RolePermission, UserRole, AdminLog
from .serializers import (
    RoleSerializer, PermissionSerializer, RolePermissionSerializer,
    UserRoleSerializer, AssignRoleSerializer, CheckPermissionSerializer,
    AdminLogSerializer
)
from .utils import get_user_permissions, assign_role, remove_role, has_permission
from .permissions import IsSuperAdmin

User = get_user_model()


class RoleViewSet(viewsets.ModelViewSet):
    """ViewSet for managing roles"""
    queryset = Role.objects.all()
    serializer_class = RoleSerializer
    permission_classes = [IsSuperAdmin]

    def get_queryset(self):
        queryset = super().get_queryset()
        name = self.request.query_params.get('name')
        if name:
            queryset = queryset.filter(name__icontains=name)
        return queryset

    @action(detail=True, methods=['get'])
    def permissions(self, request, pk=None):
        """Get all permissions for a role"""
        role = self.get_object()
        permissions = role.role_permissions.select_related('permission').all()
        serializer = RolePermissionSerializer(permissions, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['post'])
    def add_permission(self, request, pk=None):
        """Add a permission to a role"""
        role = self.get_object()
        permission_id = request.data.get('permission_id')
        
        try:
            permission = Permission.objects.get(id=permission_id)
        except Permission.DoesNotExist:
            return Response({'error': 'Permission not found'}, status=404)
        
        role_permission, created = RolePermission.objects.get_or_create(
            role=role, permission=permission
        )
        
        if created:
            return Response({'message': 'Permission added'}, status=201)
        return Response({'message': 'Permission already exists'}, status=200)

    @action(detail=True, methods=['delete'])
    def remove_permission(self, request, pk=None):
        """Remove a permission from a role"""
        role = self.get_object()
        permission_id = request.data.get('permission_id')
        
        try:
            permission = Permission.objects.get(id=permission_id)
        except Permission.DoesNotExist:
            return Response({'error': 'Permission not found'}, status=404)
        
        RolePermission.objects.filter(role=role, permission=permission).delete()
        return Response({'message': 'Permission removed'}, status=200)


class PermissionViewSet(viewsets.ModelViewSet):
    """ViewSet for managing permissions"""
    queryset = Permission.objects.all()
    serializer_class = PermissionSerializer
    permission_classes = [IsSuperAdmin]

    def get_queryset(self):
        queryset = super().get_queryset()
        module = self.request.query_params.get('module')
        if module:
            queryset = queryset.filter(module=module)
        return queryset


class UserRoleViewSet(viewsets.ModelViewSet):
    """ViewSet for managing user roles"""
    queryset = UserRole.objects.all()
    serializer_class = UserRoleSerializer
    permission_classes = [IsSuperAdmin]

    def get_queryset(self):
        queryset = super().get_queryset()
        user_id = self.request.query_params.get('user_id')
        if user_id:
            queryset = queryset.filter(user_id=user_id)
        return queryset


class AssignRoleView(generics.GenericAPIView):
    """Assign role to user"""
    permission_classes = [IsSuperAdmin]
    serializer_class = AssignRoleSerializer

    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        user = User.objects.get(id=serializer.validated_data['user_id'])
        role = Role.objects.get(id=serializer.validated_data['role_id'])
        expires_at = serializer.validated_data.get('expires_at')
        
        user_role = assign_role(user, role, request.user, expires_at)
        response_serializer = UserRoleSerializer(user_role)
        
        from .utils import log_admin_action
        log_admin_action(
            admin=request.user,
            action='assign_role',
            target_user=user,
            target_role=role,
            details={
                'role_name': role.name,
                'expires_at': str(expires_at) if expires_at else None,
                'user_role_id': user_role.id
            },
            request=request
        )
        
        return Response(response_serializer.data, status=status.HTTP_201_CREATED)


class RemoveRoleView(generics.GenericAPIView):
    """Remove role from user"""
    permission_classes = [IsSuperAdmin]
    
    def delete(self, request, user_id, role_id):
        try:
            user = User.objects.get(id=user_id)
            role = Role.objects.get(id=role_id)
        except (User.DoesNotExist, Role.DoesNotExist):
            return Response({'error': 'User or role not found'}, status=404)
        
        from .utils import log_admin_action
        log_admin_action(
            admin=request.user,
            action='remove_role',
            target_user=user,
            target_role=role,
            details={'role_name': role.name},
            request=request
        )
        
        remove_role(user, role)
        return Response({'message': 'Role removed successfully'}, status=200)


class UserPermissionsView(generics.GenericAPIView):
    """Get permissions for a user"""
    permission_classes = [IsSuperAdmin]
    
    def get(self, request, user_id):
        try:
            user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            return Response({'error': 'User not found'}, status=404)
        
        permissions = get_user_permissions(user)
        return Response({'permissions': permissions})


class MyPermissionsView(generics.GenericAPIView):
    """Get current user's permissions"""
    permission_classes = [permissions.IsAuthenticated]
    
    def get(self, request):
        permissions = get_user_permissions(request.user)
        return Response({
            'user_id': request.user.id,
            'phone': request.user.phone,
            'permissions': permissions,
            'permissions_count': len(permissions)
        })


class CheckPermissionView(generics.GenericAPIView):
    """Check if user has a specific permission"""
    permission_classes = [IsSuperAdmin]
    serializer_class = CheckPermissionSerializer
    
    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        try:
            user = User.objects.get(id=serializer.validated_data['user_id'])
        except User.DoesNotExist:
            return Response({'error': 'User not found'}, status=404)
        
        permission_codename = serializer.validated_data['permission']
        has_perm = has_permission(user, permission_codename)
        
        return Response({
            'user_id': user.id,
            'permission': permission_codename,
            'has_permission': has_perm
        })
        
class AdminLogListView(generics.ListAPIView):
    """View for admin to see all action logs"""
    permission_classes = [IsSuperAdmin]
    serializer_class = AdminLogSerializer
    queryset = AdminLog.objects.all()
    
    def get_queryset(self):
        queryset = super().get_queryset()
        
        #filtering based admin
        admin_id = self.request.query_params.get('admin_id')
        if admin_id:
            queryset = queryset.filter(admin_id=admin_id)
        
        #filtering based target user
        target_user = self.request.query_params.get('target_user')
        if target_user:
            queryset = queryset.filter(target_user_id=target_user)
        
        #filtering based action type
        action_type = self.request.query_params.get('action_type')
        if action_type:
            queryset = queryset.filter(action_type=action_type)
            
        return queryset

class AdminLogDetailView(generics.RetrieveAPIView):
    """View for admin to see a specific log entry"""
    permission_classes = [IsSuperAdmin]
    serializer_class = AdminLogSerializer
    queryset = AdminLog.objects.all()