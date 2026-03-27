from django.contrib.auth import get_user_model
from django.http import Http404
from django.contrib.auth.hashers import check_password
from django.utils import timezone
from rest_framework import generics, permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework import serializers
from .permissions import IsAdminOrVendorManager
from .models import Address, Profile, OTP, Seller
from .utils import generate_email_verification_token, verify_email_token
from .serializers import (
    AddressSerializer,
    ChangePasswordSerializer,
    PasswordResetRequestSerializer,
    PasswordResetVerifySerializer,
    ProfileSerializer,
    RegisterSerializer,
    UserSerializer,
    OTPRequestSerializer,
    OTPVerifySerializer,
    SellerApplicationSerializer, SellerSerializer, 
    SellerUpdateSerializer, AdminSellerActionSerializer,
    DeleteAccountSerializer,
    EmailVerifyRequestSerializer, EmailVerifyConfirmSerializer
)

from django.core.mail import send_mail
from django.conf import settings


User = get_user_model()


class RegisterView(generics.CreateAPIView):
    """Register a new user"""

    queryset = User.objects.all()
    permission_classes = (permissions.AllowAny,)
    serializer_class = RegisterSerializer

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()

        # Generate tokens
        refresh = RefreshToken.for_user(user)

        return Response(
            {
                "user": UserSerializer(user).data,
                "refresh": str(refresh),
                "access": str(refresh.access_token),
            },
            status=status.HTTP_201_CREATED,
        )


class ProfileView(generics.RetrieveUpdateAPIView):
    """show & edite profile"""

    serializer_class = ProfileSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        profile, created = Profile.objects.get_or_create(user=self.request.user)
        return profile


class AddressViewSet(viewsets.ModelViewSet):
    """ViewSet for managing user addresses"""

    serializer_class = AddressSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        """Return only addresses for the current user"""
        return Address.objects.filter(user=self.request.user)

    def perform_create(self, serializer):
        """Set the user automatically when creating an address"""
        serializer.save(user=self.request.user)

    @action(detail=True, methods=["patch"])
    def set_default(self, request, pk=None):
        """Set an address as default"""
        address = self.get_object()

        # Unset any existing default address for this user
        Address.objects.filter(user=request.user, is_default=True).update(
            is_default=False
        )

        # Set this address as default
        address.is_default = True
        address.save()

        return Response({"status": "default address set"}, status=status.HTTP_200_OK)


class OTPRequestView(generics.GenericAPIView):
    """Request OTP code"""
    permission_classes = [permissions.AllowAny]
    serializer_class = OTPRequestSerializer

    def post(self, request):
        
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        phone = serializer.validated_data['phone']
        print(f"Phone: {phone}")

        # Generate OTP
        otp = OTP.generate_otp(phone)
        print(f"OTP generated: {otp.code}")

        # TODO: Send SMS via Kavenegar or similar service
        # For now, just print to console

        return Response({
            'message': 'OTP sent successfully',
            'expires_in': 120
        }, status=status.HTTP_200_OK)


class OTPVerifyView(generics.GenericAPIView):
    """Verify OTP and login/register user"""
    permission_classes = [permissions.AllowAny]
    serializer_class = OTPVerifySerializer

    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        phone = serializer.validated_data['phone']
        code = serializer.validated_data['code']

        # Verify OTP
        success, message = OTP.verify_otp(phone, code)

        if not success:
            return Response({'error': message}, status=status.HTTP_400_BAD_REQUEST)

        # Get or create user
        user, created = User.objects.get_or_create(
            phone=phone,
            defaults={
                'email': f"{phone}@temp.com",  # Temporary email
                'full_name': f"User {phone[-4:]}",  # Temporary name
                'is_active': True
            }
        )

        # Generate tokens
        refresh = RefreshToken.for_user(user)

        return Response({
            'user': UserSerializer(user).data,
            'refresh': str(refresh),
            'access': str(refresh.access_token),
            'is_new': created
        }, status=status.HTTP_200_OK)
        
