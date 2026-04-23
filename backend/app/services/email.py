import asyncio
import aiosmtplib
from email.message import EmailMessage
from email.utils import formataddr
import logging

from app.core.config import settings, smtp_from_email_value, smtp_from_name_value, smtp_server_value

logger = logging.getLogger(__name__)


def _otp_text_body(*, otp: str, expiry_minutes: int = 5) -> str:
    return (
        "VidyaVerse Security Verification\n\n"
        f"Your verification code is: {otp}\n\n"
        f"This code expires in {expiry_minutes} minutes.\n"
        "If you did not request this code, you can safely ignore this email.\n\n"
        "VidyaVerse Team"
    )


def _otp_html_body(*, otp: str, expiry_minutes: int = 5) -> str:
    return f"""\
<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>VidyaVerse Verification Code</title>
  </head>
  <body style="margin:0;padding:24px;background:#f2e6ca;font-family:Arial,Helvetica,sans-serif;color:#111827;">
    <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="max-width:640px;margin:0 auto;">
      <tr>
        <td style="padding:0;">
          <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="background:#f9f4ea;border:2px solid #27272a;border-radius:8px;box-shadow:4px 4px 0 #27272a;">
            <tr>
              <td style="padding:28px 28px 22px 28px;">
                <table role="presentation" cellpadding="0" cellspacing="0" border="0" style="margin:0 0 14px 0;">
                  <tr>
                    <td style="padding:0;">
                      <table role="presentation" cellpadding="0" cellspacing="0" border="0" style="border-collapse:separate;">
                        <tr>
                          <td style="padding:8px 10px;background:#0f172a;border:2px solid #27272a;border-radius:6px 0 0 6px;">
                            <span style="display:inline-block;font-size:18px;line-height:1;font-weight:700;letter-spacing:0.2px;color:#f9f4ea;font-family:Georgia,'Times New Roman',serif;">
                              Vidya
                            </span>
                          </td>
                          <td style="padding:8px 10px;background:#4ade80;border-top:2px solid #27272a;border-right:2px solid #27272a;border-bottom:2px solid #27272a;border-radius:0 6px 6px 0;">
                            <span style="display:inline-block;font-size:18px;line-height:1;font-weight:700;letter-spacing:0.2px;color:#111827;font-family:Georgia,'Times New Roman',serif;">
                              Verse
                            </span>
                          </td>
                        </tr>
                      </table>
                    </td>
                  </tr>
                </table>
                <div style="font-size:12px;letter-spacing:1.8px;font-weight:700;text-transform:uppercase;color:#8a5a00;margin-bottom:10px;">
                  VidyaVerse Security
                </div>
                <h1 style="margin:0 0 10px 0;font-size:34px;line-height:1.1;font-weight:700;color:#111827;">
                  Your verification code
                </h1>
                <p style="margin:0 0 18px 0;font-size:16px;line-height:1.6;color:#27272a;">
                  Use this one-time code to continue securely. This code stays valid for {expiry_minutes} minutes.
                </p>
                <div style="background:#fcd34d;border:2px solid #27272a;border-radius:8px;padding:14px 16px;text-align:center;box-shadow:2px 2px 0 #27272a;">
                  <span style="display:inline-block;font-size:40px;line-height:1;font-weight:800;letter-spacing:14px;color:#111827;">
                    {otp}
                  </span>
                </div>
                <p style="margin:18px 0 0 0;font-size:14px;line-height:1.6;color:#52525b;">
                  If you did not request this code, you can safely ignore this email.
                </p>
                <hr style="border:none;border-top:1px solid #d4c6a7;margin:22px 0 16px 0;" />
                <p style="margin:0;font-size:14px;line-height:1.6;color:#27272a;">
                  <strong>VidyaVerse</strong><br />
                  AI Opportunity Intelligence Platform
                </p>
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>
  </body>
</html>
"""


async def send_email_otp(to_email: str, otp: str):
    """
    Sends a 6-digit OTP code to the requested end-user for two-step authentication.
    """
    expiry_minutes = 5
    subject = f"VidyaVerse verification code - expires in {expiry_minutes} minutes"
    text_body = _otp_text_body(otp=otp, expiry_minutes=expiry_minutes)
    html_body = _otp_html_body(otp=otp, expiry_minutes=expiry_minutes)

    message = EmailMessage()
    from_email = smtp_from_email_value()
    from_name = smtp_from_name_value()
    message["From"] = formataddr((from_name, from_email)) if from_name else from_email
    message["To"] = to_email
    message["Subject"] = subject
    message.set_content(text_body)
    message.add_alternative(html_body, subtype="html")

    smtp_server = smtp_server_value()
    if not smtp_server:
        raise RuntimeError("SMTP_SERVER is not configured.")
    if settings.SMTP_USE_TLS and settings.SMTP_STARTTLS:
        raise RuntimeError("Invalid SMTP settings: enable either SMTP_USE_TLS or SMTP_STARTTLS, not both.")
    if settings.SMTP_REQUIRE_AUTH and not (settings.SMTP_USER and settings.SMTP_PASSWORD):
        raise RuntimeError("SMTP_USER and SMTP_PASSWORD are required for authenticated SMTP delivery.")

    send_kwargs: dict[str, object] = {
        "hostname": smtp_server,
        "port": settings.SMTP_PORT,
        "start_tls": settings.SMTP_STARTTLS,
        "use_tls": settings.SMTP_USE_TLS,
        "timeout": settings.SMTP_TIMEOUT_SECONDS,
        "sender": from_email,
    }
    if settings.SMTP_USER:
        send_kwargs["username"] = settings.SMTP_USER
    if settings.SMTP_PASSWORD:
        send_kwargs["password"] = settings.SMTP_PASSWORD

    max_attempts = max(1, int(getattr(settings, "OTP_EMAIL_MAX_RETRIES", 3)))
    last_error: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            await aiosmtplib.send(message, **send_kwargs)
            if attempt > 1:
                logger.warning("OTP email delivery recovered on retry %s for %s", attempt, to_email)
            return True
        except Exception as exc:
            last_error = exc
            if attempt >= max_attempts:
                break
            backoff_seconds = min(4.0, 0.6 * (2 ** (attempt - 1)))
            logger.warning(
                "OTP email attempt %s/%s failed for %s: %s. Retrying in %.1fs",
                attempt,
                max_attempts,
                to_email,
                exc,
                backoff_seconds,
            )
            await asyncio.sleep(backoff_seconds)

    if last_error:
        logger.error(
            "Failed to send OTP email to %s after %s attempts: %s",
            to_email,
            max_attempts,
            last_error,
        )
        raise last_error
    logger.error("Failed to send OTP email to %s after %s attempts", to_email, max_attempts)
    raise RuntimeError("Unknown SMTP delivery failure")
