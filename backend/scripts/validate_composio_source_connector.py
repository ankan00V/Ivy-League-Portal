#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup


OPPORTUNITY_TERMS = re.compile(
    r"\b(intern|internship|graduate|new grad|fresher|entry level|0-1|job|jobs|"
    r"opening|role|fellowship|hackathon|challenge|competition|apply)\b",
    re.IGNORECASE,
)

GENERIC_ANCHOR_TEXT = {
    "apply",
    "careers",
    "jobs",
    "learn more",
    "read more",
    "view all",
    "view details",
}


@dataclass
class FetchEvidence:
    url: str
    final_url: str = ""
    status_code: int | None = None
    content_type: str = ""
    elapsed_ms: float = 0.0
    error: str | None = None


@dataclass
class ApiEvidence:
    detected: bool = False
    record_count: int = 0
    sample_keys: list[str] = field(default_factory=list)
    sample_titles: list[str] = field(default_factory=list)


@dataclass
class DomEvidence:
    repeated_listing_count: int = 0
    selectors: list[str] = field(default_factory=list)
    sample_titles: list[str] = field(default_factory=list)


@dataclass
class ComposioEvidence:
    available: bool = False
    command: list[str] = field(default_factory=list)
    connected_toolkits: list[str] = field(default_factory=list)
    primary_tool_slugs: list[str] = field(default_factory=list)
    error: str | None = None


@dataclass
class ConnectorValidationReport:
    generated_at_epoch: float
    name: str
    url: str
    domain: str
    recommendation: str
    promotion_contract: str
    reasons: list[str]
    fetch: FetchEvidence
    api: ApiEvidence
    dom: DomEvidence
    composio: ComposioEvidence


Runner = Callable[[list[str]], subprocess.CompletedProcess[str]]


def _domain(url: str) -> str:
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    return host[4:] if host.startswith("www.") else host


def _iter_dicts(node: Any) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    if isinstance(node, dict):
        found.append(node)
        for value in node.values():
            found.extend(_iter_dicts(value))
    elif isinstance(node, list):
        for value in node:
            found.extend(_iter_dicts(value))
    return found


def _looks_like_listing_record(row: dict[str, Any]) -> bool:
    keys = {str(key).lower() for key in row}
    has_title = bool(keys & {"title", "name", "position", "role", "job_title"})
    has_url = bool(keys & {"url", "absolute_url", "apply_url", "application_url", "link"})
    text = " ".join(str(value) for value in row.values() if isinstance(value, (str, int, float)))
    return has_title and (has_url or bool(OPPORTUNITY_TERMS.search(text)))


def inspect_json_payload(payload: Any) -> ApiEvidence:
    rows = [row for row in _iter_dicts(payload) if _looks_like_listing_record(row)]
    sample = rows[:3]
    titles: list[str] = []
    for row in sample:
        for key in ("title", "name", "position", "role", "job_title"):
            value = row.get(key)
            if value:
                titles.append(str(value)[:140])
                break
    return ApiEvidence(
        detected=len(rows) >= 3,
        record_count=len(rows),
        sample_keys=sorted({str(key) for row in sample for key in row.keys()})[:24],
        sample_titles=titles,
    )


def _selector_signature(node: Any) -> str:
    classes = node.get("class") or []
    if classes:
        return f"{node.name}.{'.'.join(str(item) for item in classes[:3])}"
    data_attrs = [key for key in node.attrs if str(key).startswith("data-")]
    if data_attrs:
        return f"{node.name}[{data_attrs[0]}]"
    return str(node.name)


def inspect_html_payload(html: str, base_url: str) -> DomEvidence:
    soup = BeautifulSoup(html, "html.parser")
    grouped: dict[str, list[str]] = {}
    for anchor in soup.select("a[href]"):
        text = " ".join(anchor.get_text(" ", strip=True).split())
        href = str(anchor.get("href") or "")
        if not text or text.lower() in GENERIC_ANCHOR_TEXT:
            continue
        if not OPPORTUNITY_TERMS.search(f"{text} {href}"):
            continue
        parent = anchor.find_parent(["article", "li", "section", "div"]) or anchor
        signature = _selector_signature(parent)
        grouped.setdefault(signature, [])
        if text not in grouped[signature]:
            grouped[signature].append(text[:140])

    repeated = {selector: titles for selector, titles in grouped.items() if len(titles) >= 3}
    selectors = sorted(repeated, key=lambda key: len(repeated[key]), reverse=True)
    return DomEvidence(
        repeated_listing_count=sum(len(repeated[selector]) for selector in selectors),
        selectors=selectors[:5],
        sample_titles=[title for selector in selectors[:2] for title in repeated[selector][:3]][:6],
    )


