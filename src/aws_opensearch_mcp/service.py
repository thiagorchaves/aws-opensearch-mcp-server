"""Composed read-only OpenSearch service."""

from .service_base import OpenSearchServiceBase
from .service_cluster import ClusterOperationsMixin
from .service_diagnostics import DiagnosticOperationsMixin
from .service_indices import IndexOperationsMixin


class OpenSearchReadService(
    DiagnosticOperationsMixin,
    ClusterOperationsMixin,
    IndexOperationsMixin,
    OpenSearchServiceBase,
):
    """All read-only OpenSearch operations exposed by the MCP server."""
