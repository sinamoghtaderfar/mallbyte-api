from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.defaultfilters import pluralize


class OTPDeliveryError(Exception):
    pass


def normalize_email(email):
    return email.strip().lower()


def mask_email(email):
    email = normalize_email(email)

    if "@" not in email:
        return ""

    local_part, domain = email.split("@", 1)

    if len(local_part) <= 2:
        masked_local = local_part[0] + "***"
    else:
        masked_local = local_part[:2] + "***"

    return f"{masked_local}@{domain}"


def send_otp_email(*, to_email, code, expires_in_seconds=None):
    to_email = normalize_email(to_email)

    if not to_email:
        raise OTPDeliveryError("OTP email address is required.")

    if not settings.EMAIL_HOST_USER or not settings.EMAIL_HOST_PASSWORD:
        raise OTPDeliveryError("Brevo SMTP credentials are not configured.")

    expires_in_seconds = expires_in_seconds or getattr(
        settings,
        "OTP_CODE_EXPIRY_SECONDS",
        120,
    )

    expires_in_minutes = max(1, expires_in_seconds // 60)

    subject = getattr(
        settings,
        "OTP_EMAIL_SUBJECT",
        "Your MallByte verification code",
    )

    text_content = (
        f"Your MallByte verification code is: {code}\n\n"
        f"This code expires in {expires_in_minutes} minute"
        f"{pluralize(expires_in_minutes)}.\n\n"
        "If you did not request this code, you can ignore this email."
    )

    html_content = f"""
    <div style="font-family: Arial, sans-serif; max-width: 520px; margin: 0 auto;">
        <h2 style="color: #222;">MallByte verification code</h2>

        <p>Your verification code is:</p>

        <div style="
            font-size: 32px;
            font-weight: bold;
            letter-spacing: 6px;
            background: #f4f4f4;
            padding: 16px;
            text-align: center;
            border-radius: 8px;
            margin: 20px 0;
        ">
            {code}
        </div>

        <p>
            This code expires in {expires_in_minutes} minute{pluralize(expires_in_minutes)}.
        </p>

        <p style="color: #666; font-size: 13px;">
            If you did not request this code, you can ignore this email.
        </p>
    </div>
    """

    try:
        message = EmailMultiAlternatives(
            subject=subject,
            body=text_content,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[to_email],
        )
        message.attach_alternative(html_content, "text/html")
        message.send(fail_silently=False)

    except Exception as exc:
        raise OTPDeliveryError(str(exc)) from exc