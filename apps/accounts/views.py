from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import make_password
from django.core.mail import send_mail
from django.db import IntegrityError, transaction
from django.http import Http404
from django.utils import timezone
from rest_framework import generics, permissions, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import AccessToken, RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView

from apps.accounts.cookies import (
    clear_refresh_cookie,
    get_refresh_cookie_name,
    set_refresh_cookie,
)

from .auth_tokens import identity_token_valid, issue_user_tokens
from .mfa import is_privileged, privileged_token_valid
from .mfa_models import AdminMFAChallenge
from .models import OTP, Address, Profile, Seller
from .otp_delivery import OTPDeliveryError, mask_email, send_otp_email
from .serializers import (
    AddressSerializer,
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
    VerifiedTokenObtainPairSerializer,
)
from .throttles import (
    AuthIPRateThrottle,
    OTPEmailRateThrottle,
    OTPIPRateThrottle,
    PasswordResetEmailRateThrottle,
    PasswordResetIPRateThrottle,
)
from .utils import clear_email_verification_token, generate_email_verification_token, pending_email_for_token

User = get_user_model()


class RegisterView(generics.CreateAPIView):
    """Register a new user."""

    queryset = User.objects.all()
    permission_classes = [permissions.AllowAny]
    serializer_class = RegisterSerializer

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = serializer.save()
        return Response(
            {
                "user": UserSerializer(user).data,
                "verification_required": True,
                "message": "Verify your email with OTP to activate this account. Set a password after verification if needed.",
            },
            status=status.HTTP_201_CREATED,
        )


class ProfileView(generics.RetrieveUpdateAPIView):
    """Show and edit the authenticated user's profile."""

    serializer_class = ProfileSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        profile, _created = Profile.objects.get_or_create(user=self.request.user)
        return profile


class AddressViewSet(viewsets.ModelViewSet):
    """ViewSet for managing user addresses."""

    serializer_class = AddressSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return Address.objects.filter(user=self.request.user)

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)

    @action(detail=True, methods=["patch"])
    def set_default(self, request, pk=None):
        address = self.get_object()

        address.is_default = True
        address.save(update_fields=["is_default"])

        return Response(
            {
                "status": "default address set",
            },
            status=status.HTTP_200_OK,
        )