class SellerApplyView(generics.CreateAPIView):
    """Apply to become a seller"""
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = SellerApplicationSerializer
    #parser_classes = [MultiPartParser, FormParser]

    def perform_create(self, serializer):
        # Check if user already has a seller profile
        if hasattr(self.request.user, 'seller'):
            raise serializers.ValidationError(
                {"error": "You already have a seller profile"}
            )
        
        serializer.save(user=self.request.user)
        
class SellerStatusView(generics.RetrieveAPIView):
    """Check seller application status"""
    
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = SellerSerializer
    
    def get_object(self):
        try:
            return self.request.user.seller
        
        except Seller.DoesNotExist:
            
            raise Http404("No seller profile found")

            
            
class IsSellerPermission(permissions.BasePermission):
    """Permission check for verified sellers"""
    
    def has_permission(self, request, view):
        return(
            request.user.is_authenticated and 
            hasattr(request.user, 'seller') and 
            request.user.seller.is_verified
        )
        
class SellerDashboardView(generics.RetrieveAPIView):
    """Seller dashboard with stats"""
    permission_classes = [IsSellerPermission]
    serializer_class = SellerSerializer

    def get_object(self):
        return self.request.user.seller


class SellerStoreView(generics.RetrieveUpdateAPIView):
    """View and update store information"""
    permission_classes = [IsSellerPermission]
    serializer_class = SellerUpdateSerializer
    parser_classes = [MultiPartParser, FormParser]

    def get_object(self):
        return self.request.user.seller


class AdminSellersListView(generics.ListAPIView):
    """Admin: List all sellers with filters"""
    permission_classes = [permissions.IsAdminUser]
    serializer_class = SellerSerializer

    def get_queryset(self):
        queryset = Seller.objects.all()
        
        # Filter by status
        status = self.request.query_params.get('status')
        if status:
            queryset = queryset.filter(status=status)
        
        # Search by store name
        search = self.request.query_params.get('search')
        if search:
            queryset = queryset.filter(store_name__icontains=search)
        
        return queryset.order_by('-applied_at')


class AdminSellerDetailView(generics.RetrieveAPIView):
    """Admin: View seller details"""
    permission_classes = [permissions.IsAdminUser]
    queryset = Seller.objects.all()
    serializer_class = SellerSerializer


class AdminSellerVerifyView(generics.GenericAPIView):
    """Admin: Verify seller"""
    permission_classes = [permissions.IsAdminUser]
    serializer_class = AdminSellerActionSerializer

    def post(self, request, pk):
        try:
            seller = Seller.objects.get(pk=pk)
        except Seller.DoesNotExist:
            return Response(
                {"error": "Seller not found"},
                status=status.HTTP_404_NOT_FOUND
            )
        
        seller.approve(request.user)
        return Response(
            {"message": f"Seller {seller.store_name} approved successfully"},
            status=status.HTTP_200_OK
        )


class AdminSellerRejectView(generics.GenericAPIView):
    """Admin: Reject seller"""
    permission_classes = [permissions.IsAdminUser]
    serializer_class = AdminSellerActionSerializer

    def post(self, request, pk):
        print(f"\nREJECT VIEW CALLED for seller {pk}")

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        try:
            seller = Seller.objects.get(pk=pk)
        except Seller.DoesNotExist:
            return Response(
                {"error": "Seller not found"},
                status=status.HTTP_404_NOT_FOUND
            )
        
        reason = serializer.validated_data.get('reason', '')
        seller.reject(request.user, reason)
        print(f"   Status after reject: {seller.status}")
        return Response(
            {"message": f"Seller {seller.store_name} rejected"},
            status=status.HTTP_200_OK
        )
        
class AdminVerifySellerView(generics.GenericAPIView):
    """
    Admin view to verify or reject seller applications.
    """
    permission_classes = [permissions.IsAuthenticated, IsAdminOrVendorManager]
    serializer_class = AdminSellerActionSerializer
    
    def post(self, request, seller_id):
        try:
            seller = Seller.objects.get(id=seller_id, status = "pending")
        except Seller.DoesNotExist:
            return Response(
                {"error": "Pending seller not found"},
                status=status.HTTP_404_NOT_FOUND
            )
        action = request.data.get("action")
        reason = request.data.get("reason", "")
        
        if action == 'approve':
            seller.approve(request.user)
            return Response({
                "message": f"Seller {seller.store_name} approved successfully",
                "seller": SellerSerializer(seller).data
            }, status=status.HTTP_200_OK)

        elif action == 'reject':
            seller.reject(request.user, reason)
            return Response({
                "message": f"Seller {seller.store_name} rejected",
                "seller": SellerSerializer(seller).data
            }, status=status.HTTP_200_OK)

        else:
            return Response(
                {"error": "Action must be 'approve' or 'reject'"},
                status=status.HTTP_400_BAD_REQUEST
            )

