import secrets
from django.utils import timezone
from datetime import timedelta

def generate_email_verification_token(user):
    """Generate a simple token for email verification"""
    token = secrets.token_urlsafe(32)
    
    from django.core.cache import cache
    
    cache_key = f'email_verify_{user.id}'
    # 1 hour expiry
    cache.set(cache_key, token, timeout=3600)  
    return token

def verify_email_token(user, token):
    """Verify email token"""
    
    from django.core.cache import cache
    
    cache_key = f'email_verify_{user.id}'
    stored_token = cache.get(cache_key)
    return stored_token == token