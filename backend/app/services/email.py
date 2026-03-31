import aiosmtplib
from email.message import EmailMessage
from app.core.config import settings


async def send_email_otp(to_email: str, otp: str):
    """
    Sends a 6-digit OTP code to the requested end-user for two-step authentication.
    """
    subject = "Your VidyaVerse Authentication Code"
    body = f"""
    Hello,

    Your VidyaVerse authentication code is: {otp}

    This code will expire in 5 minutes. If you did not request this code, please ignore this email.

    Welcome to VidyaVerse!
    """

    message = EmailMessage()
    message["From"] = settings.SMTP_FROM_EMAIL
    message["To"] = to_email
    message["Subject"] = subject
    message.set_content(body)

    if not settings.SMTP_SERVER:
        raise RuntimeError("SMTP_SERVER is not configured.")
    if settings.SMTP_USE_TLS and settings.SMTP_STARTTLS:
        raise RuntimeError("Invalid SMTP settings: enable either SMTP_USE_TLS or SMTP_STARTTLS, not both.")
    if settings.SMTP_REQUIRE_AUTH and not (settings.SMTP_USER and settings.SMTP_PASSWORD):
        raise RuntimeError("SMTP_USER and SMTP_PASSWORD are required for authenticated SMTP delivery.")

    send_kwargs = {
        "message": message,
        "hostname": settings.SMTP_SERVER,
        "port": settings.SMTP_PORT,
        "start_tls": settings.SMTP_STARTTLS,
        "use_tls": settings.SMTP_USE_TLS,
        "timeout": settings.SMTP_TIMEOUT_SECONDS,
    }
    if settings.SMTP_USER:
        send_kwargs["username"] = settings.SMTP_USER
    if settings.SMTP_PASSWORD:
        send_kwargs["password"] = settings.SMTP_PASSWORD

    try:
        await aiosmtplib.send(**send_kwargs)
        return True
    except Exception as e:
        print(f"Failed to send email to {to_email}: {e}")
        raise e
