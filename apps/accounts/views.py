from django.contrib.auth import get_user_model
from django.http import Http404

from rest_framework import generics, permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework import serializers
from .models import Address, Profile, OTP, Seller
from .serializers import (
    AddressSerializer,
    ProfileSerializer,
    RegisterSerializer,
    UserSerializer,
    OTPRequestSerializer,
    OTPVerifySerializer,
    SellerApplicationSerializer, SellerSerializer, 
    SellerUpdateSerializer, AdminSellerActionSerializer
)

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
        
        return Response(
            {"message": f"Seller {seller.store_name} rejected"},
            status=status.HTTP_200_OK
        )