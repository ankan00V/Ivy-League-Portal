#!/usr/bin/env python3
"""Prove that OTP mail actually leaves the system, and say who accepted it.

Why this exists: Gmail SMTP was returning a genuine "2.0.0 OK" with a real queue
id for mail that never reached a Microsoft 365 college inbox. Everything looked
healthy from inside the app. The only way to tell a working sender from a broken
one is to send a real message and read back the provider's own identifier, so
that is what this does.

Dry run by default, in line with the other scripts here -- it prints the resolved
configuration and sends nothing. Pass --to ADDRESS to actually send.

    python scripts/verify_email_delivery.py
    python scripts/verify_email_delivery.py --to you@yourcollege.ac.in
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import (  # noqa: E402
    email_provider_value,
    resend_from_email_value,
    settings,
    smtp_from_email_value,
    smtp_server_value,
)


def _mask(value: str | None) -> str:
    text = str(value or "")
    if not text:
        return "EMPTY"
    return f"SET (len={len(text)})"


def _print_config() -> str:
    provider = email_provider_value()
    print("Resolved email configuration")
    print(f"  EMAIL_PROVIDER      : {provider}")
    if provider == "resend":
        print(f"  RESEND_API_KEY      : {_mask(settings.RESEND_API_KEY)}")
        print(f"  RESEND_API_BASE_URL : {settings.RESEND_API_BASE_URL}")
        print(f"  from address        : {resend_from_email_value()}")
    else:
        print(f"  SMTP_SERVER         : {smtp_server_value()}:{settings.SMTP_PORT}")
        print(f"  SMTP_USER           : {_mask(settings.SMTP_USER)}")
        print(f"  from address        : {smtp_from_email_value()}")
    return provider


def _warn_on_obvious_misconfiguration(provider: str) -> None:
    if provider != "resend":
        return
    if not str(settings.RESEND_API_KEY or "").strip():
        print("\n  ! RESEND_API_KEY is empty - sending will fail.")
    sender = resend_from_email_value()
    domain = sender.rsplit("@", 1)[-1].lower() if "@" in sender else ""
    consumer = {"gmail.com", "googlemail.com", "outlook.com", "hotmail.com", "yahoo.com"}
    if domain in consumer:
        print(
            f"\n  ! Sending as {sender} while provider=resend. Resend can only send from a\n"
            "    domain you have verified, so set RESEND_FROM_EMAIL to an address on it."
        )


async def _send(to_email: str) -> int:
    # Import here so a dry run works even if the transport deps are unhappy.
    from app.services.email import send_email_otp

    print(f"\nSending a real test message to {to_email} ...")
    try:
        await send_email_otp(to_email, "000000")
    except Exception as exc:  # noqa: BLE001 - operator-facing tool
        print(f"\nFAILED: {type(exc).__name__}: {exc}")
        print("\nThe message did NOT leave the system. Nothing was delivered.")
        return 1

    print("\nAccepted by the provider.")
    print("  The code in that message is 000000 and is NOT a valid login code -")
    print("  it is a delivery test only.")
    print("\nNow confirm it actually landed:")
    print("  1. Check the inbox, then the junk/spam folder.")
    print("  2. If it is in neither, check the sending account for a bounce.")
    print("  Accepted by a provider is not the same as delivered to a human.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--to",
        default=os.environ.get("VERIFY_EMAIL_TO", ""),
        help="Recipient for a real test send. Omit for a dry run.",
    )
    args = parser.parse_args()

    provider = _print_config()
    _warn_on_obvious_misconfiguration(provider)

    recipient = str(args.to or "").strip()
    if not recipient:
        print("\nDry run - no message sent. Pass --to ADDRESS to send one.")
        return 0

    return asyncio.run(_send(recipient))


if __name__ == "__main__":
    raise SystemExit(main())