class AdminPendingSellersView(generics.ListAPIView):
    """
    Admin view to list all pending seller applications.
    """
    permission_classes = [permissions.IsAuthenticated, IsAdminOrVendorManager]
    serializer_class = SellerSerializer

    def get_queryset(self):
        return Seller.objects.filter(status='pending').order_by('-applied_at')
    
class PasswordResetRequestView(generics.CreateAPIView):
    """Request password reset via OTP"""
    permission_classes = [permissions.AllowAny]
    serializer_class = PasswordResetRequestSerializer
    
    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception = True)
        
        phone = serializer.validated_data['phone']
        
        # Check if user exists
        try:
            user = User.objects.get(phone=phone)
        except User.DoesNotExist:
            return Response(
                {"error": "No user found with this phone number"},
                status=status.HTTP_404_NOT_FOUND
            )
        # Generate OTP
        otp = OTP.generate_otp(phone)
        print(f"\n📱 Password reset OTP for {phone}: {otp.code}\n")
        
        return Response({
            'message': 'OTP sent successfully',
            'expires_in': 120
        }, status=status.HTTP_200_OK)
        
class PasswordResetVerifyView(generics.GenericAPIView):
    """Verify OTP and reset password"""
    
    permission_classes = [permissions.AllowAny]
    serializer_class = PasswordResetVerifySerializer
    
    def post(self, request):
        serializer = self. get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        phone = serializer.validated_data['phone']
        code = serializer.validated_data['code']
        new_password = serializer.validated_data['new_password']
        
        # Verify OTP
        success, message = OTP.verify_otp(phone, code)
        
        if not success:
            return Response({'error': message}, status=status.HTTP_400_BAD_REQUEST)
        
        # Get user and set new password
        try:
            user = User.objects.get(phone=phone)
        except User.DoesNotExist:
            return Response(
                {"error": "User not found"},
                status=status.HTTP_404_NOT_FOUND
            )
        user.set_password(new_password)
        user.save()
        
        return Response({
            'message': 'Password reset successful'
        }, status=status.HTTP_200_OK)
        
class ChangePasswordView(generics.GenericAPIView):
    """Change password for authenticated user"""
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = ChangePasswordSerializer
    
    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        user = request.user
        old_password = serializer.validated_data['old_password']
        new_password = serializer.validated_data['new_password']
        
         # Check old password
        if not user.check_password(old_password):
            return Response(
                {"old_password": "Wrong password"},
                status=status.HTTP_400_BAD_REQUEST
            )
        # Set new password
        user.set_password(new_password)
        user.save()
        
        return Response({
            'message': 'Password changed successfully'
        }, status=status.HTTP_200_OK)
        

class AdminSellerVerifyView(generics.GenericAPIView):
    """Admin: Verify seller"""
    permission_classes = [permissions.IsAdminUser]
    serializer_class = AdminSellerActionSerializer
    
    def post(self, request, pk):
        """Verify a seller account"""
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            seller = Seller.Objects.get(pk=pk)
            seller.is_verified = True
        except Seller.DoesNotExist:
            return Response({"detail": "Seller not found"}, status=status.HTTP_404_NOT_FOUND)
        action = serializer.validated_data('action')
        
        if action == 'approve':
            seller.approve(request.user)
            
            from apps.rbac.utils import log_admin_action
            log_admin_action(
                admin = request.user,
                action_type = 'approve_seller',
                target_user = seller.user,
                details = {
                    'seller_id': seller.id,
                    'seller_name': seller.name,
                },
                request = request
            )
            return Response(
                {"message": f"Seller {seller.store_name} approved successfully"},
                status=status.HTTP_200_OK
            )
        elif action == 'reject':
            reason = serializer.validated_data.get('reason', '')
            seller.reject(request.user, reason)
            
            from apps.rbac.utils import log_admin_action
            log_admin_action(
                admin = request.user,
                action = 'reject_seller',
                target_user = seller.user,
                details = {
                    'seller_id': seller.id,
                    'store_name': seller.store_name,
                    'reason': reason,
                },
                request = request
            )
            return Response(
                {"message": f"Seller {seller.store_name} rejected"},
                status=status.HTTP_200_OK
            )
        else:
            return Response({"error": "Action must be 'approve' or 'reject'"},
                status=status.HTTP_400_BAD_REQUEST
                )
        
