import re

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers

from .models import Address, Profile, Seller

User = get_user_model()


class UserSerializer(serializers.ModelSerializer):
    """Serializer to display user info"""

    class Meta:
        model = User
        fields = [
            "id",
            "email",
            "phone",
            "full_name",
            "is_seller",
            "email_verified",
        ]
        read_only_fields = [
            "id",
            "is_seller",
            "email_verified",
        ]


class RegisterSerializer(serializers.ModelSerializer):
    """Serializer for registering a new user"""

    password = serializers.CharField(
        write_only=True,
        required=True,
        validators=[validate_password],
    )
    password2 = serializers.CharField(
        write_only=True,
        required=True,
    )
    phone = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
        max_length=15,
    )

    class Meta:
        model = User
        fields = [
            "email",
            "phone",
            "full_name",
            "password",
            "password2",
        ]

    def validate_email(self, value):
        return value.strip().lower()

    def validate_phone(self, value):
        if not value:
            return None

        cleaned = re.sub(r'[\s\-\(\)]', '', value)

        pattern = r'^\+\d{1,3}\d{4,14}$'
        if not re.match(pattern, cleaned):
            raise serializers.ValidationError(
                "Phone must be in international format: +[country code][number]"
            )

        return cleaned

    def validate(self, attrs):
        if attrs["password"] != attrs["password2"]:
            raise serializers.ValidationError(
                {
                    "password": "Passwords don't match"
                }
            )

        return attrs

    def create(self, validated_data):
        validated_data.pop("password2")

        user = User.objects.create_user(**validated_data)

        try:
            from apps.rbac.models import Role
            from apps.rbac.utils import assign_role

            customer_role = Role.objects.get(name="customer")
            assign_role(user, customer_role, None)

        except Role.DoesNotExist:
            pass

        return user


class ProfileSerializer(serializers.ModelSerializer):
    """Serializer for user profile"""

    user = UserSerializer(read_only=True)

    class Meta:
        model = Profile
        fields = [
            "id",
            "user",
            "avatar",
            "birth_date",
            "gender",
            "national_code",
            "loyalty_points",
        ]
        read_only_fields = ["id", "user", "loyalty_points"]


class AddressSerializer(serializers.ModelSerializer):
    """Serializer for user addresses"""

    class Meta:
        model = Address
        fields = [
            "id",
            "user",
            "title",
            "province",
            "city",
            "street",
            "alley",
            "building_number",
            "floor",
            "unit",
            "postal_code",
            "receiver_name",
            "receiver_phone",
            "is_default",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "user", "created_at", "updated_at"]

    def validate_postal_code(self, value):
        """
        Validate postal code.

        Postal code formats differ by country:
        - Iran often uses 10 digits
        - Germany uses 5 digits
        - Some countries use letters, spaces, or hyphens

        So we keep it flexible, but still reject clearly invalid values.
        """
        value = value.strip()

        if len(value) < 3 or len(value) > 20:
            raise serializers.ValidationError(
                "Postal code must be between 3 and 20 characters."
            )

        if not re.match(r"^[A-Za-z0-9\s\-]+$", value):
            raise serializers.ValidationError(
                "Postal code can only contain letters, numbers, spaces, or hyphens."
            )

        return value

    def validate_receiver_phone(self, value):
        """
        Validate receiver phone.

        Accepted examples:
        - 09123456789
        - +989123456789
        - +4917612345678
        """
        value = value.strip().replace(" ", "").replace("-", "")

        local_pattern = r"^0\d{7,14}$"
        international_pattern = r"^\+\d{8,15}$"

        if not re.match(local_pattern, value) and not re.match(
            international_pattern,
            value,
        ):
            raise serializers.ValidationError(
                "Phone number must be local format like 09123456789 or international format like +989123456789."
            )

        return value


class OTPRequestSerializer(serializers.Serializer):
    """Serializer for requesting email OTP"""

    email = serializers.EmailField()

    def validate_email(self, value):
        return value.strip().lower()
    
    

