from __future__ import annotations

import hashlib
import re
from typing import Optional

from app.models.profile import Profile
from app.models.user import User

_USERNAME_SANITIZER = re.compile(r"[^a-z0-9]+")
_YEAR_CANDIDATE = re.compile(r"(19\d{2}|20\d{2})")
_COOL_SUFFIXES = (
    "techie",
    "builder",
    "coder",
    "analyst",
    "pilot",
    "ninja",
    "spark",
    "wizard",
)


def _normalize_username(value: str) -> str:
    return _USERNAME_SANITIZER.sub("", (value or "").strip().lower())


def _extract_birth_year_suffix(profile: Optional[Profile]) -> Optional[str]:
    if profile is None:
        return None
    text = (profile.date_of_birth or "").strip()
    if not text:
        return None
    matches = _YEAR_CANDIDATE.findall(text)
    if not matches:
        return None
    return str(matches[-1])[-2:]


def _username_root(user: User, profile: Optional[Profile]) -> str:
    candidates = [
        (profile.first_name if profile else None),
        user.full_name,
        (user.email or "").split("@")[0],
    ]
    for value in candidates:
        cleaned = _normalize_username(value or "")
        if cleaned:
            return cleaned[:8]
    return "user"


async def _username_available(username: str, user_id: str) -> bool:
    existing = await User.find_one(User.username == username)
    if existing is None:
        return True
    return str(existing.id) == str(user_id)


async def _build_unique_username(user: User, profile: Optional[Profile]) -> str:
    seed = hashlib.sha1(str(user.id).encode("utf-8")).hexdigest()
    suffix_word = _COOL_SUFFIXES[int(seed[:2], 16) % len(_COOL_SUFFIXES)]
    year_suffix = _extract_birth_year_suffix(profile) or f"{int(seed[2:4], 16) % 100:02d}"
    root = _username_root(user, profile)
    base = _normalize_username(f"{root}{suffix_word}")[:18] or "bigtechie"

    candidate = f"{base}{year_suffix}"
    if await _username_available(candidate, str(user.id)):
        return candidate

    for index in range(1, 200):
        alternate = f"{base}{year_suffix}{index:02d}"
        if await _username_available(alternate, str(user.id)):
            return alternate

    return f"{base}{str(user.id)[-6:].lower()}"


async def ensure_system_username(user: User, profile: Optional[Profile] = None) -> str:
    current = _normalize_username(user.username or "")
    if current and await _username_available(current, str(user.id)):
        if current != (user.username or ""):
            user.username = current
            await user.save()
        return current

    username = await _build_unique_username(user, profile)
    user.username = username
    await user.save()
    return username

