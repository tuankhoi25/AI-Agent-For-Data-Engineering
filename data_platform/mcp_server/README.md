# Bakery agent tools

The notebook client connects to three MCP endpoints:

| Service | MCP tools | Purpose |
| --- | --- | --- |
| Marmot | Nine catalog tools | Business definitions, source schemas, lineage, ownership and governance |
| This service | `list_available_tables`, `inspect_cube_model`, `run_cube_query` | Table names and business descriptions from Marmot; available Cube members and structured semantic queries |
| DBHub | `search_objects`, `execute_sql` | Explore and query Cube's SQL API, including supported CTEs and subqueries |

Cube model metadata tells the agent what it can query. Marmot metadata explains
what the data means. DBHub connects to Cube's PostgreSQL-compatible SQL endpoint,
not to the operational PostgreSQL database.

`server.py` registers MCP tools and starts the transport. `cube_api.py`
holds the Cube REST client and the accepted query schema. `marmot_api.py`
reads table summaries from Marmot's REST API, retaining descriptions omitted
by native MCP search listings. DBHub and Marmot also run their own MCP servers.

Each service has one local skill in `skills/`. The notebook loads all three;
the system prompt gives the agent its role and the skills describe tool scope
and argument shapes. The agent selects a query interface according to the
question and the available model. The skills are general tool instructions,
not templates for particular bakery answers.

## Examples

Call `list_available_tables` with `{}`. It automatically reads all pages of
Table assets across providers and returns names, business descriptions, source
identifiers and MRNs. It does not require a provider, filter or pagination input.
For column definitions, follow up with Marmot's `discover_data` using the returned
ID or MRN. Runtime configuration uses `MARMOT_HOST` and `MARMOT_API_KEY`; Compose
passes the internal Marmot address and the key from the project `.env`.

Inspect a Cube model:

```json
{"cube_names": ["sales"]}
```

Send this to `inspect_cube_model`. For a structured Cube query, send this to
`run_cube_query`:

```json
{"query": {"measures": ["sales.count"], "limit": 10}}
```

For SQL, DBHub provides its own MCP endpoint at
`http://localhost:${DBHUB_HOST_PORT}/mcp`:

```json
{"sql": "WITH counts AS (SELECT COUNT(*) AS n FROM sales) SELECT n FROM counts"}
```

Send that to DBHub's `execute_sql`. SQL syntax support is determined by Cube's
SQL API. See the corresponding SKILL.md files for detailed examples and limits.

## Reload

After editing this server, rebuild it and recreate the agent so its tool list updates:

```bash
docker compose --env-file .env -f docker-compose.yml up -d --no-deps --build --force-recreate mcp_server bakery_agent
```

The project notebook `notebooks/assistant_demo.ipynb` reads the API key, Marmot URL and host ports from
the project `.env` and runs `openai:gpt-6-luna`.
