"""Shard, allocation, settings and ingest operations."""

from __future__ import annotations

from typing import Any

from .security import validate_index_pattern


class ClusterOperationsMixin:
    def get_shard_allocation(self, profile: str, region: str, domain: str, index_pattern: str = "*") -> dict[str, Any]:
        pattern = validate_index_pattern(index_pattern)
        with self.cluster(profile, region, domain) as client:
            data = self.request(client, "GET", f"/_cat/shards/{pattern}", params={
                "format": "json", "bytes": "mb", "s": "state,index,shard,prirep",
                "h": "index,shard,prirep,state,docs,store,ip,node,unassigned.reason",
            })
        if isinstance(data, list):
            data = data[: self.settings.limits.max_cat_rows]
        return self.result(data)

    def explain_unassigned_shard(self, profile: str, region: str, domain: str, index: str | None = None, shard: int | None = None, primary: bool | None = None, include_yes_decisions: bool = False) -> dict[str, Any]:
        supplied = [index is not None, shard is not None, primary is not None]
        if any(supplied) and not all(supplied):
            raise ValueError("index, shard and primary must be supplied together")
        body = None
        if all(supplied):
            body = {"index": validate_index_pattern(str(index)), "shard": int(shard), "primary": bool(primary)}
        with self.cluster(profile, region, domain) as client:
            data = self.request(client, "POST", "/_cluster/allocation/explain", params={"include_yes_decisions": str(include_yes_decisions).lower()}, body=body)
        return self.result(data)

    def get_disk_allocation(self, profile: str, region: str, domain: str) -> dict[str, Any]:
        with self.cluster(profile, region, domain) as client:
            data = self.request(client, "GET", "/_cat/allocation", params={
                "format": "json", "bytes": "gb", "s": "disk.percent:desc",
                "h": "shards,disk.indices,disk.used,disk.avail,disk.total,disk.percent,host,ip,node",
            })
        return self.result(data)

    def get_cluster_settings(self, profile: str, region: str, domain: str, include_defaults: bool = True) -> dict[str, Any]:
        with self.cluster(profile, region, domain) as client:
            data = self.request(client, "GET", "/_cluster/settings", params={"include_defaults": str(include_defaults).lower(), "flat_settings": "false"})
        return self.result(data)

    def get_indexing_stats(self, profile: str, region: str, domain: str, index: str = "*") -> dict[str, Any]:
        safe = validate_index_pattern(index)
        with self.cluster(profile, region, domain) as client:
            data = self.request(client, "GET", f"/{safe}/_stats/docs,store,indexing,search,segments,merges,refresh", params={"level": "indices"})
        return self.result(data)

    def get_pending_tasks(self, profile: str, region: str, domain: str) -> dict[str, Any]:
        with self.cluster(profile, region, domain) as client:
            data = self.request(client, "GET", "/_cluster/pending_tasks")
        return self.result(data)

    def get_ingest_pipelines(self, profile: str, region: str, domain: str) -> dict[str, Any]:
        with self.cluster(profile, region, domain) as client:
            data = self.request(client, "GET", "/_ingest/pipeline")
        return self.result(data)
