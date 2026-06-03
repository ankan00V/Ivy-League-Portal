from __future__ import annotations

import math
import re
from collections import Counter
from datetime import timedelta
from typing import Any

from beanie.exceptions import CollectionWasNotInitialized

from app.core.time import utc_now
from app.models.opportunity import Opportunity


TECH_SKILLS = {
    "python", "java", "javascript", "typescript", "react", "next.js", "node.js", "express", "fastapi",
    "django", "flask", "spring", "go", "golang", "rust", "c++", "c#", "sql", "postgresql", "mysql",
    "mongodb", "redis", "clickhouse", "duckdb", "snowflake", "bigquery", "spark", "hadoop", "kafka",
    "airflow", "dbt", "tableau", "power bi", "excel", "pandas", "numpy", "scipy", "scikit-learn",
    "tensorflow", "pytorch", "keras", "xgboost", "lightgbm", "nlp", "computer vision", "opencv",
    "llm", "rag", "langchain", "llamaindex", "transformers", "hugging face", "openai", "mlops",
    "mlflow", "kubeflow", "docker", "kubernetes", "terraform", "ansible", "linux", "bash", "git",
    "github actions", "ci/cd", "aws", "azure", "gcp", "lambda", "s3", "ec2", "cloudflare",
    "vercel", "netlify", "html", "css", "tailwind", "sass", "material ui", "redux", "zustand",
    "graphql", "rest api", "grpc", "websocket", "oauth", "jwt", "cybersecurity", "networking",
    "blockchain", "solidity", "web3", "android", "kotlin", "swift", "ios", "flutter", "react native",
    "ui/ux", "figma", "product management", "analytics", "data analysis", "data engineering",
    "data science", "machine learning", "deep learning", "statistics", "a/b testing", "experimentation",
    "recommendation systems", "search", "ranking", "elasticsearch", "opensearch", "vector search",
    "faiss", "pinecone", "weaviate", "qdrant", "etl", "elt", "warehousing", "feature engineering",
    "backend", "frontend", "full stack", "devops", "site reliability", "sre", "observability",
    "prometheus", "grafana", "datadog", "sentry", "testing", "pytest", "playwright", "jest",
    "vitest", "cypress", "selenium", "api design", "system design", "distributed systems",
    "microservices", "event driven", "serverless", "security", "privacy", "compliance", "fintech",
    "edtech", "healthtech", "biotech", "robotics", "iot", "embedded", "computer networks",
    "operating systems", "compiler", "nlp engineering", "prompt engineering", "data visualization",
    "business intelligence", "crm", "salesforce", "marketing analytics", "growth", "seo", "content",
    "market research", "finance", "quant", "risk", "trading", "operations research", "linear algebra",
    "calculus", "probability", "research", "technical writing", "leadership", "communication",
}

QUALITY_WEIGHTS = {
    "title": 15,
    "company": 15,
    "apply_url": 20,
    "description": 15,
    "location": 10,
    "work_mode": 8,
    "stipend": 7,
    "deadline": 5,
    "tags": 5,
}

REMOTE_LOCATION_PATTERNS = {
    "wfh",
    "work from home",
    "remote",
    "remote india",
    "remote (india)",
    "anywhere",
}

LOCATION_ALIASES = {
    "bengaluru": "Bangalore, India",
    "bangalore": "Bangalore, India",
    "blr": "Bangalore, India",
    "mumbai": "Mumbai, India",
    "bombay": "Mumbai, India",
    "delhi": "Delhi NCR, India",
    "new delhi": "Delhi NCR, India",
    "gurgaon": "Gurugram, India",
    "gurugram": "Gurugram, India",
    "noida": "Noida, India",
    "hyderabad": "Hyderabad, India",
    "pune": "Pune, India",
    "chennai": "Chennai, India",
    "kolkata": "Kolkata, India",
    "ahmedabad": "Ahmedabad, India",
    "jaipur": "Jaipur, India",
}


def _text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _norm(value: Any) -> str:
    return _text(value).lower()


def _percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return round(ordered[0], 2)
    index = (len(ordered) - 1) * max(0.0, min(1.0, p))
    lower = int(index)
    upper = min(lower + 1, len(ordered) - 1)
    weight = index - lower
    return round(ordered[lower] * (1.0 - weight) + ordered[upper] * weight, 2)


