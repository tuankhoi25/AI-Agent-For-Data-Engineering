#!/usr/bin/env python3
"""Expose table discovery and Cube semantic queries as MCP tools."""

import argparse
import os
from typing import Any

from mcp.server import MCPServer

from cube_api import SemanticQuery, load_cube_query, read_cube_model
from marmot_api import read_available_tables


mcp = MCPServer("Bakery Data Tools")


@mcp.tool()
async def list_available_tables() -> dict[str, Any]:
    """List all available tables across all providers registered in Marmot.

    Returns names, business descriptions, providers, databases, schemas, IDs
    and MRNs to identify relevant datasets. No arguments; pagination is automatic.
    Use discover_data with an ID or MRN for column definitions and relationships.
    """
    return await read_available_tables()


@mcp.tool()
async def inspect_cube_model(cube_names: list[str] | None = None) -> dict[str, Any]:
    """List Cube models or inspect their queryable measures, dimensions and segments.

    This is the Cube query model, not the Marmot business catalog.
    """
    return await read_cube_model(cube_names)


@mcp.tool()
async def run_cube_query(query: SemanticQuery) -> dict[str, Any]:
    """Run a Cube Semantic Query API request using a structured query object.

Use DBHub for SQL over Cube.
    """
    return await load_cube_query(query)


def main() -> None:
    parser = argparse.ArgumentParser(description="Bakery data MCP server")
    parser.add_argument(
        "--transport", choices=("stdio", "streamable-http"), default="streamable-http"
    )
    parser.add_argument("--host", default=os.getenv("MCP_SERVER_HOST", "127.0.0.1"))
    parser.add_argument(
        "--port", type=int, default=int(os.getenv("MCP_SERVER_PORT", "8001"))
    )
    args = parser.parse_args()

    if args.transport == "streamable-http":
        mcp.run(
            transport=args.transport,
            host=args.host,
            port=args.port,
            stateless_http=True,
            json_response=True,
        )
    else:
        mcp.run(transport=args.transport)


if __name__ == "__main__":
    main()
