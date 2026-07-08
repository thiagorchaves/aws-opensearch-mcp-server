"""Configuration loading with conservative defaults."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


class ConfigError(ValueError):
    """Raised when MCP configuration is invalid."""


@dataclass(frozen=True)
class Limits:
    max_documents: int = 100
    max_query_bytes: int = 100_000
    max_response_bytes: int = 2_000_000
    request_timeout_seconds: int = 20
    max_lookback_hours: int = 24 * 31
    max_cat_rows: int = 5_000


@dataclass(frozen=True)
class ProfileSettings:
    read_only: bool = True
    role_arn: str | None = None
    external_id: str | None = None


@dataclass(frozen=True)
class Settings:
    allowed_profiles: tuple[str, ...] = ("ci", "qa", "prod", "telemetry")
    allowed_regions: tuple[str, ...] = ("us-east-1", "us-east-2")
    profile_settings: dict[str, ProfileSettings] = field(default_factory=dict)
    limits: Limits = field(default_factory=Limits)
    redact_fields: tuple[str, ...] = (
        "authorization",
        "password",
        "passwd",
        "secret",
        "secret_key",
        "access_key",
        "api_key",
        "token",
        "refresh_token",
        "session_token",
        "cookie",
        "set-cookie",
    )

    def for_profile(self, profile: str) -> ProfileSettings:
        return self.profile_settings.get(profile, ProfileSettings())


def _positive_int(value: Any, name: str, default: int) -> int:
    if value is None:
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"{name} must be an integer") from exc
    if parsed <= 0:
        raise ConfigError(f"{name} must be greater than zero")
    return parsed


def _string_tuple(value: Any, name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    if value is None:
        return default
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ConfigError(f"{name} must be a list of strings")
    cleaned = tuple(dict.fromkeys(item.strip() for item in value if item.strip()))
    if not cleaned:
        raise ConfigError(f"{name} cannot be empty")
    return cleaned


def load_settings(path: str | Path | None = None) -> Settings:
    """Load settings from YAML, or return safe defaults when no file exists."""

    configured_path = path or os.getenv("AWS_OPENSEARCH_MCP_CONFIG")
    if not configured_path:
        local_path = Path.cwd() / "config.yaml"
        configured_path = local_path if local_path.exists() else None

    data: dict[str, Any] = {}
    if configured_path:
        file_path = Path(configured_path).expanduser().resolve()
        if not file_path.exists():
            raise ConfigError(f"Configuration file does not exist: {file_path}")
        loaded = yaml.safe_load(file_path.read_text(encoding="utf-8"))
        if loaded is not None and not isinstance(loaded, dict):
            raise ConfigError("Configuration root must be a YAML object")
        data = loaded or {}

    default = Settings()
    profiles_data = data.get("profiles", {}) or {}
    regions_data = data.get("regions", {}) or {}
    limits_data = data.get("limits", {}) or {}

    allowed_profiles = _string_tuple(
        profiles_data.get("allowed"), "profiles.allowed", default.allowed_profiles
    )
    allowed_regions = _string_tuple(
        regions_data.get("allowed"), "regions.allowed", default.allowed_regions
    )

    raw_profile_settings = profiles_data.get("settings", {}) or {}
    if not isinstance(raw_profile_settings, dict):
        raise ConfigError("profiles.settings must be an object")

    profile_settings: dict[str, ProfileSettings] = {}
    for profile, raw in raw_profile_settings.items():
        if profile not in allowed_profiles:
            raise ConfigError(f"Profile settings defined for non-allowed profile: {profile}")
        raw = raw or {}
        if not isinstance(raw, dict):
            raise ConfigError(f"profiles.settings.{profile} must be an object")
        profile_settings[profile] = ProfileSettings(
            read_only=bool(raw.get("read_only", True)),
            role_arn=raw.get("role_arn"),
            external_id=raw.get("external_id"),
        )

    limits = Limits(
        max_documents=_positive_int(
            limits_data.get("max_documents"),
            "limits.max_documents",
            default.limits.max_documents,
        ),
        max_query_bytes=_positive_int(
            limits_data.get("max_query_bytes"),
            "limits.max_query_bytes",
            default.limits.max_query_bytes,
        ),
        max_response_bytes=_positive_int(
            limits_data.get("max_response_bytes"),
            "limits.max_response_bytes",
            default.limits.max_response_bytes,
        ),
        request_timeout_seconds=_positive_int(
            limits_data.get("request_timeout_seconds"),
            "limits.request_timeout_seconds",
            default.limits.request_timeout_seconds,
        ),
        max_lookback_hours=_positive_int(
            limits_data.get("max_lookback_hours"),
            "limits.max_lookback_hours",
            default.limits.max_lookback_hours,
        ),
        max_cat_rows=_positive_int(
            limits_data.get("max_cat_rows"),
            "limits.max_cat_rows",
            default.limits.max_cat_rows,
        ),
    )

    redact_fields = _string_tuple(data.get("redact_fields"), "redact_fields", default.redact_fields)

    return Settings(
        allowed_profiles=allowed_profiles,
        allowed_regions=allowed_regions,
        profile_settings=profile_settings,
        limits=limits,
        redact_fields=redact_fields,
    )