class OpportunityQualityScorer:
    def normalize_location(self, location: Any, description: Any = "") -> tuple[str | None, str | None]:
        raw = _text(location)
        haystack = _norm(" ".join([raw, _text(description)]))
        compact = re.sub(r"[^a-z0-9]+", " ", raw.lower()).strip()
        if compact in REMOTE_LOCATION_PATTERNS or any(pattern in haystack for pattern in REMOTE_LOCATION_PATTERNS):
            return "India", "remote"
        if compact in LOCATION_ALIASES:
            return LOCATION_ALIASES[compact], None
        return raw or None, None

    def normalize_stipend(self, stipend: Any) -> dict[str, Any]:
        raw = _text(stipend)
        if not raw:
            return {}

        normalized = raw.lower().replace(",", "")
        currency = "INR" if any(token in normalized for token in ["₹", "rs", "inr"]) else None
        period = "monthly" if any(token in normalized for token in ["/month", "month", "monthly", "pm", "per month"]) else None
        if not period and any(token in normalized for token in ["/year", "year", "annual", "lpa"]):
            period = "yearly"

        values: list[int] = []
        for match in re.finditer(r"(?:₹|rs\.?|inr)?\s*(\d+(?:\.\d+)?)\s*(k|lpa|lakh|lakhs)?", normalized):
            amount = float(match.group(1))
            suffix = match.group(2) or ""
            if suffix == "k":
                amount *= 1000
            elif suffix in {"lpa", "lakh", "lakhs"}:
                amount *= 100000
                period = period or "yearly"
            if amount >= 100:
                values.append(int(round(amount)))

        if not values:
            return {}
        return {
            "stipend_min": min(values),
            "stipend_max": max(values),
            "stipend_currency": currency or "INR",
            "stipend_period": period or "monthly",
        }

    def normalize_duration_months(self, value: Any, description: Any = "") -> float | None:
        haystack = _norm(" ".join([_text(value), _text(description)]))
        match = re.search(r"\b(\d+(?:\.\d+)?)\s*(months?|mos?)\b", haystack)
        if match:
            return round(float(match.group(1)), 2)
        match = re.search(r"\b(\d+(?:\.\d+)?)\s*weeks?\b", haystack)
        if match:
            return round(float(match.group(1)) / 4.0, 2)
        return None

    def extract_tags(self, *, title: Any, description: Any, existing: list[str] | None = None) -> list[str]:
        tags = {_norm(item) for item in list(existing or []) if _norm(item)}
        haystack = f" {_norm(title)} {_norm(description)} "
        for skill in TECH_SKILLS:
            pattern = rf"(?<![a-z0-9+#.]){re.escape(skill)}(?![a-z0-9+#.])"
            if re.search(pattern, haystack):
                tags.add(skill)
        return sorted(tags)[:25]

    def normalize_payload(self, opportunity: Any) -> dict[str, Any]:
        description = getattr(opportunity, "description", None)
        location, inferred_work_mode = self.normalize_location(getattr(opportunity, "location", None), description)
        stipend_fields = self.normalize_stipend(getattr(opportunity, "stipend", None))
        tags = self.extract_tags(
            title=getattr(opportunity, "title", None),
            description=description,
            existing=list(getattr(opportunity, "tags", []) or []),
        )
        payload: dict[str, Any] = {
            "location": location,
            "tags": tags,
            "duration_months": self.normalize_duration_months(
                getattr(opportunity, "duration_months", None),
                description,
            ),
        }
        if inferred_work_mode and not _text(getattr(opportunity, "work_mode", None)):
            payload["work_mode"] = inferred_work_mode
        payload.update(stipend_fields)
        return payload

    def score_payload(self, opportunity: Any, normalized: dict[str, Any] | None = None) -> tuple[float, list[str]]:
        normalized = normalized or {}

        def present(field: str) -> bool:
            if field == "company":
                return bool(_text(getattr(opportunity, "university", None)))
            if field == "apply_url":
                return bool(_text(getattr(opportunity, "url", None)).startswith(("http://", "https://")))
            if field == "description":
                return len(_text(getattr(opportunity, "description", None))) >= 40
            if field == "tags":
                return bool(normalized.get("tags") or getattr(opportunity, "tags", None))
            value = normalized.get(field, getattr(opportunity, field, None))
            return bool(_text(value))

        score = 0.0
        missing: list[str] = []
        for field, weight in QUALITY_WEIGHTS.items():
            if present(field):
                score += float(weight)
            else:
                missing.append(field)
        return round(max(0.0, min(100.0, score)), 2), missing

    async def score_and_update(self, opportunity: Opportunity) -> Opportunity:
        normalized = self.normalize_payload(opportunity)
        score, missing = self.score_payload(opportunity, normalized)
        for field, value in normalized.items():
            if value is not None:
                setattr(opportunity, field, value)
        opportunity.quality_score = score
        opportunity.quality_missing_fields = missing
        opportunity.last_quality_run_at = utc_now()
        opportunity.updated_at = utc_now()
        await opportunity.save()
        return opportunity

    async def run_quality_pipeline(self, *, stale_days: int = 7, limit: int | None = None) -> dict[str, Any]:
        cutoff = utc_now() - timedelta(days=max(1, int(stale_days)))
        try:
            query = Opportunity.find_many(
                {
                    "$or": [
                        {"quality_score": None},
                        {"last_quality_run_at": None},
                        {"last_quality_run_at": {"$lt": cutoff}},
                    ]
                }
            ).sort("-updated_at")
            if limit is not None:
                query = query.limit(max(1, int(limit)))
            rows = await query.to_list()
        except CollectionWasNotInitialized:
            return {"status": "skipped", "reason": "collection_not_initialized", "processed": 0}

        before_scores = [
            float(row.quality_score)
            for row in rows
            if getattr(row, "quality_score", None) is not None and not math.isnan(float(row.quality_score))
        ]
        after_scores: list[float] = []
        missing_counter: Counter[str] = Counter()

        for row in rows:
            updated = await self.score_and_update(row)
            after_scores.append(float(updated.quality_score or 0.0))
            missing_counter.update(list(updated.quality_missing_fields or []))

        return {
            "status": "ok",
            "processed": len(rows),
            "score_distribution": {
                "p25": _percentile(after_scores, 0.25),
                "p50": _percentile(after_scores, 0.50),
                "p75": _percentile(after_scores, 0.75),
            },
            "top_missing_fields": [
                {"field": field, "count": count}
                for field, count in missing_counter.most_common(10)
            ],
            "improvement_delta": round(
                (sum(after_scores) / len(after_scores) if after_scores else 0.0)
                - (sum(before_scores) / len(before_scores) if before_scores else 0.0),
                2,
            ),
        }


opportunity_quality_scorer = OpportunityQualityScorer()