class OTPVerifySerializer(serializers.Serializer):
    """Serializer for verifying email OTP"""

    email = serializers.EmailField()
    code = serializers.CharField(max_length=6)

    def validate_email(self, value):
        return value.strip().lower()

    def validate_code(self, value):
        if not value.isdigit() or len(value) != 6:
            raise serializers.ValidationError("Code must be 6 digits")

        return value
    
    
class SellerApplicationSerializer(serializers.ModelSerializer):
    """Serializer for applying to become a seller"""
    
    class Meta:
        model = Seller
        fields = [
            'store_name', 'description', 'business_phone', 
            'business_email', 'website', 'bank_info', 'documents'
        ]
        read_only_fields = ['id']
    def validate_store_name(self, value):
        if Seller.objects.filter(store_name=value).exists():
            raise serializers.ValidationError("This store name is already taken")
        return value

class SellerSerializer(serializers.ModelSerializer):
    """Serializer for seller details"""

    user = UserSerializer(read_only=True)
    
    class Meta:
        model= Seller
        fields = [
            'id', 'user', 'store_name', 'store_slug', 'logo', 'banner',
            'description', 'status', 'verified_at', 'business_phone',
            'business_email', 'website', 'commission_rate', 'total_sales',
            'total_orders', 'balance', 'applied_at', 'created_at'
        ]
        read_only_fields = [
            'id', 'user', 'store_slug', 'status', 'verified_at',
            'commission_rate', 'total_sales', 'total_orders', 'balance',
            'applied_at', 'created_at'
        ]
        
class SellerUpdateSerializer(serializers.ModelSerializer):
    """Serializer for sellers to update their info"""
    
    class Meta:
        model = Seller
        fields = [
            'logo', 'banner', 'description', 'business_phone',
            'business_email', 'website', 'bank_info'
        ]

class AdminSellerActionSerializer(serializers.Serializer):
    """
    Serializer for admin actions on sellers.
    """
    action = serializers.ChoiceField(choices=['approve', 'reject'])
    reason = serializers.CharField(required=False, allow_blank=True)
    
class PasswordResetRequestSerializer(serializers.Serializer):
    """Serializer for requesting password reset"""

    email = serializers.EmailField()

    def validate_email(self, value):
        email = value.strip().lower()

        if not User.objects.filter(email=email).exists():
            raise serializers.ValidationError(
                "No user found with this email address"
            )

        return email

class PasswordResetVerifySerializer(serializers.Serializer):
    """Serializer for verifying OTP and resetting password"""

    email = serializers.EmailField()
    code = serializers.CharField(max_length=6)
    new_password = serializers.CharField(
        write_only=True,
        min_length=8,
        validators=[validate_password],
    )

    def validate_email(self, value):
        return value.strip().lower()

    def validate_code(self, value):
        if not value.isdigit() or len(value) != 6:
            raise serializers.ValidationError("Code must be 6 digits")

        return value

class ChangePasswordSerializer(serializers.Serializer):
    """Serializer for changing password (when logged in)"""
    old_password = serializers.CharField(write_only=True)
    new_password = serializers.CharField(write_only=True, min_length=8)
    confirm_password = serializers.CharField(write_only=True, min_length=8)
    
    def validate(self, attrs):
        if attrs['new_password'] != attrs['confirm_password']:
            raise serializers.ValidationError({"new_password": "Passwords don't match"})
        return attrs
    
class DeleteAccountSerializer(serializers.Serializer):
    """Serializer for deleting account"""
    confirm = serializers.BooleanField(required = True)
    
    def validate_confirm(self, value):
        if not value:
            raise serializers.ValidationError("You must confirm to delete your account")
        return value
    
class EmailVerifyRequestSerializer(serializers.Serializer):
    """Serializer for requesting email verification"""
    email = serializers.EmailField()
    
    def validate_email(self, value):
        from django.contrib.auth import get_user_model
        User = get_user_model()
        if User.objects.filter(email=value, email_verified=True).exists():
            raise serializers.ValidationError("This email is already verified by another user")
        return value
    
class EmailVerifyConfirmSerializer(serializers.Serializer):
    """Serializer for confirming email verification"""
    token = serializers.CharField()