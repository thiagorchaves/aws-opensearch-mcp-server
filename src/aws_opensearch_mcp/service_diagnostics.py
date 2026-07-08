"""Evidence-based cluster and timestamp diagnostics."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .mappings import extract_field_types
from .security import clamp_size, validate_field_name, validate_index_pattern


class DiagnosticOperationsMixin:
    def diagnose_cluster(self, profile: str, region: str, domain: str) -> dict[str, Any]:
        with self.cluster(profile, region, domain) as client:
            health = self.request(client, "GET", "/_cluster/health")
            allocation = self.request(client, "GET", "/_cat/allocation", params={"format": "json", "s": "disk.percent:desc"})
            indices = self.request(client, "GET", "/_cat/indices", params={"format": "json", "bytes": "mb", "s": "store.size:desc"})
            pending = self.request(client, "GET", "/_cluster/pending_tasks")
            blocked = self.request(client, "GET", "/*/_settings/index.blocks.read_only_allow_delete", params={"flat_settings": "true", "expand_wildcards": "all"})

        findings: list[dict[str, str]] = []
        status = str(health.get("status", "unknown")).lower()
        if status in {"yellow", "red"}:
            findings.append({"severity": "critical" if status == "red" else "warning", "code": "cluster_health", "message": f"Cluster health is {status}."})
        unassigned = int(health.get("unassigned_shards", 0) or 0)
        if unassigned:
            findings.append({"severity": "high", "code": "unassigned_shards", "message": f"Cluster has {unassigned} unassigned shard(s)."})
        tasks = pending.get("tasks", []) if isinstance(pending, dict) else []
        if tasks:
            findings.append({"severity": "warning", "code": "pending_cluster_tasks", "message": f"Cluster has {len(tasks)} pending task(s)."})

        max_disk, max_disk_node = 0, None
        for row in allocation if isinstance(allocation, list) else []:
            try:
                percent = int(float(str(row.get("disk.percent", "0")).replace("%", "")))
            except ValueError:
                continue
            if percent > max_disk:
                max_disk, max_disk_node = percent, row.get("node")
        if max_disk >= 85:
            severity = "critical" if max_disk >= 95 else "high" if max_disk >= 90 else "warning"
            findings.append({"severity": severity, "code": "disk_watermark_risk", "message": f"Highest node disk usage is {max_disk}% on {max_disk_node}."})

        blocked_indices = [
            name for name, payload in blocked.items()
            if str(payload.get("settings", {}).get("index.blocks.read_only_allow_delete", "")).lower() == "true"
        ] if isinstance(blocked, dict) else []
        if blocked_indices:
            findings.append({"severity": "high", "code": "read_only_allow_delete", "message": f"{len(blocked_indices)} index(es) have the flood-stage block."})
        if not findings:
            findings.append({"severity": "info", "code": "no_immediate_issue", "message": "No immediate health, shard, pending-task, or disk issue was detected."})

        recommendations: list[str] = []
        codes = {item["code"] for item in findings}
        if "unassigned_shards" in codes:
            recommendations.append("Run explain_unassigned_shard for the first unassigned shard.")
        if "disk_watermark_risk" in codes:
            recommendations.append("Review largest indices, retention, replicas and storage capacity.")
        if "read_only_allow_delete" in codes:
            recommendations.append("Free disk space before removing any flood-stage index block.")

        return self.result({
            "target": {"profile": profile, "region": region, "domain": domain},
            "summary": {
                "status": status, "nodes": health.get("number_of_nodes"),
                "data_nodes": health.get("number_of_data_nodes"), "active_shards": health.get("active_shards"),
                "unassigned_shards": unassigned, "pending_tasks": len(tasks),
                "max_disk_percent": max_disk, "blocked_indices": blocked_indices,
            },
            "findings": findings, "recommendations": recommendations,
            "evidence": {"health": health, "disk_allocation": allocation, "largest_indices": indices[:20] if isinstance(indices, list) else indices, "pending_tasks": pending},
        })

    @staticmethod
    def _parse_timestamp(value: Any) -> datetime | None:
        if isinstance(value, (int, float)):
            seconds = value / 1000 if value > 10_000_000_000 else value
            try:
                return datetime.fromtimestamp(seconds, tz=timezone.utc)
            except (OverflowError, OSError, ValueError):
                return None
        if not isinstance(value, str):
            return None
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)

    def diagnose_timestamp(self, profile: str, region: str, domain: str, index: str, timestamp_field: str = "@timestamp", sample_size: int = 5) -> dict[str, Any]:
        safe_index, safe_field = validate_index_pattern(index), validate_field_name(timestamp_field)
        safe_size = clamp_size(sample_size, self.settings)
        with self.cluster(profile, region, domain) as client:
            mapping = self.request(client, "GET", f"/{safe_index}/_mapping/field/{safe_field}")
            aggregate = self.request(client, "POST", f"/{safe_index}/_search", body={
                "size": 0, "timeout": f"{self.settings.limits.request_timeout_seconds}s",
                "query": {"exists": {"field": safe_field}},
                "aggs": {
                    "minimum": {"min": {"field": safe_field}},
                    "maximum": {"max": {"field": safe_field}},
                    "documents_with_timestamp": {"value_count": {"field": safe_field}},
                },
            })
            samples: dict[str, Any] = {}
            for direction in ("desc", "asc"):
                samples[direction] = self.request(client, "POST", f"/{safe_index}/_search", body={
                    "size": safe_size, "timeout": f"{self.settings.limits.request_timeout_seconds}s",
                    "query": {"exists": {"field": safe_field}},
                    "sort": [{safe_field: {"order": direction, "unmapped_type": "date"}}],
                })

        aggs = aggregate.get("aggregations", {}) if isinstance(aggregate, dict) else {}
        minimum = aggs.get("minimum", {}).get("value_as_string") or aggs.get("minimum", {}).get("value")
        maximum = aggs.get("maximum", {}).get("value_as_string") or aggs.get("maximum", {}).get("value")
        maximum_dt = self._parse_timestamp(maximum)
        age_hours = round((datetime.now(timezone.utc) - maximum_dt).total_seconds() / 3600, 2) if maximum_dt else None
        types = extract_field_types(mapping, safe_field)
        findings: list[dict[str, str]] = []
        if not types:
            findings.append({"severity": "critical", "code": "timestamp_field_missing", "message": f"Field '{safe_field}' was not found."})
        elif any(field_type not in {"date", "date_nanos"} for field_type in types):
            findings.append({"severity": "high", "code": "timestamp_not_date", "message": f"Field types: {', '.join(types)}."})
        if age_hours is not None and age_hours > 24:
            findings.append({"severity": "warning", "code": "stale_latest_document", "message": f"Newest timestamp is approximately {age_hours} hours old."})
        if not findings:
            findings.append({"severity": "info", "code": "timestamp_looks_current", "message": "Timestamp mapping and newest value look healthy."})

        return self.result({
            "target": {"profile": profile, "region": region, "domain": domain, "index": safe_index},
            "timestamp_field": safe_field, "mapping_types": types,
            "minimum_timestamp": minimum, "maximum_timestamp": maximum, "maximum_age_hours": age_hours,
            "documents_with_timestamp": aggs.get("documents_with_timestamp", {}).get("value"),
            "findings": findings, "newest_documents": samples["desc"], "oldest_documents": samples["asc"], "mapping": mapping,
        })
