from __future__ import annotations

PERSONAL_EMAIL_DOMAINS = frozenset(
    {
        "gmail.com",
        "googlemail.com",
        "yahoo.com",
        "yahoo.co.in",
        "yahoo.in",
        "outlook.com",
        "hotmail.com",
        "live.com",
        "msn.com",
        "icloud.com",
        "me.com",
        "mac.com",
        "aol.com",
        "protonmail.com",
        "proton.me",
        "pm.me",
        "zoho.com",
        "yandex.com",
        "gmx.com",
        "mail.com",
        "rediffmail.com",
    }
)


def extract_email_domain(email: str) -> str:
    value = str(email or "").strip().lower()
    if "@" not in value:
        return ""
    return value.rsplit("@", 1)[-1].strip()


def is_corporate_email(email: str) -> bool:
    domain = extract_email_domain(email)
    if not domain:
        return False
    return domain not in PERSONAL_EMAIL_DOMAINS