class DeleteAccountView(generics.GenericAPIView):
    """Delete user account"""
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = DeleteAccountSerializer
    
    def delete(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        user = request.user
        
        # Soft delete
        user.is_deleted = True
        user.deleted_at = timezone.now()
        user.is_active = False
        user.save()
        
        return Response({
            'message': 'Your account has been deleted successfully'
        }, status=status.HTTP_200_OK)

class AdminDeleteUserView(generics.GenericAPIView):
    """Admin: Delete a user account"""
    permission_classes = [permissions.IsAdminUser]
    
    def delete(self, request, user_id):
        try:
            user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            return Response(
                {"error": "User not found"},
                status=status.HTTP_404_NOT_FOUND
            )
        
        
        if user.id == request.user.id:
            return Response(
                {"error": "You cannot delete your own account"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        
        if user.is_superuser:
            return Response(
                {"error": "Cannot delete super admin accounts"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Soft delete
        user.is_deleted = True
        user.is_active = False
        user.deleted_at = timezone.now()
        user.save()
        
        
        from apps.rbac.utils import log_admin_action
        log_admin_action(
            admin=request.user,
            action='delete_user',
            target_user=user,
            details={
                'user_phone': user.phone,
                'deleted_by': request.user.phone
            },
            request=request
        )
        
        return Response({
            'message': f'User {user.phone} deleted successfully'
        }, status=status.HTTP_200_OK)
        
class EmailVerifyRequestView(generics.GenericAPIView):
    """Request email verification (send email with token)"""
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = EmailVerifyRequestSerializer

    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        user = request.user
        new_email = serializer.validated_data['email']
        
        # if email already verified
        if user.email_verified:
            return Response(
                {"error": "Your email is already verified"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # save new email
        user.email = new_email
        user.save()
        
        # generate token
        token = generate_email_verification_token(user)
        
        # make verification link
        verification_link = f"{settings.FRONTEND_URL}/verify-email?token={token}"
        
        # send email
        try:
            send_mail(
                subject='Verify Your Email - MallByte',
                message=f"""
                    Hello {user.full_name or user.phone},

                    Please click the link below to verify your email address:

                    {verification_link}

                    This link will expire in 1 hour.

                    If you didn't request this, please ignore this email.

                    Best regards,
                    MallByte Team
                    """,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[new_email],
                fail_silently=False,
            )
            print(f"📧 Email sent to {new_email}")
            
        except Exception as e:
            print(f"❌ Failed to send email: {e}")
            # Fallback: print the verification link to console
            print(f"\n📧 Email verification link for {new_email}:")
            print(f"   {verification_link}\n")
        
        return Response({
            'message': 'Verification email sent',
            'email': new_email
        }, status=status.HTTP_200_OK)
        
class EmailVerifyConfirmView(generics.GenericAPIView):
    """Confirm email verification"""
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = EmailVerifyConfirmSerializer

    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        user = request.user
        token = serializer.validated_data['token']
        
        # if email already verified
        if user.email_verified:
            return Response(
                {"error": "Email already verified"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # check token
        if not verify_email_token(user, token):
            return Response(
                {"error": "Invalid or expired token"},
                status=status.HTTP_400_BAD_REQUEST
            )
        print(f"Verifying email for user {user.id}: {user.email}")
        # verfy email
        user.email_verified = True
        user.email_verified_at = timezone.now()
        user.save()
        print(f"After save: email_verified={user.email_verified}")
        return Response({
            'message': 'Email verified successfully'
        }, status=status.HTTP_200_OK)