import re
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers

from .models import Address, Profile, Seller

User = get_user_model()


class UserSerializer(serializers.ModelSerializer):
    """serializers to display user info"""

    class Meta:
        model = User
        fields = ["id", "phone", "email", "full_name", "is_seller"]
        read_only_fields = ["id", "is_seller"]


class RegisterSerializer(serializers.ModelSerializer):
    """Serializer for registering a new user"""

    password = serializers.CharField(
        write_only=True, required=True, validators=[validate_password]
    )
    password2 = serializers.CharField(write_only=True, required=True)

    class Meta:
        model = User
        fields = ["phone", "email", "full_name", "password", "password2"]

    def validate(self, attrs):
        if attrs["password"] != attrs["password2"]:
            raise serializers.ValidationError({"password": "Passwords don't match"})
        return attrs

    def create(self, validated_data):

        validated_data.pop("password2")
        user = User.objects.create_user(**validated_data)

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
        """Validate postal code (10 digits)"""
        if not value.isdigit() or len(value) != 10:
            raise serializers.ValidationError("Postal code must be exactly 10 digits")
        return value

    def validate_receiver_phone(self, value):
        """Validate phone number (11 digits starting with 09)"""
        if not value.isdigit() or len(value) != 11 or not value.startswith("09"):
            raise serializers.ValidationError(
                "Phone number must be 11 digits starting with 09"
            )
        return value


class OTPRequestSerializer(serializers.Serializer):
    """Serializer for requesting OTP"""
    phone = serializers.CharField(max_length = 15)
    
    
    def validate_phone(self, value):
        """Validate phone number"""
        cleaned = re.sub(r'[\s\-\(\)]', '', value)
        
        pattern = r'^\+\d{1,3}\d{4,14}$'
        if not re.match(pattern, cleaned):
            raise serializers.ValidationError(
                "Phone must be in international format: +[country code][number] (e.g., +989121234567)"
            )
        
        return cleaned
    
    

class OTPVerifySerializer(serializers.Serializer):
    """Serializer for verifying OTP"""
    phone = serializers.CharField(max_length = 15)
    code = serializers.CharField(max_length=6)
    
    def validate_code(self, value):
        """Validate code is 6 digits"""
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
    """Serializer for admin actions on sellers"""
    
    reason = serializers.CharField(required=False, allow_blank=True)
    
class AdminSellerActionSerializer(serializers.Serializer):
    """
    Serializer for admin actions on sellers.
    """
    action = serializers.ChoiceField(choices=['approve', 'reject'])
    reason = serializers.CharField(required=False, allow_blank=True)
    
class PasswordResetRequestSerializer(serializers.Serializer):
    """Serializer for requesting password reset"""
    phone = serializers.CharField(max_length = 15)
    
    def validate_phone(self, value):
        #remove space -
        cleaned = re.sub(r'[\s\-\(\)]', '', value)
        
        pattern = r'^\+\d{1,3}\d{4,14}$'
        
        if not re.match(pattern, cleaned):
            raise serializers.ValidationError(
                "Phone must be in international format: +[country code][number]"
            )
        return cleaned

class PasswordResetVerifySerializer(serializers.Serializer):
    """Serializer for verifying OTP and resetting password"""
    phone = serializers.CharField(max_length = 15)
    code = serializers.CharField(max_length = 6)
    new_password = serializers.CharField(write_only=True, min_length=8)
    confirm_password = serializers.CharField(write_only=True, min_length=8)
    
    def validate_code(self, value):
        if not value.isdigit() or len(value) !=6:
            raise serializers.ValidationError("Code must be 6 digits")
        return value
    
    def validate(self, attrs):
        if attrs['new_password'] != attrs['confirm_password']:
            raise serializers.ValidationError({"new_password": "Passwords don't match"})
        return attrs

class ChangePasswordSerializer(serializers.Serializer):
    """Serializer for changing password (when logged in)"""
    old_password = serializers.CharField(write_only=True)
    new_password = serializers.CharField(write_only=True, min_length=8)
    confirm_password = serializers.CharField(write_only=True, min_length=8)
    
    def validate(self, attrs):
        if attrs['new_password'] != attrs['confirm_password']:
            raise serializers.ValidationError({"new_password": "Passwords don't match"})
        return attrs