from pathlib import Path

from aws_opensearch_mcp.config import load_settings


def test_default_profiles_include_telemetry():
    settings = load_settings()
    assert settings.allowed_profiles == ("ci", "qa", "prod", "telemetry")


def test_load_example_config(tmp_path: Path):
    config = tmp_path / "config.yaml"
    config.write_text(
        """
profiles:
  allowed: [ci, telemetry]
regions:
  allowed: [us-east-1]
limits:
  max_documents: 25
""",
        encoding="utf-8",
    )
    settings = load_settings(config)
    assert settings.allowed_profiles == ("ci", "telemetry")
    assert settings.limits.max_documents == 25
