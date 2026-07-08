"""Domain, index, mapping and search operations."""

from __future__ import annotations

from typing import Any

from .mappings import count_mapping_fields, extract_field_types
from .security import (
    clamp_lookback,
    clamp_size,
    prepare_search_body,
    validate_field_name,
    validate_index_pattern,
)


class IndexOperationsMixin:
    def list_profiles(self) -> dict[str, Any]:
        return self.result({"allowed_regions": list(self.settings.allowed_regions), "profiles": self.aws.available_profiles()})

    def list_domains(self, profile: str, region: str) -> dict[str, Any]:
        domains: list[dict[str, Any]] = []
        for name in self.aws.list_domains(profile, region):
            try:
                status = self.aws.describe_domain(profile, region, name)
                domains.append({
                    "domain": name,
                    "engine_version": status.get("EngineVersion"),
                    "processing": status.get("Processing"),
                    "upgrade_processing": status.get("UpgradeProcessing"),
                    "endpoint": self.aws.extract_endpoint(status),
                    "vpc": bool(status.get("VPCOptions")),
                })
            except Exception as exc:
                domains.append({"domain": name, "error": str(exc)})
        return self.result({"profile": profile, "region": region, "domains": domains})

    def get_domain_config(self, profile: str, region: str, domain: str) -> dict[str, Any]:
        status = self.aws.describe_domain(profile, region, domain)
        keys = {
            "DomainName": "domain_name", "ARN": "arn", "EngineVersion": "engine_version",
            "Created": "created", "Deleted": "deleted", "Processing": "processing",
            "UpgradeProcessing": "upgrade_processing", "ClusterConfig": "cluster_config",
            "EBSOptions": "ebs_options", "VPCOptions": "vpc_options",
            "SnapshotOptions": "snapshot_options", "EncryptionAtRestOptions": "encryption_at_rest",
            "NodeToNodeEncryptionOptions": "node_to_node_encryption",
            "AdvancedSecurityOptions": "advanced_security",
            "DomainEndpointOptions": "domain_endpoint_options",
            "ServiceSoftwareOptions": "service_software_options",
            "AutoTuneOptions": "auto_tune_options", "OffPeakWindowOptions": "off_peak_window_options",
        }
        selected = {target: status.get(source) for source, target in keys.items()}
        selected["endpoint"] = self.aws.extract_endpoint(status)
        return self.result(selected)

    def get_cluster_health(self, profile: str, region: str, domain: str, level: str = "cluster") -> dict[str, Any]:
        if level not in {"cluster", "indices", "shards"}:
            raise ValueError("level must be cluster, indices, or shards")
        with self.cluster(profile, region, domain) as client:
            data = self.request(client, "GET", "/_cluster/health", params={
                "level": level, "timeout": f"{self.settings.limits.request_timeout_seconds}s"
            })
        return self.result(data)

    def get_cluster_stats(self, profile: str, region: str, domain: str) -> dict[str, Any]:
        with self.cluster(profile, region, domain) as client:
            data = self.request(client, "GET", "/_cluster/stats")
        return self.result(data)

    def list_indices(self, profile: str, region: str, domain: str, index_pattern: str = "*") -> dict[str, Any]:
        pattern = validate_index_pattern(index_pattern)
        with self.cluster(profile, region, domain) as client:
            data = self.request(client, "GET", f"/_cat/indices/{pattern}", params={
                "format": "json", "bytes": "mb", "s": "store.size:desc",
                "h": "health,status,index,uuid,pri,rep,docs.count,docs.deleted,store.size,pri.store.size",
            })
        if isinstance(data, list):
            data = data[: self.settings.limits.max_cat_rows]
        return self.result(data)

    def get_index_details(self, profile: str, region: str, domain: str, index: str) -> dict[str, Any]:
        safe = validate_index_pattern(index)
        with self.cluster(profile, region, domain) as client:
            data = {
                "index": safe,
                "settings": self.request(client, "GET", f"/{safe}/_settings"),
                "mappings": self.request(client, "GET", f"/{safe}/_mapping"),
                "aliases": self.request(client, "GET", f"/{safe}/_alias"),
                "stats": self.request(client, "GET", f"/{safe}/_stats/docs,store,indexing,search,segments,merges,refresh", params={"level": "indices"}),
            }
        return self.result(data)

    def search_index(self, profile: str, region: str, domain: str, index: str, query: dict[str, Any], size: int = 20) -> dict[str, Any]:
        safe = validate_index_pattern(index)
        with self.cluster(profile, region, domain) as client:
            data = self.request(client, "POST", f"/{safe}/_search", body=prepare_search_body(query, size, self.settings))
        return self.result(data)

    def get_latest_documents(self, profile: str, region: str, domain: str, index: str, timestamp_field: str = "@timestamp", size: int = 10, lookback_hours: int = 0, source_fields: list[str] | None = None) -> dict[str, Any]:
        safe_index = validate_index_pattern(index)
        safe_field = validate_field_name(timestamp_field)
        hours = clamp_lookback(lookback_hours, self.settings)
        body: dict[str, Any] = {
            "size": clamp_size(size, self.settings),
            "sort": [{safe_field: {"order": "desc", "unmapped_type": "date"}}],
            "query": {"range": {safe_field: {"gte": f"now-{hours}h"}}} if hours else {"match_all": {}},
            "timeout": f"{self.settings.limits.request_timeout_seconds}s", "track_total_hits": False,
        }
        if source_fields:
            body["_source"] = [validate_field_name(field) for field in source_fields]
        with self.cluster(profile, region, domain) as client:
            data = self.request(client, "POST", f"/{safe_index}/_search", body=body)
        return self.result(data)

    def get_field_mapping(self, profile: str, region: str, domain: str, index: str, field: str) -> dict[str, Any]:
        safe_index, safe_field = validate_index_pattern(index), validate_field_name(field)
        with self.cluster(profile, region, domain) as client:
            mapping = self.request(client, "GET", f"/{safe_index}/_mapping/field/{safe_field}")
        return self.result({"field": safe_field, "types": extract_field_types(mapping, safe_field), "mapping": mapping})

    def get_field_count(self, profile: str, region: str, domain: str, index: str) -> dict[str, Any]:
        safe = validate_index_pattern(index)
        with self.cluster(profile, region, domain) as client:
            mappings = self.request(client, "GET", f"/{safe}/_mapping")
            settings = self.request(client, "GET", f"/{safe}/_settings/index.mapping.total_fields.limit")
        rows: list[dict[str, Any]] = []
        for name, payload in mappings.items():
            limit = int(settings.get(name, {}).get("settings", {}).get("index", {}).get("mapping", {}).get("total_fields", {}).get("limit", 1000))
            count = count_mapping_fields(payload)
            rows.append({"index": name, "field_count": count, "limit": limit, "usage_percent": round(count / limit * 100, 2) if limit else None})
        return self.result(sorted(rows, key=lambda row: row["field_count"], reverse=True))
