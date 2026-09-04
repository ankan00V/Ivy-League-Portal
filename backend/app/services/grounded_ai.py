"""One narrow job: let a model write prose over numbers it is not allowed to invent.

Every AI feature on this platform sits on top of a measurement that already
exists - a demand share, a coverage percentage, a funnel conversion. The model's
job is never to work out the number. It is to say what the number means to the
person reading it, which is the part a table genuinely cannot do and the part a
generic assistant gets wrong because it has never seen the data.

Three rules make that safe, and they are the whole of this module.

**Python computes, the model narrates.** Facts arrive as a dict that was
produced by the same services the dashboards read. The model is asked for
sentences, never for arithmetic.

**A number not in the facts is a hallucination.** Not a stylistic problem - a
recruiter reading "18% of candidates have Kubernetes" will act on it. Every
numeric literal in the model's output is checked against the values it was
given, and an answer carrying an unsupported one is discarded rather than
shown. This is the check that makes the feature safe to ship; without it the
honest thing would be to not ship it.

**Below the evidence floor there is no answer.** The refusal is the product.
The other services here already withhold a cohort statistic under five students
and a coverage figure under three assessments, and a paragraph of confident
prose over the same thin data would walk straight around those floors. A
feature that says "not enough data yet, here is exactly what is missing" is
worth more than one that always produces something.

The fallback when the LLM is unconfigured, slow or wrong is not an apology - it
is a deterministic sentence assembled from the same facts. The page always says
something true.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Optional

from app.core.config import settings
from app.services.openai_client import create_async_openai_client

logger = logging.getLogger(__name__)

#: Numbers every answer may use without them appearing in the facts: small
#: counts the model uses to enumerate its own points ("three things stand out"),
#: and the percentage endpoints. Kept deliberately tiny - the wider this gets,
#: the less the verifier is worth.
_ALWAYS_ALLOWED = {0.0, 1.0, 2.0, 3.0, 100.0}

#: How close a quoted number must be to a supported one to count as that number.
#: Wide enough that a model rounding 4.13% to 4.1% is not treated as inventing a
#: figure, tight enough that 4.1 and 14.1 never collapse into each other.
_TOLERANCE = 0.06

_NUMBER_PATTERN = re.compile(r"-?\d+(?:\.\d+)?")


@dataclass
class GroundedAnswer:
    """What the caller renders. `grounded` says which of the three paths ran."""

    headline: str
    paragraphs: list[str]
    actions: list[str] = field(default_factory=list)
    #: "llm" when the model's answer passed verification, "deterministic" when
    #: it was unavailable or rejected, "refused" when the evidence floor failed.
    source: str = "deterministic"
    #: Present only on a refusal, and it names what is missing rather than
    #: saying the request failed.
    refusal: Optional[str] = None
    #: Whichever checks the model's answer failed, kept for the logs and for the
    #: admin view. A silent fallback is how a broken feature looks healthy.
    rejected_because: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "headline": self.headline,
            "paragraphs": list(self.paragraphs),
            "actions": list(self.actions),
            "source": self.source,
            "refusal": self.refusal,
            "rejected_because": list(self.rejected_because),
        }


def collect_supported_numbers(facts: Any) -> set[float]:
    """Every number the facts contain, at any depth.

    Percentages are registered in both forms. The services store shares as
    0..1 and every surface renders them as 0..100, so a model shown 0.041 and
    writing "4.1%" is quoting the fact it was given, not inventing one.
    """
    found: set[float] = set(_ALWAYS_ALLOWED)

    def walk(node: Any) -> None:
        if isinstance(node, bool):
            return
        if isinstance(node, (int, float)):
            value = float(node)
            found.add(round(value, 4))
            if -1.0 <= value <= 1.0:
                found.add(round(value * 100, 4))
            found.add(float(round(value)))
            return
        if isinstance(node, dict):
            for item in node.values():
                walk(item)
            return
        if isinstance(node, (list, tuple, set)):
            for item in node:
                walk(item)

    walk(facts)
    return found


def unsupported_numbers(text: str, supported: set[float]) -> list[str]:
    """Numeric literals in `text` that no supported value accounts for.

    Years are exempt. "2026" in "by 2026" is a date, not a claim about the data,
    and treating it as one rejected otherwise-correct answers.
    """
    offenders: list[str] = []
    for raw in _NUMBER_PATTERN.findall(text or ""):
        try:
            value = float(raw)
        except ValueError:
            continue
        if 1900 <= value <= 2200 and "." not in raw:
            continue
        if any(abs(value - candidate) <= _TOLERANCE for candidate in supported):
            continue
        offenders.append(raw)
    return offenders


class GroundedNarrator:
    """Shared LLM plumbing. One instance, reused by every role's feature."""

    def __init__(self) -> None:
        self._provider = str(getattr(settings, "LLM_PROVIDER", "") or "openai_compatible").strip().lower()
        self._api_base_url = (
            (getattr(settings, "LLM_API_BASE_URL", "") or "").strip()
            or (getattr(settings, "OPENROUTER_BASE_URL", "") or "").strip()
            or "https://openrouter.ai/api/v1"
        )
        self._api_key = (
            (getattr(settings, "LLM_API_KEY", "") or getattr(settings, "OPENROUTER_API_KEY", "") or "").strip()
            or None
        )
        self._model = live_model(
            (getattr(settings, "BRIEFING_LLM_MODEL", "") or "").strip()
            or (getattr(settings, "RAG_LLM_MODEL", "") or "").strip()
            or (getattr(settings, "LLM_MODEL", "") or "").strip(),
            fallback="nvidia/nemotron-3-super-120b-a12b",
            context="role briefings",
        )
        self._client: Any | None = None

    def _extra_body(self) -> dict[str, Any] | None:
        """Turn off the model's reasoning preamble where the host supports it.

        Reasoning-tuned models on NVIDIA's endpoint narrate their working before
        answering, and it is neither wanted nor read here - the reasoning this
        feature needs already happened in Python, and the model is only being
        asked to phrase the result. Leaving it on costs the whole latency
        budget: measured on this prompt, nemotron-3.5-lightning went from 37.4
        to 7.0 seconds and nemotron-3-nano from 8.9 to 2.1 when it was turned
        off, and both stopped emitting a preamble that had to be parsed around.

        Sent only to hosts known to accept it. An unrecognised body field is a
        400 on some OpenAI-compatible gateways, which would turn a latency
        optimisation into a total outage of every briefing.
        """
        if "integrate.api.nvidia.com" not in self._api_base_url.lower():
            return None
        return {"chat_template_kwargs": {"thinking": False}}

    @property
    def configured(self) -> bool:
        return bool(self._api_key)

    def _get_client(self) -> Any:
        if self._client is None:
            self._client = create_async_openai_client(
                base_url=self._api_base_url,
                api_key=self._api_key or "dummy_key_to_prevent_boot_crash",
            )
        return self._client

    async def narrate(
        self,
        *,
        system_prompt: str,
        facts: dict[str, Any],
        fallback: GroundedAnswer,
        max_paragraphs: int = 3,
        max_actions: int = 4,
        timeout_seconds: float | None = None,
    ) -> GroundedAnswer:
        """Ask for prose over `facts`; return `fallback` unless it verifies."""
        if not self.configured:
            fallback.rejected_because = ["llm_not_configured"]
            return fallback

        supported = collect_supported_numbers(facts)
        messages = [
            {"role": "system", "content": system_prompt.strip() + "\n\n" + _OUTPUT_CONTRACT},
            {"role": "user", "content": json.dumps(facts, default=str)},
        ]
        # A briefing is a dashboard panel that loads beside other panels, not a
        # chat turn somebody is watching a cursor blink through, so it can wait
        # longer than Ask AI does. Measured on the configured endpoint, a
        # 30B-A3B model answers this prompt in 4-27 seconds; the interactive
        # 12-second budget rejected answers that were merely slow.
        timeout = timeout_seconds or max(
            8.0, float(getattr(settings, "BRIEFING_LLM_TIMEOUT_SECONDS", 30.0))
        )

        try:
            response = await asyncio.wait_for(
                self._get_client().chat.completions.create(
                    model=self._model,
                    messages=messages,
                    response_format={"type": "json_object"},
                    extra_body=self._extra_body(),
                    temperature=0.2,
                    # Generous on purpose. The first model tried here spent all
                    # 700 tokens on an unrequested "thinking process" preamble
                    # and stopped at finish_reason=length before emitting a
                    # single brace, which arrives as "unparseable" and looks
                    # like a bad model rather than a budget that was too small.
                    max_tokens=int(getattr(settings, "BRIEFING_LLM_MAX_TOKENS", 1600)),
                ),
                timeout=timeout,
            )
            content = ""
            if response.choices and response.choices[0].message:
                content = response.choices[0].message.content or ""
        except asyncio.TimeoutError:
            logger.warning("Grounded narration timed out after %.1fs; serving deterministic text.", timeout)
            fallback.rejected_because = ["timeout"]
            return fallback
        except Exception as exc:
            logger.warning("Grounded narration failed; serving deterministic text: %s", exc)
            fallback.rejected_because = [f"error:{type(exc).__name__}"]
            return fallback

        parsed = _extract_json(content)
        if not isinstance(parsed, dict):
            truncated = bool(content) and "{" in content and content.rstrip()[-1:] != "}"
            reason = "truncated" if truncated else "unparseable"
            logger.warning(
                "Grounded narration %s (%d chars); raise BRIEFING_LLM_MAX_TOKENS if this persists.",
                reason,
                len(content or ""),
            )
            fallback.rejected_because = [reason]
            return fallback

        headline = str(parsed.get("headline") or "").strip()
        paragraphs = [str(p).strip() for p in (parsed.get("paragraphs") or []) if str(p).strip()]
        actions = [str(a).strip() for a in (parsed.get("actions") or []) if str(a).strip()]
        if not headline or not paragraphs:
            fallback.rejected_because = ["empty"]
            return fallback

        failures: list[str] = []
        for label, text in [("headline", headline), *[(f"paragraph[{i}]", p) for i, p in enumerate(paragraphs)], *[(f"action[{i}]", a) for i, a in enumerate(actions)]]:
            offenders = unsupported_numbers(text, supported)
            if offenders:
                failures.append(f"{label}:unsupported_numbers={','.join(offenders[:4])}")
        if failures:
            # Logged loudly and at the value, because this is the check that
            # decides whether a number a user acts on came from the database.
            logger.warning("Grounded narration rejected: %s", "; ".join(failures[:3]))
            fallback.rejected_because = failures
            return fallback

        return GroundedAnswer(
            headline=headline,
            paragraphs=paragraphs[:max_paragraphs],
            actions=actions[:max_actions],
            source="llm",
        )


