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


# Domains that look academic without being a fixed list. Indian colleges are the
# reason this is pattern-based: `lpu.in` and `vitstudent.ac.in` are both real
# student domains, and a plain ".edu" allowlist rejects the first one. An
# existing student in this database signs in as @lpu.in, so a strict allowlist
# would have locked out a real user on day one.
ACADEMIC_DOMAIN_SUFFIXES = (
    ".edu",
    ".ac.in",
    ".edu.in",
    ".ac.uk",
    ".edu.au",
    ".ac.jp",
    ".edu.sg",
    ".ac.nz",
    ".edu.pk",
    ".ac.bd",
    ".edu.np",
)


def looks_academic(email: str) -> bool:
    """Whether the domain carries a recognised academic suffix."""
    domain = extract_email_domain(email)
    if not domain:
        return False
    return any(domain == suffix.lstrip(".") or domain.endswith(suffix) for suffix in ACADEMIC_DOMAIN_SUFFIXES)


def is_institutional_email(email: str, *, strict: bool = False) -> bool:
    """Whether a candidate may sign up with this address.

    Default (strict=False) is the same rule employers already get: anything that
    is not a consumer mailbox. That admits `lpu.in`, which no academic-suffix
    list would, at the cost of also admitting a company domain - an acceptable
    trade while college domains are this irregular.

    strict=True additionally requires an academic suffix, for when the corpus of
    known college domains is good enough to turn it on.
    """
    domain = extract_email_domain(email)
    if not domain or domain in PERSONAL_EMAIL_DOMAINS:
        return False
    if strict:
        return looks_academic(email)
    return True
