#!/usr/bin/env python3
"""Enrich dbt mart tables in Marmot without using the dbt-Marmot plugin.

The dbt plugin is still responsible for discovering dbt artifacts and lineage.
This script owns the business-facing descriptions for the physical relations in
``analytics_mart``. It is safe to rerun: only metadata, tags, schema column
descriptions, and the managed documentation page are updated.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import sys
from pathlib import Path
from typing import Any
from urllib.parse import quote

from enrich_bakery_metadata import MarmotAPI, load_env_file
from mart_metadata_details import MART_SPECS, describe_mart_column


PROJECT_ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = PROJECT_ROOT / ".env"
MART_SCHEMA = "analytics_mart"
METADATA_MARKER = "bakery_mart_metadata_enrichment"
ENRICHMENT_VERSION = "1.0"


def schema_columns(asset: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    raw_schema = asset.get("schema")
    schema = dict(raw_schema) if isinstance(raw_schema, dict) else {}
    schema_key = "columns"
    raw_columns = schema.get("columns", [])
    # The dbt-Marmot adapter stores the physical relation schema in a
    # provider-specific ``dbt`` section rather than the native PostgreSQL
    # connector's ``columns`` section. Preserve that shape when writing back.
    if not raw_columns and isinstance(schema.get("dbt"), str):
        schema_key = "dbt"
        raw_columns = schema["dbt"]
    if isinstance(raw_columns, str):
        try:
            raw_columns = json.loads(raw_columns)
        except json.JSONDecodeError:
            raw_columns = []
    if not isinstance(raw_columns, list):
        raw_columns = []
    return schema, [dict(column) for column in raw_columns if isinstance(column, dict)]


def find_mart_assets(api: MarmotAPI) -> dict[str, dict[str, Any]]:
    found: dict[str, dict[str, Any]] = {}
    expected = set(MART_SPECS)
    for asset in api.paginated("/assets/search", "assets"):
        if str(asset.get("type", "")).casefold() != "table":
            continue
        providers = {str(provider).casefold() for provider in asset.get("providers", []) or []}
        if not any("postgres" in provider for provider in providers):
            continue
        metadata = asset.get("metadata") if isinstance(asset.get("metadata"), dict) else {}
        if str(metadata.get("schema", "")).casefold() != MART_SCHEMA.casefold():
            continue
        name = str(asset.get("name", ""))
        if name in expected:
            found[name] = asset

    # Marmot's search index can lag immediately after a dbt catalog sync. Use
    # the canonical Table lookup for any mart that is not visible in search,
    # so enrichment still targets the physical PostgreSQL relation rather than
    # silently treating a transient index gap as a missing table.
    database = os.environ.get("POSTGRES_DB", "marmot").strip() or "marmot"
    for table_name in sorted(expected - found.keys()):
        fqn = f"{database}.{MART_SCHEMA}.{table_name}"
        try:
            asset = api.request(
                "GET",
                f"/assets/lookup/Table/Postgres/{quote(fqn, safe='')}"
            )
        except RuntimeError as exc:
            if "HTTP 404" in str(exc):
                continue
            raise
        if isinstance(asset, dict):
            found[table_name] = asset

    missing = sorted(expected - found.keys())
    if missing:
        raise RuntimeError(
            f"Missing analytics_mart assets in Marmot: {', '.join(missing)}. "
            "Run the dbt catalog sync after the mart tables have been built."
        )
    return found


def enrich_schema(table_name: str, asset: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    schema, columns = schema_columns(asset)
    if not columns:
        raise RuntimeError(f"Marmot has no column schema for {MART_SCHEMA}.{table_name}.")
    schema_key = "dbt" if "columns" not in schema and "dbt" in schema else "columns"

    for column in columns:
        name = str(column.get("column_name") or column.get("name") or "").strip()
        if not name:
            raise RuntimeError(f"Marmot returned an unnamed column for {MART_SCHEMA}.{table_name}.")
        data_type = str(column.get("data_type") or column.get("type") or "unknown")
        column["column_name"] = name
        column.setdefault("data_type", data_type)
        column["description"] = describe_mart_column(table_name, name, data_type)
        column["data_layer"] = "mart"
        column["dbt_model"] = table_name
        column["managed_by"] = "dbt"
        column["mart_schema"] = MART_SCHEMA

    schema[schema_key] = json.dumps(columns, ensure_ascii=False, separators=(",", ":"))
    return schema, columns


def business_metadata(table_name: str) -> dict[str, Any]:
    spec = MART_SPECS[table_name]
    metadata = {
        "data_layer": "mart",
        "mart_schema": MART_SCHEMA,
        "dbt_model": table_name,
        "managed_by": "dbt",
        "materialization": "incremental",
        "incremental_strategy": "merge",
        "model_kind": spec["model_kind"],
        "scd_type": spec["scd_type"],
        "business_domain": spec["domain"],
        "business_grain": spec["grain"],
        "unique_key": list(spec["unique_key"]),
        "source_models": list(spec["source_models"]),
        "metadata_language": "en",
        "enrichment_source": METADATA_MARKER,
        "enrichment_version": ENRICHMENT_VERSION,
    }
    if spec.get("sensitivity"):
        metadata["data_sensitivity"] = spec["sensitivity"]
        metadata["contains_personal_data"] = spec["sensitivity"] == "personal"
    else:
        metadata["data_sensitivity"] = "internal"
        metadata["contains_personal_data"] = False
    return metadata


def render_page(table_name: str, columns: list[dict[str, Any]]) -> str:
    spec = MART_SPECS[table_name]
    esc = html.escape
    parts = [
        f"<h2>{esc(spec['title'])}</h2>",
        f"<p>{esc(spec['description'])}</p>",
        "<h3>Layer and model</h3>",
        f"<p><strong>Layer:</strong> analytics mart; <strong>dbt model:</strong> <code>{esc(table_name)}</code>; <strong>materialization:</strong> incremental merge.</p>",
        f"<p><strong>Model kind:</strong> {esc(spec['model_kind'])}; <strong>SCD:</strong> {esc(spec['scd_type'])}; <strong>unique key:</strong> <code>{esc(', '.join(spec['unique_key']))}</code>.</p>",
        "<h3>Grain</h3>",
        f"<p>{esc(spec['grain'])}</p>",
        "<h3>Source dbt models</h3>",
        "<p>" + ", ".join(f"<code>{esc(model)}</code>" for model in spec["source_models"]) + "</p>",
        "<h3>Columns</h3>",
        "<ul>",
    ]
    for column in columns:
        name = str(column.get("column_name") or column.get("name") or "")
        data_type = str(column.get("data_type") or column.get("type") or "unknown")
        parts.append(
            f"<li><strong>{esc(name)}</strong> (<code>{esc(data_type)}</code>): "
            f"{esc(str(column.get('description', '')))}</li>"
        )
    parts.extend([
        "</ul>",
        "<p><em>Physical relation is stored in PostgreSQL schema analytics_mart. "
        "Column shape is read from the synchronized Marmot asset; business descriptions are maintained by "
        "enrich_bakery_mart_metadata.py.</em></p>",
    ])
    return "\n".join(parts)


def upsert_page(api: MarmotAPI, mrn: str, table_name: str, columns: list[dict[str, Any]]) -> None:
    page_title = f"Bakery Mart — {table_name}"
    entity_path = f"/docs/entity/asset/{quote(mrn, safe='')}/pages"
    page_tree = api.request("GET", entity_path) or {}
    pages = page_tree.get("pages", []) if isinstance(page_tree, dict) else []
    page = next((item for item in pages if item.get("title") == page_title), None)
    payload = {"title": page_title, "content": render_page(table_name, columns)}
    if page and page.get("id"):
        api.request("PUT", f"/docs/pages/{quote(str(page['id']), safe='')}", payload=payload)
        action = "updated"
    else:
        api.request("POST", entity_path, payload=payload)
        action = "created"
    print(f"UI Page: {table_name} ({action})")


def enrich_assets(api: MarmotAPI, assets: dict[str, dict[str, Any]]) -> None:
    for table_name, asset in sorted(assets.items()):
        asset_id = str(asset.get("id", ""))
        mrn = str(asset.get("mrn", ""))
        if not asset_id or not mrn:
            raise RuntimeError(f"Marmot mart asset {table_name!r} has no ID or MRN.")

        full_asset = api.request("GET", f"/assets/{quote(asset_id, safe='')}") or asset
        schema, columns = enrich_schema(table_name, full_asset)
        spec = MART_SPECS[table_name]
        current_metadata = full_asset.get("metadata") if isinstance(full_asset.get("metadata"), dict) else {}
        metadata = dict(current_metadata)
        metadata.update(business_metadata(table_name))
        current_tags = full_asset.get("tags") if isinstance(full_asset.get("tags"), list) else []
        tags = sorted({str(tag) for tag in current_tags} | {"bakery", "analytics-mart", "dbt", spec["model_kind"]})
        if spec["scd_type"] == "2":
            tags.append("scd2")
        payload = {
            "description": spec["description"],
            "user_description": spec["description"],
            "metadata": metadata,
            "tags": sorted(set(tags)),
            "schema": schema,
        }
        api.request("PUT", f"/assets/{quote(asset_id, safe='')}", payload=payload)
        upsert_page(api, mrn, table_name, columns)
        print(f"Mart asset: {MART_SCHEMA}.{table_name}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Validate and print writes without modifying Marmot.")
    args = parser.parse_args()

    try:
        # Local/manual runs can load the project .env.  Dagu injects the
        # Marmot credentials as container environment variables instead.
        if ENV_FILE.is_file():
            load_env_file(ENV_FILE)
        host = os.environ.get("MARMOT_HOST", "").strip()
        api_key = os.environ.get("MARMOT_API_KEY", "").strip()
        if not host or not api_key:
            raise RuntimeError("MARMOT_HOST and MARMOT_API_KEY must be available in .env or the environment.")
        api = MarmotAPI(host, api_key, dry_run=args.dry_run)
        try:
            print(f"Reading mart assets from {host.rstrip('/')}")
            assets = find_mart_assets(api)
            print(f"Found {len(assets)} analytics_mart tables.")
            enrich_assets(api, assets)
            print(f"Completed mart metadata enrichment; writes={api.writes}.")
        finally:
            api.close()
        return 0
    except Exception as exc:
        print(f"Mart metadata enrichment failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
