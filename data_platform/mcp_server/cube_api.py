"""Cube REST client and the query shape exposed by the MCP tools."""

import os
from typing import Any, Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field


CUBE_API_URL = os.getenv(
    "CUBE_API_URL", "http://localhost:4000/cubejs-api/v1"
).rstrip("/")
CUBE_API_TOKEN = os.getenv("CUBE_API_TOKEN", "")


class TimeDimension(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dimension: str = Field(description="Exact Cube time dimension name")
    dateRange: str | list[str] | None = Field(
        default=None, description="Relative period or [start_date, end_date]"
    )
    granularity: str | None = Field(
        default=None, description="Time grouping, such as day or month"
    )


class SemanticQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    measures: list[str] = Field(
        default_factory=list, description="Exact Cube measure names for calculations"
    )
    dimensions: list[str] = Field(
        default_factory=list, description="Exact Cube dimension names for grouping"
    )
    timeDimensions: list[TimeDimension] = Field(default_factory=list)
    filters: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Cube filter objects, such as {member, operator, values}",
    )
    segments: list[str] = Field(default_factory=list)
    order: dict[str, Literal["asc", "desc"]] | None = Field(
        default=None, description="Map exact member names to asc or desc"
    )
    limit: int = Field(default=100, ge=1, le=1000, strict=True)
    offset: int = Field(default=0, ge=0, strict=True)
    timezone: str = "Asia/Ho_Chi_Minh"
    ungrouped: bool | None = None


def _headers() -> dict[str, str]:
    return {"Authorization": CUBE_API_TOKEN} if CUBE_API_TOKEN else {}


async def _metadata(client: httpx.AsyncClient) -> list[dict[str, Any]]:
    response = await client.get(f"{CUBE_API_URL}/meta", headers=_headers())
    response.raise_for_status()
    return response.json().get("cubes", [])


async def read_cube_model(cube_names: list[str] | None) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=30) as client:
        cubes = await _metadata(client)

    if not cube_names:
        return {
            "cubes": [
                {key: cube[key] for key in ("name", "title", "type") if key in cube}
                for cube in cubes
            ]
        }

    requested = set(cube_names)
    cubes = [cube for cube in cubes if cube.get("name") in requested]
    missing = sorted(requested - {cube.get("name") for cube in cubes})
    if missing:
        return {"error": "Unknown cube name(s)", "unknown": missing}

    def members(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            {
                key: member[key]
                for key in ("name", "title", "type", "aggType", "isPrimaryKey")
                if key in member
            }
            for member in items
        ]

    return {
        "cubes": [
            {
                "name": cube.get("name"),
                "measures": members(cube.get("measures", [])),
                "dimensions": members(cube.get("dimensions", [])),
                "segments": members(cube.get("segments", [])),
            }
            for cube in cubes
        ]
    }


async def load_cube_query(query: SemanticQuery) -> dict[str, Any]:
    payload = query.model_dump(exclude_unset=True, exclude_none=True)
    payload.setdefault("limit", query.limit)
    payload.setdefault("timezone", query.timezone)

    async with httpx.AsyncClient(timeout=60) as client:
        cubes = await _metadata(client)
        valid = {
            kind: {
                member["name"]: member
                for cube in cubes
                for member in cube.get(kind, [])
            }
            for kind in ("measures", "dimensions", "segments")
        }
        invalid = {
            kind: [name for name in getattr(query, kind) if name not in valid[kind]]
            for kind in valid
        }
        invalid["timeDimensions"] = [
            item.dimension
            for item in query.timeDimensions
            if valid["dimensions"].get(item.dimension, {}).get("type") != "time"
        ]
        invalid = {kind: names for kind, names in invalid.items() if names}
        if invalid:
            return {"error": "Invalid Cube members", "invalid_members": invalid}

        response = await client.post(
            f"{CUBE_API_URL}/load", headers=_headers(), json={"query": payload}
        )

    if response.is_error:
        try:
            details = response.json().get("error", response.text[:500])
        except (ValueError, AttributeError):
            details = response.text[:500]
        return {
            "error": "Cube semantic query failed",
            "status_code": response.status_code,
            "details": details,
        }

    result = response.json()
    rows = result.get("data", [])
    return {
        "data": rows,
        "row_count": len(rows),
        "annotation": result.get("annotation", {}),
        "timezone": payload["timezone"],
        "last_refresh_time": result.get("lastRefreshTime"),
    }
