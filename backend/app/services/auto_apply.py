from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.models.opportunity import Opportunity
from app.models.profile import Profile
from app.models.user import User


FIELD_HINTS: dict[str, list[str]] = {
    "full_name": ["full_name", "fullname", "name", "candidate_name", "student_name"],
    "email": ["email", "mail"],
    "bio": ["bio", "about", "summary", "cover_letter", "motivation"],
    "skills": ["skills", "tech_stack", "technologies", "expertise"],
    "education": ["education", "college", "university", "degree"],
    "interests": ["interests", "domain", "focus_area"],
    "achievements": ["achievements", "accomplishments", "projects"],
}


def _truncate(value: str | None, limit: int = 600) -> str:
    if not value:
        return ""
    if len(value) <= limit:
        return value
    return f"{value[:limit]}..."


def _build_value_map(user: User, profile: Profile | None) -> dict[str, str]:
    return {
        "full_name": _truncate(user.full_name or ""),
        "email": _truncate(user.email or ""),
        "bio": _truncate(profile.bio if profile else ""),
        "skills": _truncate(profile.skills if profile else ""),
        "education": _truncate(profile.education if profile else ""),
        "interests": _truncate(profile.interests if profile else ""),
        "achievements": _truncate(profile.achievements if profile else ""),
    }


async def _fill_field(page, selector: str, value: str) -> bool:
    if not value:
        return False
    locator = page.locator(selector)
    count = await locator.count()
    if count == 0:
        return False
    for index in range(count):
        field = locator.nth(index)
        try:
            if not await field.is_visible():
                continue
            tag_name = await field.evaluate("el => el.tagName.toLowerCase()")
            input_type = ((await field.get_attribute("type")) or "").lower()

            if tag_name == "select":
                options = await field.locator("option").all_text_contents()
                if options:
                    option_value = options[1] if len(options) > 1 else options[0]
                    await field.select_option(label=option_value)
                    return True
                continue

            if input_type in {"hidden", "checkbox", "radio", "file", "submit", "button"}:
                continue

            await field.fill(value)
            return True
        except Exception:
            continue
    return False


async def _autofill_form_fields(page, values: dict[str, str]) -> tuple[int, list[str]]:
    filled = 0
    filled_labels: list[str] = []

    for field_name, hints in FIELD_HINTS.items():
        value = values.get(field_name, "")
        if not value:
            continue
        selectors = []
        for hint in hints:
            selectors.extend(
                [
                    f"input[name*='{hint}' i]",
                    f"input[id*='{hint}' i]",
                    f"textarea[name*='{hint}' i]",
                    f"textarea[id*='{hint}' i]",
                    f"select[name*='{hint}' i]",
                    f"select[id*='{hint}' i]",
                    f"[aria-label*='{hint}' i]",
                    f"[placeholder*='{hint}' i]",
                ]
            )
        for selector in selectors:
            success = await _fill_field(page, selector, value)
            if success:
                filled += 1
                filled_labels.append(field_name)
                break
    return filled, filled_labels


async def _click_submit(page) -> tuple[bool, str]:
    submit_selectors = [
        "form button[type='submit']",
        "button[type='submit']",
        "input[type='submit']",
        "button:has-text('Apply')",
        "button:has-text('Submit')",
        "button:has-text('Continue')",
    ]
    for selector in submit_selectors:
        locator = page.locator(selector)
        count = await locator.count()
        if count == 0:
            continue
        button = locator.first
        try:
            if await button.is_visible() and await button.is_enabled():
                await button.click(timeout=settings.PLAYWRIGHT_TIMEOUT_MS)
                await page.wait_for_timeout(2000)
                return True, f"Clicked submit control using selector '{selector}'."
        except Exception:
            continue
    return False, "No clickable submit control detected."


async def auto_apply_with_playwright(
    opportunity: Opportunity,
    user: User,
    profile: Profile | None,
) -> dict[str, Any]:
    """
    Uses Playwright to open the opportunity form and auto-fill known fields.
    If AUTO_SUBMIT_ENABLED is true, it attempts to click submit.
    """
    value_map = _build_value_map(user, profile)
    screenshot_dir = Path(settings.AUTO_APPLY_SCREENSHOT_DIR)
    screenshot_dir.mkdir(parents=True, exist_ok=True)
    screenshot_path = screenshot_dir / f"apply-{user.id}-{opportunity.id}-{int(datetime.now().timestamp())}.png"

    try:
        from playwright.async_api import async_playwright
    except Exception as exc:
        return {
            "submitted": False,
            "filled_fields": 0,
            "filled_labels": [],
            "mode": "playwright_unavailable",
            "summary": f"Playwright unavailable: {exc}",
            "screenshot_path": None,
        }

    browser = None
    try:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=settings.PLAYWRIGHT_HEADLESS)
            context = await browser.new_context()
            page = await context.new_page()

            await page.goto(opportunity.url, wait_until="domcontentloaded", timeout=settings.PLAYWRIGHT_TIMEOUT_MS)
            await page.wait_for_timeout(1200)

            form_count = await page.locator("form").count()
            filled_fields, filled_labels = await _autofill_form_fields(page, value_map)

            submitted = False
            submit_note = "Auto-submit disabled. Form was auto-filled only."
            mode = "playwright_fill_only"
            if settings.AUTO_SUBMIT_ENABLED:
                submitted, submit_note = await _click_submit(page)
                mode = "playwright_submitted" if submitted else "playwright_submit_failed"

            await page.screenshot(path=str(screenshot_path), full_page=True)

            summary = (
                f"Detected forms: {form_count}; filled fields: {filled_fields} "
                f"({', '.join(filled_labels) if filled_labels else 'none'}). {submit_note}"
            )
            return {
                "submitted": submitted,
                "filled_fields": filled_fields,
                "filled_labels": filled_labels,
                "mode": mode,
                "summary": summary,
                "screenshot_path": str(screenshot_path),
            }
    except Exception as exc:
        return {
            "submitted": False,
            "filled_fields": 0,
            "filled_labels": [],
            "mode": "playwright_error",
            "summary": f"Playwright automation failed: {exc}",
            "screenshot_path": str(screenshot_path) if screenshot_path.exists() else None,
        }
    finally:
        if browser:
            try:
                await browser.close()
            except Exception:
                pass


def serialize_automation_log(result: dict[str, Any]) -> str:
    return json.dumps(
        {
            "mode": result.get("mode"),
            "submitted": result.get("submitted"),
            "filled_fields": result.get("filled_fields"),
            "filled_labels": result.get("filled_labels"),
            "summary": result.get("summary"),
            "screenshot_path": result.get("screenshot_path"),
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        },
        ensure_ascii=True,
    )
