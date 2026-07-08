"""Mapping inspection helpers."""

from __future__ import annotations

from typing import Any


def count_mapping_fields(mapping: dict[str, Any]) -> int:
    """Approximate index.mapping.total_fields by counting objects, leaves and multi-fields."""

    def count_properties(properties: dict[str, Any]) -> int:
        total = 0
        for definition in properties.values():
            total += 1
            fields = definition.get("fields", {}) if isinstance(definition, dict) else {}
            total += len(fields) if isinstance(fields, dict) else 0
            nested = definition.get("properties", {}) if isinstance(definition, dict) else {}
            if isinstance(nested, dict):
                total += count_properties(nested)
        return total

    root = mapping.get("mappings", mapping)
    properties = root.get("properties", {}) if isinstance(root, dict) else {}
    runtime = root.get("runtime", {}) if isinstance(root, dict) else {}
    aliases = root.get("_meta", {}) if isinstance(root, dict) else {}
    total = count_properties(properties) if isinstance(properties, dict) else 0
    total += len(runtime) if isinstance(runtime, dict) else 0
    # _meta is deliberately not counted; this assignment keeps the behavior explicit.
    _ = aliases
    return total


def extract_field_types(field_mapping_response: dict[str, Any], field: str) -> list[str]:
    types: set[str] = set()
    for index_data in field_mapping_response.values():
        mappings = index_data.get("mappings", {}) if isinstance(index_data, dict) else {}
        field_data = mappings.get(field, {}) if isinstance(mappings, dict) else {}
        if isinstance(field_data, dict) and field_data.get("type"):
            types.add(str(field_data["type"]))
    return sorted(types)
