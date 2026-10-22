"""Read table summaries from the Marmot REST API."""

import os
from typing import Any

import httpx


async def read_available_tables() -> dict[str, Any]:
    host = os.getenv("MARMOT_HOST", "").rstrip("/")
    api_key = os.getenv("MARMOT_API_KEY", "")
    if not host or not api_key:
        raise RuntimeError("MARMOT_HOST and MARMOT_API_KEY are required to read available tables.")

    tables: list[dict[str, Any]] = []
    offset = 0
    async with httpx.AsyncClient(
        timeout=30,
        headers={"Authorization": f"Bearer {api_key}"},
    ) as client:
        while True:
            response = await client.get(
                f"{host}/api/v1/assets/search",
                params={"types": "Table", "limit": 100, "offset": offset},
            )
            response.raise_for_status()
            assets = response.json()["assets"]
            if not assets:
                break
            for asset in assets:
                metadata = asset.get("metadata") or {}
                tables.append({
                    "id": asset.get("id"),
                    "name": asset.get("name"),
                    "description": asset.get("user_description") or asset.get("description") or "",
                    "providers": asset.get("providers", []),
                    "database": metadata.get("database"),
                    "schema": metadata.get("schema"),
                    "mrn": asset.get("mrn"),
                })
            offset += len(assets)

    return {"table_count": len(tables), "tables": tables}
