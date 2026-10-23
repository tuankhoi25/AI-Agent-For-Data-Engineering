# Bakery assistant UI

Default assistant-ui frontend, AG-UI streaming and the existing Python/LangChain agent.
Marmot provides business context, Cube provides semantic queries, and DBHub provides SQL
through Cube's PostgreSQL interface. The agent serves stakeholders and managers;
it prefers [13 curated DBHub reporting tools](../dbhub/README.md) for common
management questions, supplying parameters without writing SQL. It uses Cube
REST or ad hoc SQL for questions outside those reports' documented scope.

## Perspective visualization tools

- `inspect_perspective`: installed visual plugins and column roles, not business metadata.
- `render_perspective`: **one chart, grid/pivot or Number Card per call**, using one typed
  `table` and one native `view` configuration. No dashboard layout or app-added scroll area.

Perspective 5.5.1 runs locally in the browser. Official chart/datagrid bundles and WASM
are served from versioned public assets; no external CDN is needed. Native settings provide
filters, grouping, splitting, visual selection and chart interactions. Datagrid retains
its own native scrolling. Each view fits its container; fullscreen uses the same viewer.

The typed table has `name`, `schema`, verified `rows` (maximum 2,000) and optional description.
Numeric strings are converted using schema; unsafe integers are rejected. Missing data is
not invented. `view` declares `plugin`, `columns` and optional `group_by`, `split_by`,
`aggregates`, `sort` and `filter`. See `agent/instructions/perspective/SKILL.md` for examples.

Filters only operate on supplied rows and do not query the database. A new period or missing
filter dimension requires a new query. **Download view JSON includes the supplied data**
and current native configuration, including rows hidden by filters. Reset restores the
initial view. Routine tool calls stay grouped; visualizations render outside the trace.

The project-owned **Number Card** plugin uses Perspective's official plugin API. It shows
one numeric scalar or an explicitly aggregated engine grand total, with optional unit,
locale and decimals formatting. Empty/null scalar results show a dash; observed zero shows 0.
The plugin does not query the database or calculate totals in JavaScript.

Chat threads and graph checkpoints remain in memory; refreshing loses the browser session.

## Automatic tool execution

Backend tools execute in LangGraph and browser tools execute through the
assistant-ui toolkit. When a model response includes both, the frontend-tools
middleware uses a LangGraph `ToolNode` to finish the backend calls before ending
the run for browser execution. Only browser calls remain unresolved at handoff.
Their results arrive on the next run; backend results keep stable call/message
IDs so they are not executed or inserted twice.

Routine tool traces use a display-only composition of assistant-ui's fallback
components. They never display Allow/Deny or write an approval string as a query
result. Query errors remain errors, and visual tools return their actual result
through `execute`; there is no automatic approval placeholder.

## Run

From the repository root:

```sh
docker compose --env-file .env -f docker-compose.yml up -d --build --no-deps assistant_ui bakery_agent
```

Refresh http://localhost:3000 after rebuilding. Local frontend development: `npm ci`, then
`npm run dev -- --port 3001` from this directory.

## Verification

All current tests and fixtures are in `test/`. Python agent tests use a
separate environment because the agent and root MCP tools pin different MCP
runtime versions. From the repository root:

```sh
python3.12 -m venv .venv-agent-test
./.venv-agent-test/bin/python -m pip install -r data_platform/assistant_ui/test/requirements.txt
./.venv-agent-test/bin/python -m unittest discover -s data_platform/assistant_ui/test -p 'test_*.py' -v
```

These Python tests use fake model/tool responses and do not call OpenAI or
start Docker. Run the following frontend commands from `data_platform/assistant_ui`:

```sh
npm run typecheck
# Tests use synthetic data and expect the dev server on port 3001.
PLAYWRIGHT_CHROMIUM_EXECUTABLE='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' npm run test:browser
PLAYWRIGHT_CHROMIUM_EXECUTABLE='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' npm run test:regression
PLAYWRIGHT_CHROMIUM_EXECUTABLE='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' npm run test:cards
```

Override `ASSISTANT_UI_URL` to test a deployed URL. `npm run test:live` is opt-in and uses
real MCP queries and the configured agent model, consuming API usage.

## Files

- `components/visualization-toolkit.tsx`: frontend tools and tool UI registration.
- `components/perspective-card.tsx`: single native viewer lifecycle, reset/export/fullscreen.
- `lib/perspective-parameters.ts`: schema validation and typed row conversion.
- `lib/perspective-runtime.ts`: shared local engine and plugin inspection.
- `lib/perspective-number-card.ts`: project Number Card extension.
- `lib/render-requests.ts`, `lib/use-render-tool.ts`: renderer/executor handshake.
- `agent/instructions/perspective/SKILL.md`: visualization workflow and examples.

Pre-change source snapshots are in `.rollback/`. Dashboard layout sizing and custom scroll
code were removed; existing business-query tools and agent behavior are retained.
