from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import send_mail
from django.http import Http404
from django.utils import timezone

from rest_framework import generics, permissions, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response

from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView

from .throttles import (
    AuthIPRateThrottle,
    OTPEmailRateThrottle,
    OTPIPRateThrottle,
    PasswordResetEmailRateThrottle,
    PasswordResetIPRateThrottle,
)
from .models import Address, OTP, Profile, Seller
from .otp_delivery import OTPDeliveryError, mask_email, send_otp_email
from .serializers import (
    AddressSerializer,
    AdminSellerActionSerializer,
    ChangePasswordSerializer,
    DeleteAccountSerializer,
    EmailVerifyConfirmSerializer,
    EmailVerifyRequestSerializer,
    OTPRequestSerializer,
    OTPVerifySerializer,
    PasswordResetRequestSerializer,
    PasswordResetVerifySerializer,
    ProfileSerializer,
    RegisterSerializer,
    SellerApplicationSerializer,
    SellerSerializer,
    SellerUpdateSerializer,
    UserSerializer,
)
from .utils import generate_email_verification_token, verify_email_token


User = get_user_model()


class RegisterView(generics.CreateAPIView):
    """Register a new user"""

    queryset = User.objects.all()
    permission_classes = [permissions.AllowAny]
    serializer_class = RegisterSerializer

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = serializer.save()

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
    """Show and edit the authenticated user's profile"""

    serializer_class = ProfileSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        profile, _created = Profile.objects.get_or_create(user=self.request.user)
        return profile


class AddressViewSet(viewsets.ModelViewSet):
    """ViewSet for managing user addresses"""

    serializer_class = AddressSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return Address.objects.filter(user=self.request.user)

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)

    @action(detail=True, methods=["patch"])
    def set_default(self, request, pk=None):
        address = self.get_object()

        Address.objects.filter(
            user=request.user,
            is_default=True,
        ).update(
            is_default=False,
        )

        address.is_default = True
        address.save(update_fields=["is_default"])

        return Response(
            {
                "status": "default address set"
            },
            status=status.HTTP_200_OK,
        )