class OTPRequestView(generics.GenericAPIView):
    """Request email OTP code."""

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

        except OTPDeliveryError:
            otp.is_used = True
            otp.save(update_fields=["is_used"])

            return Response(
                {
                    "error": "OTP email could not be sent.",
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
    """Verify email OTP and login/register user."""

    permission_classes = [permissions.AllowAny]
    serializer_class = OTPVerifySerializer
    throttle_classes = [OTPIPRateThrottle, OTPEmailRateThrottle]

    @transaction.atomic
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
                    "error": message,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # The public manager hides soft-deleted users. Looking up all records
        # prevents an OTP from recreating an existing deleted account and
        # ensures suspended accounts never receive fresh JWTs.
        user, created = User.objects.all_with_deleted().select_for_update().get_or_create(
            email=email,
            defaults={
                "full_name": f"User {email.split('@')[0]}",
                "password": make_password(None),
                "is_active": True,
                "email_verified": True,
                "email_verified_at": timezone.now(),
            },
        )
        if user is not None and (not user.is_active or user.is_deleted):
            return Response(
                {"error": "Account unavailable. Please contact support."},
                status=status.HTTP_403_FORBIDDEN,
            )
        update_fields = []

        if not user.email_verified:
            # Email ownership does not prove who selected a provisional password.
            # Never retain credentials/sessions supplied before that proof.
            if not is_privileged(user):
                user.set_unusable_password()
                user.auth_version += 1
                update_fields.extend(["password", "auth_version"])
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

        if is_privileged(user):
            # Email verification is first factor only; never issue privileged JWTs here.
            token = AdminMFAChallenge.issue(user)
            enrolled = getattr(user, "admin_mfa", None)
            return Response({
                "mfa_required": True,
                "challenge": token,
                "mfa_enrolled": bool(enrolled and enrolled.enabled),
            })

        refresh = issue_user_tokens(user)

        response = Response(
            {
                "user": UserSerializer(user).data,
                "access": str(refresh.access_token),
                "is_new": created,
            },
            status=status.HTTP_200_OK,
        )
        set_refresh_cookie(response, str(refresh))
        return response


class SellerApplyView(generics.CreateAPIView):
    """Apply to become a seller."""

    permission_classes = [permissions.IsAuthenticated]
    serializer_class = SellerApplicationSerializer

    def perform_create(self, serializer):
        if hasattr(self.request.user, "seller"):
            raise serializers.ValidationError(
                {
                    "error": "You already have a seller profile",
                }
            )

        serializer.save(user=self.request.user)


class SellerStatusView(generics.RetrieveAPIView):
    """Check seller application status."""

    permission_classes = [permissions.IsAuthenticated]
    serializer_class = SellerSerializer

    def get_object(self):
        try:
            return self.request.user.seller

        except Seller.DoesNotExist as exc:
            raise Http404("No seller profile found") from exc


class IsSellerPermission(permissions.BasePermission):
    """Permission check for verified sellers."""

    def has_permission(self, request, view):
        return (
            request.user.is_authenticated
            and hasattr(request.user, "seller")
            and request.user.seller.is_verified
        )


class SellerDashboardView(generics.RetrieveAPIView):
    """Seller dashboard with stats."""

    permission_classes = [IsSellerPermission]
    serializer_class = SellerSerializer

    def get_object(self):
        return self.request.user.seller


class SellerStoreView(generics.RetrieveUpdateAPIView):
    """View and update store information."""

    permission_classes = [IsSellerPermission]
    serializer_class = SellerUpdateSerializer
    parser_classes = [MultiPartParser, FormParser]

    def get_object(self):
        return self.request.user.seller


class AdminSellersListView(generics.ListAPIView):
    """Admin: list all sellers with optional filters."""

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
    """Admin: view seller details."""

    permission_classes = [permissions.IsAdminUser]
    serializer_class = SellerSerializer

    def get_queryset(self):
        return Seller.objects.select_related(
            "user",
            "verified_by",
        ).all()


class AdminPendingSellersView(generics.ListAPIView):
    """Admin: list pending seller applications."""

    permission_classes = [permissions.IsAdminUser]
    serializer_class = SellerSerializer

    def get_queryset(self):
        return (
            Seller.objects.select_related(
                "user",
                "verified_by",
            )
            .filter(
                status=Seller.StatusChoices.PENDING,
            )
            .order_by("-applied_at")
        )


class AdminSellerVerifyView(generics.GenericAPIView):
    """Admin: approve a pending seller application."""

    permission_classes = [permissions.IsAdminUser]
    serializer_class = SellerSerializer

    def post(self, request, pk):
        try:
            seller = Seller.objects.select_related("user").get(pk=pk)

        except Seller.DoesNotExist:
            return Response(
                {
                    "error": "Seller not found",
                },
                status=status.HTTP_404_NOT_FOUND,
            )

        if seller.status != Seller.StatusChoices.PENDING:
            return Response(
                {
                    "error": "Only pending seller applications can be approved",
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
                        "request": request,
                    },
                ).data,
            },
            status=status.HTTP_200_OK,
        )


class AdminSellerRejectView(generics.GenericAPIView):
    """Admin: reject a pending seller application."""

    permission_classes = [permissions.IsAdminUser]
    serializer_class = SellerSerializer

    def post(self, request, pk):
        try:
            seller = Seller.objects.select_related("user").get(pk=pk)

        except Seller.DoesNotExist:
            return Response(
                {
                    "error": "Seller not found",
                },
                status=status.HTTP_404_NOT_FOUND,
            )

        if seller.status != Seller.StatusChoices.PENDING:
            return Response(
                {
                    "error": "Only pending seller applications can be rejected",
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
                        "request": request,
                    },
                ).data,
            },
            status=status.HTTP_200_OK,
        )