def run_composio_search(name: str, url: str, toolkit: str | None, runner: Runner | None = None) -> ComposioEvidence:
    composio_path = shutil.which("composio")
    if not composio_path:
        return ComposioEvidence(error="composio CLI not found on PATH")

    query = f"{name} listings API jobs internships source connector {_domain(url)}"
    command = [composio_path, "search", query, "--limit", "5"]
    if toolkit:
        command.extend(["--toolkits", toolkit])

    run = runner or (lambda cmd: subprocess.run(cmd, capture_output=True, text=True, timeout=30, check=False))
    try:
        completed = run(command)
    except Exception as exc:
        return ComposioEvidence(available=True, command=command, error=str(exc))

    if completed.returncode != 0:
        return ComposioEvidence(
            available=True,
            command=command,
            error=(completed.stderr or completed.stdout or f"exit {completed.returncode}")[:1000],
        )

    try:
        payload = json.loads(completed.stdout or "{}")
    except json.JSONDecodeError:
        return ComposioEvidence(available=True, command=command, error="composio search returned non-JSON output")

    tool_slugs: list[str] = []
    for result in payload.get("results") or []:
        if isinstance(result, dict):
            tool_slugs.extend(str(item) for item in result.get("primary_tool_slugs") or [])
    return ComposioEvidence(
        available=True,
        command=command,
        connected_toolkits=[str(item) for item in payload.get("connected_toolkits") or []],
        primary_tool_slugs=sorted(set(tool_slugs))[:12],
    )


def validate_connector(
    *,
    name: str,
    url: str,
    toolkit: str | None = None,
    timeout_seconds: float = 20.0,
    runner: Runner | None = None,
) -> ConnectorValidationReport:
    started = time.perf_counter()
    reasons: list[str] = []
    fetch = FetchEvidence(url=url)
    api = ApiEvidence()
    dom = DomEvidence()

    try:
        response = requests.get(
            url,
            timeout=timeout_seconds,
            headers={
                "Accept": "application/json,text/html,application/xhtml+xml,*/*",
                "User-Agent": "VidyaVerseConnectorValidator/1.0",
            },
        )
        fetch.final_url = response.url
        fetch.status_code = response.status_code
        fetch.content_type = response.headers.get("content-type", "")
        fetch.elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
        response.raise_for_status()

        content_type = fetch.content_type.lower()
        if "json" in content_type or urlparse(fetch.final_url or url).path.endswith("/api"):
            api = inspect_json_payload(response.json())
        else:
            dom = inspect_html_payload(response.text, fetch.final_url or url)
    except Exception as exc:
        fetch.elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
        fetch.error = str(exc)
        reasons.append(f"fetch_failed:{exc}")

    composio = run_composio_search(name, url, toolkit, runner=runner)

    if api.detected:
        recommendation = "candidate_api_connector"
        promotion_contract = "api"
        reasons.append(f"json_listing_records:{api.record_count}")
    elif dom.repeated_listing_count >= 3:
        recommendation = "candidate_dom_connector"
        promotion_contract = "stable_dom"
        reasons.append(f"repeated_listing_dom:{dom.repeated_listing_count}")
    else:
        recommendation = "blocked_needs_dedicated_connector"
        promotion_contract = "none"
        if fetch.error is None:
            reasons.append("no_repeated_listing_cards_or_json_records")

    if composio.primary_tool_slugs:
        reasons.append("composio_tools_available")

    return ConnectorValidationReport(
        generated_at_epoch=time.time(),
        name=name,
        url=url,
        domain=_domain(fetch.final_url or url),
        recommendation=recommendation,
        promotion_contract=promotion_contract,
        reasons=reasons,
        fetch=fetch,
        api=api,
        dom=dom,
        composio=composio,
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate whether a discovered source has a promotable API or repeated listing DOM contract."
    )
    parser.add_argument("--name", required=True, help="Human-readable source name, e.g. Devfolio")
    parser.add_argument("--url", required=True, help="Candidate listing URL to probe")
    parser.add_argument("--toolkit", help="Optional Composio toolkit slug to search, e.g. github")
    parser.add_argument("--timeout-seconds", type=float, default=20.0)
    parser.add_argument("--output", type=Path, help="Optional JSON report path")
    args = parser.parse_args()

    report = validate_connector(
        name=args.name,
        url=args.url,
        toolkit=args.toolkit,
        timeout_seconds=max(3.0, args.timeout_seconds),
    )
    payload = asdict(report)
    text = json.dumps(payload, indent=2, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if report.recommendation != "blocked_needs_dedicated_connector" else 2


if __name__ == "__main__":
    raise SystemExit(main())
