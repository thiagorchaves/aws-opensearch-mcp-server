"""Input validation, query bounding and output redaction."""

from __future__ import annotations

import copy
import fnmatch
import json
import re
from typing import Any

from .config import Settings


class SecurityError(ValueError):
    """Raised when an input violates the server safety policy."""


_INDEX_PATTERN = re.compile(r"^[A-Za-z0-9@._*?,+-]+$")
_FIELD_PATTERN = re.compile(r"^[A-Za-z0-9@._-]+$")
_DOMAIN_PATTERN = re.compile(r"^[a-z][a-z0-9-]{2,27}$")

_BLOCKED_QUERY_KEYS = {
    "script",
    "script_fields",
    "runtime_mappings",
    "rescore",
    "stored_fields",
}


def validate_profile_region(settings: Settings, profile: str, region: str) -> None:
    if profile not in settings.allowed_profiles:
        raise SecurityError(
            f"AWS profile '{profile}' is not allowed. Allowed: {', '.join(settings.allowed_profiles)}"
        )
    if region not in settings.allowed_regions:
        raise SecurityError(
            f"AWS region '{region}' is not allowed. Allowed: {', '.join(settings.allowed_regions)}"
        )


def validate_domain(domain: str) -> str:
    if not _DOMAIN_PATTERN.fullmatch(domain):
        raise SecurityError("Invalid OpenSearch domain name")
    return domain


def validate_index_pattern(index: str) -> str:
    if not index or len(index) > 512:
        raise SecurityError("Index pattern is empty or too long")
    if "/" in index or ".." in index or "%" in index or not _INDEX_PATTERN.fullmatch(index):
        raise SecurityError("Invalid index or index pattern")
    return index


def validate_field_name(field: str) -> str:
    if not field or len(field) > 256 or not _FIELD_PATTERN.fullmatch(field):
        raise SecurityError("Invalid field name")
    return field


def clamp_size(size: int, settings: Settings) -> int:
    if size <= 0:
        raise SecurityError("size must be greater than zero")
    return min(size, settings.limits.max_documents)


def clamp_lookback(hours: int, settings: Settings) -> int:
    if hours < 0:
        raise SecurityError("lookback_hours cannot be negative")
    return min(hours, settings.limits.max_lookback_hours)


def _find_blocked_key(value: Any, path: str = "$") -> str | None:
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).lower() in _BLOCKED_QUERY_KEYS:
                return f"{path}.{key}"
            found = _find_blocked_key(child, f"{path}.{key}")
            if found:
                return found
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found = _find_blocked_key(child, f"{path}[{index}]")
            if found:
                return found
    return None


def _clamp_nested_sizes(value: Any, max_size: int) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if key in {"size", "shard_size"} and isinstance(child, int):
                value[key] = min(max(child, 0), max_size)
            else:
                _clamp_nested_sizes(child, max_size)
    elif isinstance(value, list):
        for child in value:
            _clamp_nested_sizes(child, max_size)


def prepare_search_body(query: dict[str, Any], size: int, settings: Settings) -> dict[str, Any]:
    if not isinstance(query, dict):
        raise SecurityError("query must be a JSON object")

    encoded = json.dumps(query, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(encoded) > settings.limits.max_query_bytes:
        raise SecurityError("Query exceeds max_query_bytes")

    blocked = _find_blocked_key(query)
    if blocked:
        raise SecurityError(f"Query contains blocked feature at {blocked}")

    body = copy.deepcopy(query)
    _clamp_nested_sizes(body, settings.limits.max_documents)
    body["size"] = clamp_size(size, settings)

    raw_from = body.get("from", 0)
    if not isinstance(raw_from, int) or raw_from < 0:
        raise SecurityError("from must be a non-negative integer")
    body["from"] = min(raw_from, 10_000)

    body["timeout"] = f"{settings.limits.request_timeout_seconds}s"
    raw_track_total_hits = body.get("track_total_hits", 10_000)
    if isinstance(raw_track_total_hits, bool):
        body["track_total_hits"] = raw_track_total_hits
    elif isinstance(raw_track_total_hits, int):
        body["track_total_hits"] = min(max(raw_track_total_hits, 0), 10_000)
    else:
        body["track_total_hits"] = 10_000
    return body


def redact(value: Any, patterns: tuple[str, ...]) -> Any:
    """Redact values whose key matches a configured case-insensitive pattern."""

    lowered_patterns = tuple(pattern.lower() for pattern in patterns)

    def matches_sensitive_key(key_text: str) -> bool:
        camel_split = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", key_text)
        normalized = camel_split.lower()
        parts = set(part for part in re.split(r"[^a-z0-9]+", normalized) if part)
        for pattern in lowered_patterns:
            if fnmatch.fnmatch(normalized, pattern) or normalized == pattern:
                return True
            pattern_parts = [part for part in re.split(r"[^a-z0-9]+", pattern) if part]
            if len(pattern_parts) == 1 and pattern_parts[0] in parts:
                return True
        return False

    def walk(node: Any) -> Any:
        if isinstance(node, dict):
            result: dict[str, Any] = {}
            for key, child in node.items():
                key_text = str(key)
                if matches_sensitive_key(key_text):
                    result[key_text] = "[REDACTED]"
                else:
                    result[key_text] = walk(child)
            return result
        if isinstance(node, list):
            return [walk(item) for item in node]
        return node

    return walk(value)


def bounded_response(value: Any, settings: Settings) -> dict[str, Any]:
    safe = redact(value, settings.redact_fields)
    encoded = json.dumps(safe, ensure_ascii=False, default=str).encode("utf-8")
    if len(encoded) <= settings.limits.max_response_bytes:
        return {"ok": True, "truncated": False, "data": safe}

    budget = max(settings.limits.max_response_bytes - 1_000, 1_000)
    preview = encoded[:budget].decode("utf-8", errors="ignore")
    return {
        "ok": True,
        "truncated": True,
        "original_bytes": len(encoded),
        "max_response_bytes": settings.limits.max_response_bytes,
        "preview_json": preview,
        "hint": "Narrow the index pattern, fields, time range, or requested tool.",
    }
