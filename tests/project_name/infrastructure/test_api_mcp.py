"""Actual FastAPI requests and MCP tool registration without live LLM/mail services."""

import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from config.application import AppConfig
from project_name.api import create_app
from project_name.application import Runtime
from project_name.mcp_server import create_server


def test_api_auth_health_and_path_containment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EW_API_TOKEN", "test-token")
    config = AppConfig.model_validate(
        {
            "tracks": {"track2_enabled": False},
            "storage": {"sqlite_path": str(tmp_path / "db.sqlite3")},
            "extraction": {"output_directory": str(tmp_path / "raw")},
        }
    )
    runtime = Runtime(config, tmp_path / "config.yaml")
    with TestClient(create_app(runtime)) as client:
        assert client.get("/health").json()["status"] == "ready"
        assert client.get("/stats").status_code == 401
        assert (
            client.get("/stats", headers={"Authorization": "Bearer test-token"}).json()[
                "email_count"
            ]
            == 0
        )
        assert (
            client.post(
                "/ingest",
                json={"manifest": "../outside.jsonl"},
                headers={"Authorization": "Bearer test-token"},
            ).status_code
            == 400
        )


def test_mcp_tools_register_and_execute_metadata_sql(tmp_path: Path) -> None:
    config = AppConfig.model_validate(
        {
            "tracks": {"track2_enabled": False},
            "storage": {"sqlite_path": str(tmp_path / "db.sqlite3")},
        }
    )
    server = create_server(Runtime(config, tmp_path / "config.yaml"))
    tools = asyncio.run(server.list_tools())
    assert {tool.name for tool in tools} == {"metadata_schema", "read_sql", "semantic_search"}
    result = asyncio.run(
        server.call_tool("read_sql", {"sql": "SELECT count(*) AS count FROM mcp_emails"})
    )
    assert "count" in str(result)
    assert "0" in str(result)


def test_real_stdio_mcp_transport(tmp_path: Path) -> None:
    import sys

    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    from config.application import save_config

    path = tmp_path / "config.yaml"
    config = AppConfig.model_validate({"tracks": {"track2_enabled": False}})
    save_config(path, config)

    async def verify() -> None:
        parameters = StdioServerParameters(
            command=sys.executable, args=["-m", "project_name.cli", "--config", str(path), "mcp"]
        )
        async with (
            stdio_client(parameters) as (reader, writer),
            ClientSession(reader, writer) as session,
        ):
            await session.initialize()
            tools = await session.list_tools()
            assert "read_sql" in {tool.name for tool in tools.tools}
            result = await session.call_tool(
                "read_sql", {"sql": "SELECT count(*) AS count FROM mcp_emails"}
            )
            assert not result.isError
            assert result.structuredContent is not None

    asyncio.run(verify())
