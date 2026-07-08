"""Shared primitives for read-only OpenSearch services."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from opensearchpy import OpenSearch

from .aws_clients import AwsSessionFactory
from .config import Settings
from .security import bounded_response, validate_domain, validate_profile_region

LOGGER = logging.getLogger(__name__)


class OpenSearchServiceBase:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.aws = AwsSessionFactory(settings)

    def result(self, data: Any) -> dict[str, Any]:
        return bounded_response(data, self.settings)

    @contextmanager
    def cluster(self, profile: str, region: str, domain: str) -> Iterator[OpenSearch]:
        validate_profile_region(self.settings, profile, region)
        validate_domain(domain)
        client = self.aws.open_search_client(self.aws.target(profile, region, domain))
        try:
            yield client
        finally:
            try:
                client.close()
            except Exception:
                LOGGER.debug("Ignoring OpenSearch client close error", exc_info=True)

    @staticmethod
    def request(
        client: OpenSearch,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
    ) -> Any:
        return client.transport.perform_request(method, path, params=params, body=body)
