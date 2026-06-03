from __future__ import annotations

import statistics
from datetime import datetime, timedelta
from typing import Any

from beanie.exceptions import CollectionWasNotInitialized

from app.core.time import as_utc_aware, utc_now
from app.models.scraper_run_log import ScraperRunLog


def _parse_report_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return as_utc_aware(value)
    candidate = str(value or "").strip()
    if not candidate:
        return None
    try:
        return as_utc_aware(datetime.fromisoformat(candidate.replace("Z", "+00:00")))
    except Exception:
        return None


def _status_bucket(value: str | None) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"success", "ok"}:
        return "success"
    if normalized in {"partial", "partial_success", "degraded"}:
        return "partial"
    return "failed"


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return round(ordered[0], 2)
    index = (len(ordered) - 1) * percentile
    lower = int(index)
    upper = min(lower + 1, len(ordered) - 1)
    if lower == upper:
        return round(ordered[lower], 2)
    weight = index - lower
    return round(ordered[lower] * (1 - weight) + ordered[upper] * weight, 2)


class ScraperHealthService:
    async def persist_report(self, report: dict[str, Any]) -> list[ScraperRunLog]:
        run_start = _parse_report_datetime(report.get("started_at")) or utc_now()
        run_end = _parse_report_datetime(report.get("finished_at")) or utc_now()
        logs: list[ScraperRunLog] = []

        for source in list(report.get("sources") or []):
            source_name = str(source.get("source") or "unknown").strip().lower() or "unknown"
            errors = [str(item) for item in list(source.get("errors") or []) if str(item).strip()]
            fetched = max(0, int(source.get("fetched") or 0))
            parsed = max(0, int(source.get("parsed") or fetched))
            inserted = max(0, int(source.get("inserted") or 0))
            updated = max(0, int(source.get("updated") or 0))
            failed = max(0, int(source.get("failed") or 0))
            deduplicated = max(0, int(source.get("deduplicated") or max(0, fetched - parsed)))
            status = _status_bucket("failed" if errors and fetched == 0 else source.get("status") or report.get("status"))
            parse_error_count = max(failed, int(source.get("parse_error_count") or 0), len(errors))
            parse_times = [float(item) for item in list(source.get("parse_times_ms") or []) if item is not None]
            if not parse_times and fetched > 0:
                duration_ms = float(source.get("fetch_duration_ms") or 0.0) + float(source.get("upsert_duration_ms") or 0.0)
                if duration_ms > 0:
                    parse_times = [duration_ms / fetched]

            log = ScraperRunLog(
                source_name=source_name,
                run_start=run_start,
                run_end=run_end,
                status=status,  # type: ignore[arg-type]
                items_fetched=fetched,
                items_parsed=parsed,
                items_inserted=inserted,
                items_updated=updated,
                items_deduplicated=deduplicated,
                parse_error_count=parse_error_count,
                error_samples=[
                    {"message": message[:500], "source": source_name}
                    for message in errors[-5:]
                ],
                p50_parse_time_ms=_percentile(parse_times, 0.50),
                p95_parse_time_ms=_percentile(parse_times, 0.95),
                avg_trust_score=(
                    round(float(source.get("avg_trust_score")), 2)
                    if source.get("avg_trust_score") is not None
                    else None
                ),
                silent_failure=bool(fetched > 0 and inserted == 0 and updated == 0 and not errors),
            )
            await log.insert()
            logs.append(log)

        return logs

    async def source_health(self, *, window_days: int = 7) -> dict[str, Any]:
        now = utc_now()
        cutoff = now - timedelta(days=max(1, int(window_days)))
        try:
            logs = await ScraperRunLog.find_many({"run_end": {"$gte": cutoff}}).sort("-run_end").to_list()
        except CollectionWasNotInitialized:
            return {
                "summary": {
                    "total_sources": 0,
                    "green_count": 0,
                    "yellow_count": 0,
                    "red_count": 0,
                },
                "sources": [],
            }

        by_source: dict[str, list[ScraperRunLog]] = {}
        for log in logs:
            by_source.setdefault(str(log.source_name or "unknown"), []).append(log)

        rows: list[dict[str, Any]] = []
        for source_name, source_logs in sorted(by_source.items()):
            latest = max(source_logs, key=lambda item: item.run_end)
            total_runs = max(1, len(source_logs))
            success_runs = sum(1 for item in source_logs if item.status == "success")
            partial_runs = sum(1 for item in source_logs if item.status == "partial")
            total_fetched = sum(int(item.items_fetched or 0) for item in source_logs)
            total_inserted = sum(int(item.items_inserted or 0) for item in source_logs)
            total_updated = sum(int(item.items_updated or 0) for item in source_logs)
            parse_errors = sum(int(item.parse_error_count or 0) for item in source_logs)
            parsed = sum(int(item.items_parsed or 0) for item in source_logs)
            success_rate = (success_runs + partial_runs * 0.5) / total_runs
            parse_error_rate = parse_errors / max(1, parsed + parse_errors)
            avg_items_per_run = total_inserted / total_runs
            avg_daily_yield = total_inserted / max(1.0, float(window_days))
            latest_end = as_utc_aware(latest.run_end) or now
            staleness_hours = max(0.0, (now - latest_end).total_seconds() / 3600.0)

            success_component = success_rate * 45.0
            parse_component = max(0.0, 1.0 - parse_error_rate) * 25.0
            yield_component = min(1.0, avg_items_per_run / 5.0) * 20.0
            staleness_component = max(0.0, 1.0 - min(staleness_hours, 72.0) / 72.0) * 10.0
            health_score = round(success_component + parse_component + yield_component + staleness_component, 1)

            if health_score < 40:
                health_status = "RED"
            elif health_score <= 70:
                health_status = "YELLOW"
            else:
                health_status = "GREEN"

            consecutive_failures = 0
            for item in sorted(source_logs, key=lambda row: row.run_end, reverse=True):
                if item.status == "failed" or item.silent_failure:
                    consecutive_failures += 1
                else:
                    break

            p50_values = [float(item.p50_parse_time_ms) for item in source_logs if item.p50_parse_time_ms is not None]
            p95_values = [float(item.p95_parse_time_ms) for item in source_logs if item.p95_parse_time_ms is not None]
            trust_values = [float(item.avg_trust_score) for item in source_logs if item.avg_trust_score is not None]

            rows.append(
                {
                    "source": source_name,
                    "health_score": health_score,
                    "health_status": health_status,
                    "last_run": latest.run_end.isoformat(),
                    "avg_daily_yield": round(avg_daily_yield, 2),
                    "consecutive_failures": consecutive_failures,
                    "silent_failures": sum(1 for item in source_logs if item.silent_failure),
                    "success_rate": round(success_rate, 3),
                    "parse_error_rate": round(parse_error_rate, 3),
                    "avg_items_per_run": round(avg_items_per_run, 2),
                    "items_fetched": total_fetched,
                    "items_inserted": total_inserted,
                    "items_updated": total_updated,
                    "p50_parse_time_ms": round(statistics.mean(p50_values), 2) if p50_values else None,
                    "p95_parse_time_ms": round(statistics.mean(p95_values), 2) if p95_values else None,
                    "avg_trust_score": round(statistics.mean(trust_values), 2) if trust_values else None,
                    "staleness_hours": round(staleness_hours, 2),
                    "latest_errors": list(latest.error_samples or []),
                }
            )

        summary = {
            "total_sources": len(rows),
            "green_count": sum(1 for row in rows if row["health_status"] == "GREEN"),
            "yellow_count": sum(1 for row in rows if row["health_status"] == "YELLOW"),
            "red_count": sum(1 for row in rows if row["health_status"] == "RED"),
        }
        return {"summary": summary, "sources": rows}

    async def unhealthy_sources(self) -> list[dict[str, Any]]:
        health = await self.source_health()
        return [
            row
            for row in list(health.get("sources") or [])
            if str(row.get("health_status") or "").upper() in {"RED", "YELLOW"}
        ]

    async def red_sources_for_24h(self) -> list[dict[str, Any]]:
        now = utc_now()
        unhealthy = await self.unhealthy_sources()
        return [
            row
            for row in unhealthy
            if str(row.get("health_status") or "").upper() == "RED"
            and float(row.get("staleness_hours") or 0.0) >= 24.0
        ]


scraper_health_service = ScraperHealthService()
