"""Standard stdio MCP server exposing curated SQL and current semantic evidence."""

from dataclasses import asdict

from mcp.server.fastmcp import FastMCP

from project_name.application import Runtime
from project_name.core.records import JsonRow
from project_name.infrastructure.sqlite_store import MCP_SCHEMA


def create_server(runtime: Runtime) -> FastMCP:
    server = FastMCP(
        "Outlook RAG",
        instructions=(
            "SQL is read-only over mcp_emails, mcp_documents, and "
            "mcp_attachments. Document bodies are available only through "
            "enabled semantic retrieval."
        ),
    )

    @server.tool()
    def metadata_schema() -> JsonRow:
        """Describe curated, ready-only relational views and their columns."""
        return MCP_SCHEMA

    @server.tool()
    def read_sql(
        sql: str, parameters: list[str | int | float | bool | None] | None = None, limit: int = 200
    ) -> list[JsonRow]:
        """Run bounded read-only SQL against curated metadata views with positional parameters."""
        return runtime.metadata.query(sql, parameters or (), limit)

    @server.tool()
    def semantic_search(query: str, limit: int = 5) -> list[JsonRow]:
        """Retrieve current, ready Track 2 chunks with IDs and source paths."""
        return [asdict(hit) for hit in runtime.deep_agent().search(query, limit)]

    return server
