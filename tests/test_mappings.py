from aws_opensearch_mcp.mappings import count_mapping_fields


def test_count_mapping_fields_includes_objects_and_multifields():
    mapping = {
        "mappings": {
            "properties": {
                "message": {
                    "type": "text",
                    "fields": {"keyword": {"type": "keyword"}},
                },
                "http": {
                    "properties": {
                        "status_code": {"type": "integer"},
                    }
                },
            }
        }
    }
    assert count_mapping_fields(mapping) == 4
