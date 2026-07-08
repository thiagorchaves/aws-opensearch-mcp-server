import pytest

from aws_opensearch_mcp.config import Settings
from aws_opensearch_mcp.security import (
    SecurityError,
    bounded_response,
    prepare_search_body,
    validate_index_pattern,
)


def test_search_size_is_capped():
    body = prepare_search_body({"query": {"match_all": {}}}, 9999, Settings())
    assert body["size"] == 100
    assert body["timeout"] == "20s"


def test_scripts_are_blocked():
    with pytest.raises(SecurityError):
        prepare_search_body(
            {"query": {"script": {"script": "return true"}}},
            10,
            Settings(),
        )


def test_index_path_injection_is_blocked():
    with pytest.raises(SecurityError):
        validate_index_pattern("logs/_delete_by_query")


def test_sensitive_fields_are_redacted():
    response = bounded_response(
        {"user": "thiago", "api_token": "secret-value"},
        Settings(),
    )
    assert response["data"]["api_token"] == "[REDACTED]"


def test_nested_sizes_and_pagination_are_capped():
    body = prepare_search_body(
        {
            "from": 999999,
            "aggs": {"services": {"terms": {"field": "service", "size": 50000}}},
        },
        10,
        Settings(),
    )
    assert body["from"] == 10000
    assert body["aggs"]["services"]["terms"]["size"] == 100


def test_tokenizer_is_not_redacted():
    response = bounded_response(
        {"tokenizer": "standard", "sessionToken": "secret-value"},
        Settings(),
    )
    assert response["data"]["tokenizer"] == "standard"
    assert response["data"]["sessionToken"] == "[REDACTED]"
