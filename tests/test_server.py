from aws_opensearch_mcp.server import mcp


def test_expected_read_only_tools_are_registered():
    tools = set(mcp._tool_manager._tools)
    assert len(tools) == 20
    assert "diagnose_cluster" in tools
    assert "diagnose_timestamp" in tools
    assert "search_index" in tools
    assert all(not name.startswith(("delete", "update", "apply", "create")) for name in tools)