class OTPRequestView(generics.GenericAPIView):
    """Request email OTP code"""

    permission_classes = [permissions.AllowAny]
    serializer_class = OTPRequestSerializer
    throttle_classes = [OTPIPRateThrottle, OTPEmailRateThrottle]

    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        email = serializer.validated_data["email"]

        otp = OTP.generate_otp(email=email)

        try:
            send_otp_email(
                to_email=email,
                code=otp.code,
                expires_in_seconds=settings.OTP_CODE_EXPIRY_SECONDS,
            )

        except OTPDeliveryError as exc:
            otp.is_used = True
            otp.save(update_fields=["is_used"])

            return Response(
                {
                    "error": "OTP email could not be sent.",
                    "detail": str(exc),
                },
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        return Response(
            {
                "message": "OTP sent successfully",
                "delivery_channel": "email",
                "email": mask_email(email),
                "expires_in": settings.OTP_CODE_EXPIRY_SECONDS,
            },
            status=status.HTTP_200_OK,
        )


class OTPVerifyView(generics.GenericAPIView):
    """Verify email OTP and login/register user"""

    permission_classes = [permissions.AllowAny]
    serializer_class = OTPVerifySerializer
    throttle_classes = [OTPIPRateThrottle, OTPEmailRateThrottle]

    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        email = serializer.validated_data["email"]
        code = serializer.validated_data["code"]

        success, message, _otp = OTP.verify_otp_and_get_instance(
            email=email,
            code=code,
        )

        if not success:
            return Response(
                {
                    "error": message
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        user = User.objects.filter(email=email).first()
        created = False

        if user is None:
            user = User.objects.create_user(
                email=email,
                full_name=f"User {email.split('@')[0]}",
                password=None,
                is_active=True,
                email_verified=True,
                email_verified_at=timezone.now(),
            )
            created = True

        update_fields = []

        if not user.email_verified:
            user.email_verified = True
            user.email_verified_at = timezone.now()
            update_fields.extend(
                [
                    "email_verified",
                    "email_verified_at",
                ]
            )

        if update_fields:
            user.save(update_fields=update_fields)

        refresh = RefreshToken.for_user(user)

        return Response(
            {
                "user": UserSerializer(user).data,
                "refresh": str(refresh),
                "access": str(refresh.access_token),
                "is_new": created,
            },
            status=status.HTTP_200_OK,
        )


class SellerApplyView(generics.CreateAPIView):
    """Apply to become a seller"""

    permission_classes = [permissions.IsAuthenticated]
    serializer_class = SellerApplicationSerializer

    def perform_create(self, serializer):
        if hasattr(self.request.user, "seller"):
            raise serializers.ValidationError(
                {
                    "error": "You already have a seller profile"
                }
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
        return (
            request.user.is_authenticated
            and hasattr(request.user, "seller")
            and request.user.seller.is_verified
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
    """Admin: list all sellers with optional filters"""

    permission_classes = [permissions.IsAdminUser]
    serializer_class = SellerSerializer

    def get_queryset(self):
        queryset = Seller.objects.select_related(
            "user",
            "verified_by",
        ).all()

        status_filter = self.request.query_params.get("status")
        if status_filter:
            queryset = queryset.filter(status=status_filter)

        search = self.request.query_params.get("search")
        if search:
            queryset = queryset.filter(store_name__icontains=search)

        return queryset.order_by("-applied_at")


class AdminSellerDetailView(generics.RetrieveAPIView):
    """Admin: view seller details"""

    permission_classes = [permissions.IsAdminUser]
    serializer_class = SellerSerializer

    def get_queryset(self):
        return Seller.objects.select_related(
            "user",
            "verified_by",
        ).all()


class AdminPendingSellersView(generics.ListAPIView):
    """Admin: list pending seller applications"""

    permission_classes = [permissions.IsAdminUser]
    serializer_class = SellerSerializer

    def get_queryset(self):
        return Seller.objects.select_related(
            "user",
            "verified_by",
        ).filter(
            status=Seller.StatusChoices.PENDING,
        ).order_by("-applied_at")


class AdminSellerVerifyView(generics.GenericAPIView):
    """Admin: approve a pending seller application"""

    permission_classes = [permissions.IsAdminUser]
    serializer_class = SellerSerializer

    def post(self, request, pk):
        try:
            seller = Seller.objects.select_related("user").get(pk=pk)

        except Seller.DoesNotExist:
            return Response(
                {
                    "error": "Seller not found"
                },
                status=status.HTTP_404_NOT_FOUND,
            )

        if seller.status != Seller.StatusChoices.PENDING:
            return Response(
                {
                    "error": "Only pending seller applications can be approved"
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        seller.approve(request.user)
        seller.refresh_from_db()

        return Response(
            {
                "message": f"Seller {seller.store_name} approved successfully",
                "seller": SellerSerializer(
                    seller,
                    context={
                        "request": request
                    },
                ).data,
            },
            status=status.HTTP_200_OK,
        )


class AdminSellerRejectView(generics.GenericAPIView):
    """Admin: reject a pending seller application"""

    permission_classes = [permissions.IsAdminUser]
    serializer_class = SellerSerializer

    def post(self, request, pk):
        try:
            seller = Seller.objects.select_related("user").get(pk=pk)

        except Seller.DoesNotExist:
            return Response(
                {
                    "error": "Seller not found"
                },
                status=status.HTTP_404_NOT_FOUND,
            )

        if seller.status != Seller.StatusChoices.PENDING:
            return Response(
                {
                    "error": "Only pending seller applications can be rejected"
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        reason = request.data.get("reason", "")

        seller.reject(
            admin_user=request.user,
            reason=reason,
        )
        seller.refresh_from_db()

        return Response(
            {
                "message": f"Seller {seller.store_name} rejected",
                "seller": SellerSerializer(
                    seller,
                    context={
                        "request": request
                    },
                ).data,
            },
            status=status.HTTP_200_OK,
        )


class PasswordResetRequestView(generics.CreateAPIView):
    """Request password reset via email OTP"""

    permission_classes = [permissions.AllowAny]
    serializer_class = PasswordResetRequestSerializer
    throttle_classes = [PasswordResetIPRateThrottle, PasswordResetEmailRateThrottle]

    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        email = serializer.validated_data["email"]

        otp = OTP.generate_otp(email=email)

        try:
            send_otp_email(
                to_email=email,
                code=otp.code,
                expires_in_seconds=settings.OTP_CODE_EXPIRY_SECONDS,
            )

        except OTPDeliveryError as exc:
            otp.is_used = True
            otp.save(update_fields=["is_used"])

            return Response(
                {
                    "error": "Password reset email could not be sent.",
                    "detail": str(exc),
                },
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        return Response(
            {
                "message": "Password reset OTP sent successfully",
                "delivery_channel": "email",
                "email": mask_email(email),
                "expires_in": settings.OTP_CODE_EXPIRY_SECONDS,
            },
            status=status.HTTP_200_OK,
        )


class PasswordResetVerifyView(generics.GenericAPIView):
    """Verify email OTP and reset password"""

    permission_classes = [permissions.AllowAny]
    serializer_class = PasswordResetVerifySerializer
    throttle_classes = [PasswordResetIPRateThrottle, PasswordResetEmailRateThrottle]

    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        email = serializer.validated_data["email"]
        code = serializer.validated_data["code"]
        new_password = serializer.validated_data["new_password"]

        success, message, _otp = OTP.verify_otp_and_get_instance(
            email=email,
            code=code,
        )

        if not success:
            return Response(
                {
                    "error": message
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            user = User.objects.get(email=email)

        except User.DoesNotExist:
            return Response(
                {
                    "error": "User not found"
                },
                status=status.HTTP_404_NOT_FOUND,
            )

        user.set_password(new_password)
        user.save(update_fields=["password"])

        return Response(
            {
                "message": "Password reset successful"
            },
            status=status.HTTP_200_OK,
        )


class ChangePasswordView(generics.GenericAPIView):
    """Change password for authenticated user"""

    permission_classes = [permissions.IsAuthenticated]
    serializer_class = ChangePasswordSerializer

    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = request.user
        old_password = serializer.validated_data["old_password"]
        new_password = serializer.validated_data["new_password"]

        if not user.check_password(old_password):
            return Response(
                {
                    "old_password": "Wrong password"
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        user.set_password(new_password)
        user.save(update_fields=["password"])

        return Response(
            {
                "message": "Password changed successfully"
            },
            status=status.HTTP_200_OK,
        )


class DeleteAccountView(generics.GenericAPIView):
    """Delete authenticated user account"""

    permission_classes = [permissions.IsAuthenticated]
    serializer_class = DeleteAccountSerializer

    def delete(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = request.user

        user.is_deleted = True
        user.deleted_at = timezone.now()
        user.is_active = False
        user.save(
            update_fields=[
                "is_deleted",
                "deleted_at",
                "is_active",
            ]
        )

        return Response(
            {
                "message": "Your account has been deleted successfully"
            },
            status=status.HTTP_200_OK,
        )


class AdminDeleteUserView(generics.GenericAPIView):
    """Admin: delete a user account"""

    permission_classes = [permissions.IsAdminUser]

    def delete(self, request, user_id):
        try:
            user = User.objects.get(id=user_id)

        except User.DoesNotExist:
            return Response(
                {
                    "error": "User not found"
                },
                status=status.HTTP_404_NOT_FOUND,
            )

        if user.id == request.user.id:
            return Response(
                {
                    "error": "You cannot delete your own account"
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        if user.is_superuser:
            return Response(
                {
                    "error": "Cannot delete super admin accounts"
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        user.is_deleted = True
        user.is_active = False
        user.deleted_at = timezone.now()
        user.save(
            update_fields=[
                "is_deleted",
                "is_active",
                "deleted_at",
            ]
        )

        from apps.rbac.utils import log_admin_action

        log_admin_action(
            admin=request.user,
            action="delete_user",
            target_user=user,
            details={
                "user_email": user.email,
                "deleted_by": request.user.email,
            },
            request=request,
        )

        return Response(
            {
                "message": f"User {user.email} deleted successfully"
            },
            status=status.HTTP_200_OK,
        )


class EmailVerifyRequestView(generics.GenericAPIView):
    """Request email verification"""

    permission_classes = [permissions.IsAuthenticated]
    serializer_class = EmailVerifyRequestSerializer

    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = request.user
        new_email = serializer.validated_data["email"]

        if user.email_verified:
            return Response(
                {
                    "error": "Your email is already verified"
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        user.email = new_email
        user.save(update_fields=["email"])

        token = generate_email_verification_token(user)

        frontend_url = getattr(settings, "FRONTEND_URL", "http://localhost:3000")
        verification_link = f"{frontend_url}/verify-email?token={token}"

        try:
            send_mail(
                subject="Verify Your Email - MallByte",
                message=(
                    f"Hello {user.full_name or user.email},\n\n"
                    "Please click the link below to verify your email address:\n\n"
                    f"{verification_link}\n\n"
                    "This link will expire in 1 hour.\n\n"
                    "If you did not request this, please ignore this email.\n\n"
                    "Best regards,\n"
                    "MallByte Team"
                ),
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[new_email],
                fail_silently=False,
            )

        except Exception as exc:
            return Response(
                {
                    "error": "Verification email could not be sent.",
                    "detail": str(exc),
                },
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        return Response(
            {
                "message": "Verification email sent",
                "email": new_email,
            },
            status=status.HTTP_200_OK,
        )


class EmailVerifyConfirmView(generics.GenericAPIView):
    """Confirm email verification"""

    permission_classes = [permissions.IsAuthenticated]
    serializer_class = EmailVerifyConfirmSerializer

    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = request.user
        token = serializer.validated_data["token"]

        if user.email_verified:
            return Response(
                {
                    "error": "Email already verified"
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not verify_email_token(user, token):
            return Response(
                {
                    "error": "Invalid or expired token"
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        user.email_verified = True
        user.email_verified_at = timezone.now()
        user.save(
            update_fields=[
                "email_verified",
                "email_verified_at",
            ]
        )

        return Response(
            {
                "message": "Email verified successfully"
            },
            status=status.HTTP_200_OK,
        )
        
class ThrottledTokenObtainPairView(TokenObtainPairView):
    throttle_classes = [AuthIPRateThrottle]