class PasswordResetRequestView(generics.CreateAPIView):
    """Request password reset via email OTP."""

    permission_classes = [permissions.AllowAny]
    serializer_class = PasswordResetRequestSerializer
    throttle_classes = [PasswordResetIPRateThrottle, PasswordResetEmailRateThrottle]

    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        email = serializer.validated_data["email"]
        if not User.objects.filter(email=email, is_active=True).exists():
            return Response({
                "message": "If this account is available, a password reset OTP has been sent.",
                "delivery_channel": "email", "email": mask_email(email), "expires_in": settings.OTP_CODE_EXPIRY_SECONDS,
            })
        otp = OTP.generate_otp(email=email)

        try:
            send_otp_email(
                to_email=email,
                code=otp.code,
                expires_in_seconds=settings.OTP_CODE_EXPIRY_SECONDS,
            )

        except OTPDeliveryError:
            otp.is_used = True
            otp.save(update_fields=["is_used"])

            return Response(
                {
                    "error": "Password reset email could not be sent.",
                },
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        return Response(
            {
                "message": "If this account is available, a password reset OTP has been sent.",
                "delivery_channel": "email",
                "email": mask_email(email),
                "expires_in": settings.OTP_CODE_EXPIRY_SECONDS,
            },
            status=status.HTTP_200_OK,
        )


class PasswordResetVerifyView(generics.GenericAPIView):
    """Verify email OTP and reset password."""

    permission_classes = [permissions.AllowAny]
    serializer_class = PasswordResetVerifySerializer
    throttle_classes = [PasswordResetIPRateThrottle, PasswordResetEmailRateThrottle]

    @transaction.atomic
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
                    "error": message,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            user = User.objects.get(email=email)

        except User.DoesNotExist:
            return Response(
                {
                    "error": "User not found",
                },
                status=status.HTTP_404_NOT_FOUND,
            )

        with transaction.atomic():
            user = User.objects.select_for_update().get(pk=user.pk)
            user.set_password(new_password)
            user.email_verified = True
            user.email_verified_at = user.email_verified_at or timezone.now()
            user.save(update_fields=["password", "email_verified", "email_verified_at"])

        return Response(
            {
                "message": "Password reset successful",
            },
            status=status.HTTP_200_OK,
        )


class ChangePasswordView(generics.GenericAPIView):
    """Change password for authenticated user."""

    permission_classes = [permissions.IsAuthenticated]
    serializer_class = ChangePasswordSerializer

    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = request.user
        old_password = serializer.validated_data["old_password"]
        new_password = serializer.validated_data["new_password"]

        with transaction.atomic():
            user = User.objects.select_for_update().get(pk=user.pk)
            if not user.check_password(old_password):
                return Response({"old_password": "Wrong password"}, status=status.HTTP_400_BAD_REQUEST)
            user.set_password(new_password)
            user.save(update_fields=["password"])

        return Response(
            {
                "message": "Password changed successfully",
            },
            status=status.HTTP_200_OK,
        )


class DeleteAccountView(generics.GenericAPIView):
    """Delete authenticated user account."""

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
                "message": "Your account has been deleted successfully",
            },
            status=status.HTTP_200_OK,
        )


