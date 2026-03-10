from rest_framework import serializers
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from .models import Profile

User = get_user_model()


class UserSerializer(serializers.ModelSerializer):
    """serializers to display user info"""

    class Meta:
        model = User
        fields = ["id", "phone", "email", "full_name", "is_seller"]
        read_only_fields = ["id", "is_seller"]


class RegisterSerializer(serializers.ModelSerializer):
    """Serializer for registering a new user"""

    password = serializers.CharField(write_only=True, required=True, validators=[validate_password])
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
