"""MCP server entry point."""

from __future__ import annotations

import logging
import os
import sys
from collections.abc import Callable
from functools import lru_cache
from typing import Any

from mcp.server.fastmcp import FastMCP

from .config import load_settings
from .service import OpenSearchReadService

logging.basicConfig(
    level=os.getenv("AWS_OPENSEARCH_MCP_LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    stream=sys.stderr,
)
LOGGER = logging.getLogger(__name__)

mcp = FastMCP(
    "AWS OpenSearch Read-Only",
    instructions=(
        "Use these tools to inspect Amazon OpenSearch Service safely. "
        "All cluster operations are read-only, AWS profiles and regions are allowlisted, "
        "search sizes are capped, and sensitive-looking fields are redacted."
    ),
    json_response=True,
)


@lru_cache(maxsize=1)
def service() -> OpenSearchReadService:
    return OpenSearchReadService(load_settings())


def call(operation: Callable[..., dict[str, Any]], *args: Any, **kwargs: Any) -> dict[str, Any]:
    try:
        return operation(*args, **kwargs)
    except Exception as exc:
        LOGGER.exception("OpenSearch MCP tool failed: %s", operation.__name__)
        return {
            "ok": False,
            "error_type": type(exc).__name__,
            "error": str(exc),
            "operation": operation.__name__,
        }


@mcp.tool()
def list_aws_profiles() -> dict[str, Any]:
    """List allowlisted AWS profiles, whether they exist locally, and allowed regions."""
    return call(service().list_profiles)


@mcp.tool()
def list_domains(profile: str, region: str) -> dict[str, Any]:
    """List Amazon OpenSearch Service domains visible to an allowlisted AWS profile."""
    return call(service().list_domains, profile, region)


@mcp.tool()
def get_domain_config(profile: str, region: str, domain: str) -> dict[str, Any]:
    """Read the managed-domain configuration, nodes, storage, networking and security posture."""
    return call(service().get_domain_config, profile, region, domain)


@mcp.tool()
def get_cluster_health(
    profile: str, region: str, domain: str, level: str = "cluster"
) -> dict[str, Any]:
    """Get OpenSearch cluster health at cluster, indices, or shards level."""
    return call(service().get_cluster_health, profile, region, domain, level)


@mcp.tool()
def get_cluster_stats(profile: str, region: str, domain: str) -> dict[str, Any]:
    """Get high-level cluster, node, shard, document and storage statistics."""
    return call(service().get_cluster_stats, profile, region, domain)


@mcp.tool()
def list_indices(
    profile: str, region: str, domain: str, index_pattern: str = "*"
) -> dict[str, Any]:
    """List matching indices ordered by storage size with health, shards and document counts."""
    return call(service().list_indices, profile, region, domain, index_pattern)


@mcp.tool()
def get_index_details(profile: str, region: str, domain: str, index: str) -> dict[str, Any]:
    """Read settings, mappings, aliases and operational stats for an index or safe pattern."""
    return call(service().get_index_details, profile, region, domain, index)


@mcp.tool()
def search_index(
    profile: str,
    region: str,
    domain: str,
    index: str,
    query: dict[str, Any],
    size: int = 20,
) -> dict[str, Any]:
    """Run a bounded read-only Query DSL search. Scripts and runtime mappings are blocked."""
    return call(service().search_index, profile, region, domain, index, query, size)


@mcp.tool()
def get_latest_documents(
    profile: str,
    region: str,
    domain: str,
    index: str,
    timestamp_field: str = "@timestamp",
    size: int = 10,
    lookback_hours: int = 0,
    source_fields: list[str] | None = None,
) -> dict[str, Any]:
    """Return newest documents sorted by a date field, optionally restricted by lookback hours."""
    return call(
        service().get_latest_documents,
        profile,
        region,
        domain,
        index,
        timestamp_field,
        size,
        lookback_hours,
        source_fields,
    )


@mcp.tool()
def get_field_mapping(
    profile: str, region: str, domain: str, index: str, field: str
) -> dict[str, Any]:
    """Inspect one field across matching index mappings and report mapping type conflicts."""
    return call(service().get_field_mapping, profile, region, domain, index, field)


@mcp.tool()
def get_field_count(profile: str, region: str, domain: str, index: str) -> dict[str, Any]:
    """Estimate mapped field counts and compare them with index.mapping.total_fields.limit."""
    return call(service().get_field_count, profile, region, domain, index)


@mcp.tool()
def get_shard_allocation(
    profile: str, region: str, domain: str, index_pattern: str = "*"
) -> dict[str, Any]:
    """List primary and replica shard states, nodes, sizes and unassigned reasons."""
    return call(service().get_shard_allocation, profile, region, domain, index_pattern)


@mcp.tool()
def explain_unassigned_shard(
    profile: str,
    region: str,
    domain: str,
    index: str | None = None,
    shard: int | None = None,
    primary: bool | None = None,
    include_yes_decisions: bool = False,
) -> dict[str, Any]:
    """Explain the first unassigned shard, or a specific shard when all shard fields are given."""
    return call(
        service().explain_unassigned_shard,
        profile,
        region,
        domain,
        index,
        shard,
        primary,
        include_yes_decisions,
    )


@mcp.tool()
def get_disk_allocation(profile: str, region: str, domain: str) -> dict[str, Any]:
    """Get per-node disk allocation and shard counts ordered by disk percentage."""
    return call(service().get_disk_allocation, profile, region, domain)


@mcp.tool()
def get_cluster_settings(
    profile: str, region: str, domain: str, include_defaults: bool = True
) -> dict[str, Any]:
    """Read transient, persistent, and optionally default cluster settings."""
    return call(service().get_cluster_settings, profile, region, domain, include_defaults)


@mcp.tool()
def get_indexing_stats(profile: str, region: str, domain: str, index: str = "*") -> dict[str, Any]:
    """Get document, storage, indexing, search, merge, refresh and segment statistics."""
    return call(service().get_indexing_stats, profile, region, domain, index)


@mcp.tool()
def get_pending_tasks(profile: str, region: str, domain: str) -> dict[str, Any]:
    """List pending cluster-manager tasks and their queue wait time."""
    return call(service().get_pending_tasks, profile, region, domain)


@mcp.tool()
def get_ingest_pipelines(profile: str, region: str, domain: str) -> dict[str, Any]:
    """Read all ingest pipeline definitions visible to the current AWS identity."""
    return call(service().get_ingest_pipelines, profile, region, domain)


@mcp.tool()
def diagnose_cluster(profile: str, region: str, domain: str) -> dict[str, Any]:
    """Generate an evidence-based read-only diagnosis for health, shards, disk and flood-stage blocks."""
    return call(service().diagnose_cluster, profile, region, domain)


@mcp.tool()
def diagnose_timestamp(
    profile: str,
    region: str,
    domain: str,
    index: str,
    timestamp_field: str = "@timestamp",
    sample_size: int = 5,
) -> dict[str, Any]:
    """Diagnose stale data by checking date mappings, min/max values, and newest/oldest samples."""
    return call(
        service().diagnose_timestamp,
        profile,
        region,
        domain,
        index,
        timestamp_field,
        sample_size,
    )


def main() -> None:
    transport = os.getenv("MCP_TRANSPORT", "stdio")
    mcp.run(transport=transport)


if __name__ == "__main__":
    main()