_OUTPUT_CONTRACT = """
Output one JSON object and nothing else. No preamble, no explanation of your
reasoning, no text before the opening brace or after the closing brace. A
response that begins by describing what you are about to do is a failed
response - it is discarded unread, because a truncated thinking process
contains no answer at all.

The object has exactly these keys:
  "headline"   - one sentence, under 110 characters, stating the single most
                 important thing in the data.
  "paragraphs" - 2 to 3 short paragraphs of plain prose. No markdown, no bullet
                 characters, no headings.
  "actions"    - 2 to 4 imperative next steps, each one line.

Hard rules, in order of importance:
1. Every number you write must appear in the data you were given. Do not
   calculate, estimate, extrapolate or round to a figure that is not there. If
   a point needs a number you were not given, make the point without it.
2. Do not invent names of people, companies, institutions, courses or tools
   that are not in the data.
3. Say what the data means for the reader and what to do about it. Do not
   restate the table back to them.
4. Where the data is thin, say so plainly. Confidence you do not have is worse
   than an admission you do.
5. Write in British English, in the second person, plainly. No marketing voice.

All three keys are required. An object carrying only a headline is discarded -
the headline is one sentence, and the paragraphs are where the reading actually
happens. This is the exact shape expected:

{"headline": "One sentence naming the single most important thing.",
 "paragraphs": ["First paragraph of two or three sentences.",
                "Second paragraph of two or three sentences."],
 "actions": ["Do this first.", "Then this."]}
""".strip()


def _extract_json(content: str) -> Any:
    text = (content or "").strip()
    if not text:
        return None
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except Exception:
        pass
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except Exception:
            return None
    return None




def live_model(configured: str | None, *, fallback: str, context: str) -> str:
    """Refuse to send a request to a model the provider has withdrawn.

    A retired model is not a slow model or a bad model - it is an HTTP 410, and
    every LLM path in this codebase catches provider errors and serves a
    deterministic answer. That is the correct behaviour for a transient failure
    and exactly the wrong shape for a permanent one: the feature reports healthy,
    the pages render, and the only evidence is a warning in a log nobody reads.

    Checked at construction rather than at call time so the substitution is
    logged once at startup, where it will be seen, instead of on every request.
    """
    candidate = (configured or "").strip()
    retired = {str(name).strip() for name in (getattr(settings, "RETIRED_LLM_MODELS", None) or [])}
    if candidate and candidate in retired:
        logger.warning(
            "%s is configured for %s, which the provider has retired; using %s instead. "
            "Update the deployment's model setting - this substitution is a safety net, "
            "not the configuration.",
            candidate,
            context,
            fallback,
        )
        return fallback
    return candidate or fallback


grounded_narrator = GroundedNarrator()
