---
name: marmot
description: Read and maintain business metadata in the Marmot data catalog, including assets, definitions, lineage, ownership, tags and data products.
---

# Marmot data catalog

Marmot contains cataloged knowledge about datasets: their locations, schemas,
column descriptions, business definitions, relationships and governance.
Catalog metadata provides context for analysis; numeric values come from Cube
REST queries or DBHub SQL over Cube's model.

## Tool scopes

### `list_available_tables` — all tables with business descriptions

- Call with `{}`; no arguments, provider filters or pagination inputs.
- Lists all table assets registered in Marmot across providers and visible to the configured API key. Pagination is handled by the tool.
- Returns `table_count` and `tables`, each containing `id`, `name`, `description`, `providers`, `database`, `schema` and `mrn`.
- Use this overview when the relevant datasets are not known. Descriptions help select candidate tables; inspect selected tables with `discover_data` for column definitions and relationships.
- The description prefers business user notes, falling back to the ingested description. An empty description means none was recorded.
- This project tool reads Marmot's REST API. It returns metadata, not table rows or current business values.

### `discover_data` — assets and their metadata

- Browse or search assets using `query`, `types`, `providers`, `tags` or `metadata_filters`.
- Retrieve an asset's full catalog entry using its returned `id` or exact `mrn`.
- Use asset details for source location, schema, column meaning and other recorded metadata. Search listings identify candidates; retrieve details when the question needs information beyond the listing.
- This tool discovers datasets and describes their contents. It does not query their transaction rows or execute SQL.

### `lookup_term` — business glossary

- Browse or search definitions using `query`, retrieve a term with `term_id`, or browse a hierarchy using `parent_term_id`.
- Use for business meaning, synonyms, term relationships and linked assets returned by the catalog.
- A glossary term is a concept; its definition does not supply the current value of a metric.

### `trace_lineage` — data dependencies

- Inspect upstream, downstream or both directions using `asset_id` or `mrn`, `direction` and `depth`.
- Use to explain recorded source dependencies and downstream impact. Depth is 1–10, default 3.
- Lineage edges describe cataloged dependencies. Query join keys and transformation logic require supporting metadata; an edge alone does not establish them.

### `find_ownership` — responsibilities for data

- Find owners of an asset with `asset_id`, or entities owned by a person or team with `user_id`, `username`, `team_id` or `team_name`.
- `include_assets` and `include_glossary_terms` control which owned entities are returned.
- Use for responsibility and ownership relationships. Use `explore_teams` for team membership and `manage_owners` for ownership changes.

### `explore_teams` — teams and membership

- Browse teams, inspect a team with `team_id` or `team_name`, or find a person's teams with `user_id` or `username`.
- Use for team identity and members. Team membership and ownership of an asset are separate catalog relationships.

### `explore_data_products` — curated data collections

- Browse or search catalog data products with `query` or `tags`; retrieve a product and its linked assets with `id` or `name`.
- A data product is a curated collection of data assets. Retail products sold by the bakery are business records in source tables.
- Use to discover a governed collection and its scope. Retrieve member assets when their details are needed.

### `manage_owners` — update asset ownership

- Identify the asset with `id` or `mrn`; supply `action` (`add` or `remove`), `owner_type` (`user` or `team`) and `owner_id`.
- Resolve the owner identity from catalog responses. This tool changes an asset's ownership; it does not change team membership.

### `manage_tags` — update asset labels

- Identify the asset with `id` or `mrn`; supply `add_tags` and/or `remove_tags`.
- This tool changes catalog labels. It does not filter or update business records in the source database.

### `update_documentation` — update asset notes

- Identify the asset with `id` or `mrn`; supply `documentation` text.
- Writes the asset's `user_description`, preserving its ingested description. An empty string clears the notes.
- Its scope is asset notes; it does not create UI documentation pages or update source data.

## Catalog access and changes

Use the live tool input schemas as the parameter contract. Preserve identifiers
returned by the catalog, including MRN case and qualifiers. Use pagination when
more results are needed; `discover_data` defaults to 20 results, maximum 100.

Examples of MCP tool inputs:

```json
{"query": "sales"}
```

Pass this to `discover_data` to find candidate assets. For an exact asset,
pass its returned identifier instead:

```json
{"mrn": "mrn://table/postgresql/sales"}
```

For a term, pass `{"query": "Sale"}` to `lookup_term`. For recorded
dependencies, pass `{"mrn": "mrn://table/postgresql/sales", "direction":
"downstream", "depth": 2}` to `trace_lineage`. A search listing is a lead;
read the detail response before claiming a column meaning or join key.

The three write tools require `assets:manage` and the server's preview workflow:
call without `confirm` or with `confirm: false`, present the proposed change,
then submit the approved change with `confirm: true`. Confirm only changes
actually approved by the user and reported as applied by the server.

## Choosing catalog context

Use the tool whose scope matches the information needed. Definitions belong to
the glossary, source structures to assets, dependencies to lineage, and
responsibilities to ownership. Retrieve the catalog context needed to resolve
ambiguity before interpreting a numerical result. A catalog-only answer can be
completed without querying transaction data.

For analysis, use the relevant definition and data grain when selecting Cube
members or composing SQL against Cube through DBHub. SQL examples recorded in
catalog metadata help explain a calculation; Marmot tools do not execute them.
Report missing or conflicting definitions explicitly.

Adapted from the [official Marmot skill](https://github.com/marmotdata/marmot/blob/main/SKILL.md)
for the MCP tools available in this project.