class AdminDeleteUserView(generics.GenericAPIView):
    """Admin: delete a user account."""

    permission_classes = [permissions.IsAdminUser]

    def delete(self, request, user_id):
        try:
            user = User.objects.get(id=user_id)

        except User.DoesNotExist:
            return Response(
                {
                    "error": "User not found",
                },
                status=status.HTTP_404_NOT_FOUND,
            )

        if user.id == request.user.id:
            return Response(
                {
                    "error": "You cannot delete your own account",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        if user.is_superuser:
            return Response(
                {
                    "error": "Cannot delete super admin accounts",
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
                "message": f"User {user.email} deleted successfully",
            },
            status=status.HTTP_200_OK,
        )


class EmailVerifyRequestView(generics.GenericAPIView):
    """Request email verification."""

    permission_classes = [permissions.IsAuthenticated]
    serializer_class = EmailVerifyRequestSerializer

    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = request.user
        new_email = serializer.validated_data["email"]

        token = generate_email_verification_token(user, email=new_email)

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

        except Exception:
            clear_email_verification_token(user)
            return Response(
                {
                    "error": "Verification email could not be sent.",
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
    """Confirm email verification."""

    permission_classes = [permissions.IsAuthenticated]
    serializer_class = EmailVerifyConfirmSerializer

    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        token = serializer.validated_data["token"]
        try:
            with transaction.atomic():
                user = User.objects.select_for_update().get(pk=request.user.pk)
                new_email = pending_email_for_token(user, token)
                if not new_email:
                    raise serializers.ValidationError({"token": "Invalid or expired token."})
                if User.objects.all_with_deleted().filter(email__iexact=new_email).exclude(pk=user.pk).exists():
                    raise serializers.ValidationError({"email": "This email is unavailable."})
                user.email = new_email
                user.email_verified = True
                user.email_verified_at = timezone.now()
                user.save(update_fields=["email", "email_verified", "email_verified_at"])
                transaction.on_commit(lambda: clear_email_verification_token(user))
        except IntegrityError as exc:
            raise serializers.ValidationError({"email": "This email is unavailable."}) from exc

        return Response(
            {
                "message": "Email verified successfully",
            },
            status=status.HTTP_200_OK,
        )


class ThrottledTokenObtainPairView(TokenObtainPairView):
    throttle_classes = [AuthIPRateThrottle]
    serializer_class = VerifiedTokenObtainPairSerializer

    def post(self, request, *args, **kwargs):
        email = str(request.data.get("email", "")).strip()
        if User.objects.filter(email__iexact=email, is_active=True).filter(
            is_staff=True
        ).exists() or User.objects.filter(
            email__iexact=email, is_active=True, is_superuser=True
        ).exists():
            return Response(
                {"detail": "Privileged accounts must use email OTP and authenticator MFA."},
                status=status.HTTP_403_FORBIDDEN,
            )
        response = super().post(request, *args, **kwargs)

        refresh_token = response.data.get("refresh")
        access_token = response.data.get("access")

        response.data = {
            "access": access_token,
        }

        if refresh_token:
            set_refresh_cookie(response, refresh_token)

        return response


class CookieTokenRefreshView(generics.GenericAPIView):
    permission_classes = [permissions.AllowAny]
    throttle_classes = [AuthIPRateThrottle]

    def post(self, request):
        raw_refresh_token = request.COOKIES.get(get_refresh_cookie_name())

        if not raw_refresh_token:
            return Response(
                {
                    "detail": "Refresh token cookie was not provided.",
                },
                status=status.HTTP_401_UNAUTHORIZED,
            )

        try:
            refresh = RefreshToken(raw_refresh_token)
            user = User.objects.all_with_deleted().filter(pk=refresh.get("user_id")).first()
            if not user or not identity_token_valid(user, refresh) or not privileged_token_valid(user, refresh):
                response = Response(
                    {"detail": "Session expired or additional verification is required."},
                    status=status.HTTP_401_UNAUTHORIZED,
                )
                clear_refresh_cookie(response)
                return response
            access_token = str(refresh.access_token)

        except TokenError:
            response = Response(
                {
                    "detail": "Refresh token is invalid or expired.",
                },
                status=status.HTTP_401_UNAUTHORIZED,
            )
            clear_refresh_cookie(response)
            return response

        return Response(
            {
                "access": access_token,
            },
            status=status.HTTP_200_OK,
        )


class LogoutView(generics.GenericAPIView):
    permission_classes = [permissions.AllowAny]
    # Logout must always clear stale/invalid browser credentials as well.
    authentication_classes = []

    def post(self, request):
        raw_tokens = [(request.COOKIES.get(get_refresh_cookie_name()), RefreshToken)]
        authorization = request.META.get("HTTP_AUTHORIZATION", "").split()
        if len(authorization) == 2 and authorization[0].lower() == "bearer":
            raw_tokens.append((authorization[1], AccessToken))
        with transaction.atomic():
            for raw, token_type in raw_tokens:
                if not raw:
                    continue
                try:
                    token = token_type(raw)
                except TokenError:
                    continue
                user = User.objects.select_for_update().filter(pk=token.get("user_id")).first()
                if user and identity_token_valid(user, token) and privileged_token_valid(user, token):
                    user.invalidate_sessions()
                    break
        response = Response(
            {
                "message": "Logged out successfully",
            },
            status=status.HTTP_200_OK,
        )
        clear_refresh_cookie(response)
        return response
