"""AWS and signed OpenSearch client factories."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

import boto3
from botocore.exceptions import BotoCoreError, ClientError, ProfileNotFound
from opensearchpy import AWSV4SignerAuth, OpenSearch, RequestsHttpConnection

from .config import ProfileSettings, Settings
from .security import validate_domain, validate_profile_region


class AwsClientError(RuntimeError):
    """Normalized AWS/OpenSearch connection error."""


@dataclass(frozen=True)
class DomainTarget:
    profile: str
    region: str
    domain: str
    endpoint: str


class AwsSessionFactory:
    def __init__(self, settings: Settings):
        self.settings = settings

    def _base_session(self, profile: str, region: str) -> boto3.Session:
        validate_profile_region(self.settings, profile, region)
        try:
            return boto3.Session(profile_name=profile, region_name=region)
        except ProfileNotFound as exc:
            raise AwsClientError(str(exc)) from exc

    def _assumed_session(
        self,
        base: boto3.Session,
        profile: str,
        region: str,
        profile_settings: ProfileSettings,
    ) -> boto3.Session:
        if not profile_settings.role_arn:
            return base

        kwargs: dict[str, str] = {
            "RoleArn": profile_settings.role_arn,
            "RoleSessionName": f"aws-opensearch-mcp-{profile}",
        }
        if profile_settings.external_id:
            kwargs["ExternalId"] = profile_settings.external_id

        try:
            response = base.client("sts", region_name=region).assume_role(**kwargs)
        except (BotoCoreError, ClientError) as exc:
            raise AwsClientError(f"Could not assume role for profile '{profile}': {exc}") from exc

        credentials = response["Credentials"]
        return boto3.Session(
            aws_access_key_id=credentials["AccessKeyId"],
            aws_secret_access_key=credentials["SecretAccessKey"],
            aws_session_token=credentials["SessionToken"],
            region_name=region,
        )

    def session(self, profile: str, region: str) -> boto3.Session:
        base = self._base_session(profile, region)
        return self._assumed_session(
            base,
            profile,
            region,
            self.settings.for_profile(profile),
        )

    def available_profiles(self) -> list[dict[str, object]]:
        available = set(boto3.Session().available_profiles)
        return [
            {
                "profile": profile,
                "configured": True,
                "available_locally": profile in available,
                "read_only": self.settings.for_profile(profile).read_only,
                "assume_role": bool(self.settings.for_profile(profile).role_arn),
            }
            for profile in self.settings.allowed_profiles
        ]

    def control_client(self, profile: str, region: str):
        session = self.session(profile, region)
        try:
            return session.client("opensearch", region_name=region)
        except Exception:
            return session.client("es", region_name=region)

    def list_domains(self, profile: str, region: str) -> list[str]:
        client = self.control_client(profile, region)
        try:
            try:
                response = client.list_domain_names(EngineType="OpenSearch")
            except Exception:
                response = client.list_domain_names()
        except (BotoCoreError, ClientError) as exc:
            raise AwsClientError(f"Could not list domains: {exc}") from exc
        return sorted(item["DomainName"] for item in response.get("DomainNames", []))

    def describe_domain(self, profile: str, region: str, domain: str) -> dict:
        validate_domain(domain)
        client = self.control_client(profile, region)
        try:
            return client.describe_domain(DomainName=domain)["DomainStatus"]
        except (BotoCoreError, ClientError) as exc:
            raise AwsClientError(f"Could not describe domain '{domain}': {exc}") from exc

    @staticmethod
    def extract_endpoint(status: dict) -> str:
        endpoint = status.get("Endpoint")
        if not endpoint:
            endpoints = status.get("Endpoints", {}) or {}
            endpoint = endpoints.get("vpc") or endpoints.get("dualstack")
            if not endpoint and endpoints:
                endpoint = next(iter(endpoints.values()))
        if not endpoint:
            raise AwsClientError("Domain has no reachable endpoint in DescribeDomain response")
        if not endpoint.startswith("http"):
            endpoint = f"https://{endpoint}"
        return endpoint.rstrip("/")

    def target(self, profile: str, region: str, domain: str) -> DomainTarget:
        status = self.describe_domain(profile, region, domain)
        return DomainTarget(
            profile=profile,
            region=region,
            domain=domain,
            endpoint=self.extract_endpoint(status),
        )

    def open_search_client(self, target: DomainTarget) -> OpenSearch:
        session = self.session(target.profile, target.region)
        credentials = session.get_credentials()
        if credentials is None:
            raise AwsClientError(f"No AWS credentials available for profile '{target.profile}'")

        parsed = urlparse(target.endpoint)
        if not parsed.hostname:
            raise AwsClientError("Invalid OpenSearch endpoint")

        auth = AWSV4SignerAuth(credentials, target.region, "es")
        return OpenSearch(
            hosts=[{"host": parsed.hostname, "port": parsed.port or 443}],
            http_auth=auth,
            use_ssl=True,
            verify_certs=True,
            ssl_assert_hostname=True,
            ssl_show_warn=False,
            connection_class=RequestsHttpConnection,
            timeout=self.settings.limits.request_timeout_seconds,
            max_retries=2,
            retry_on_timeout=True,
            http_compress=True,
        )
