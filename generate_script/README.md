# Bakery data generation and bootstrap

Start the services from the project root:

```bash
docker compose --env-file .env -f docker-compose.yml up -d
```

On a fresh PostgreSQL volume, the official PostgreSQL image automatically runs
the numbered `.sql` files in `data_platform/postgres` in filename order. This creates
the platform schemas, bakery tables, and opening inventory/catalog seed data.
Once PostgreSQL is healthy, run the host-side bootstrap script to verify the
fresh `bakery` schema and backfill operational history:

```bash
bash generate_script/bootstrap_bakery.sh
```

The bootstrap script checks whether all 35 bakery tables exist. If they do,
it skips seed replay. If no bakery tables exist, it runs the numbered
initialization SQL files. A partially initialized schema fails explicitly so
opening inventory is not accidentally replayed into existing business data. It
then backfills history using the host Python environment.

`00_postgres_schemas.sql` initializes platform schemas/roles;
`01_bakery_schema.sql` creates `bakery`; `01_row_audit.sql` defines the lifecycle
trigger function before business tables and seeds. Each table file selects the
`bakery` search path. Existing tables in another schema are not moved by this
bootstrap. The project assumes a fresh PostgreSQL volume when the source schema
needs to be recreated.

Bootstrap reads the project-root `.env`; an exported `DATABASE_URL` takes
precedence and must use the same database as `POSTGRES_DB`, with host
`localhost` or `127.0.0.1` for host-side Python. Both Python runners use the
`bakery` search path. Local `psql` is unnecessary because bootstrap invokes
it inside the running PostgreSQL container.

## Product catalog

- `data_platform/postgres/10_products.sql` seeds 15 bakery products, 10 drinks and 8 takeaway/retail items. Product names are normalized for a French-style bakery POS.
- Product categories describe what customers order: viennoiserie, macaron, entremet, coffee, tea/refreshments, chocolate drinks, bakery boxes, packaged goods and merchandise. Pack sizes are sale formats, not separate product categories.
- Menu names are based on public catalogues from La Boulangerie Française and La Paris. Ingredient summaries are broad planning descriptions, not verified shop recipes. Exact quantities belong in `recipes` and `recipe_items`.
- `supplier_products` contains candidate supplier/brand relationships; update it from actual quotes and invoices. `LOCAL_FOOD_VENDOR` is a placeholder to replace with a real local vendor.

## Opening baseline and history

- On the first initialization, the opening date is the local date minus `HISTORY_DAYS` (30 by default). The branch, five employees, starting price list, recipes, supplier purchase orders/receipts, received inventory lots, opening production batches, on-hand stock movements and one opening promotion are seeded relative to that date.
- The shell bootstrap then runs `backfill_operations.py --days $HISTORY_DAYS`, ending yesterday. Completed dates are skipped, so rerunning the script does not duplicate historical activity. Set `HISTORY_DAYS` before the first initialization to choose the window; changing it later requires a fresh database volume and bootstrap. `SIMULATOR_MAX_ORDERS` controls the baseline order volume.
- Prices, costs, recipe quantities, opening purchase quantities, expiry dates and production quantities are illustrative demo values, not supplier quotes or a real bakery's recipe/records.
- The SQL seed leaves `customers`, `sales`, `sale_items`, `payments`, `loyalty_transactions`, `returns`, `return_items`, `shifts`, `cash_movements`, `waste_records` and `simulation_runs` empty; the backfill then creates historical operating records in them.
- Allergen mappings are seeded as unconfirmed estimates from the simulated recipes and should be reviewed before serving customers.

## One-tick operations simulator

After the shell bootstrap finishes, run `simulate_operations.py` once each day before you run the analytics pipeline:

```bash
pip install "psycopg[binary]" Faker holidays certifi
python3 generate_script/simulate_operations.py --max-orders 3
```

Both Python scripts read `DATABASE_URL` from the project-root `.env`. The process environment or `--dsn` can override it. The script resolves `.env` relative to its own file, so it does not depend on the current working directory. Docker Compose reads Postgres credentials and host-published ports from that file when you pass `--env-file .env`; service ports inside containers are fixed in Compose to match their images.

The daily runner captures PostgreSQL `clock_timestamp()` as the run cutoff. It does not accept a simulated date/time or create future business events. Business events are scheduled at distinct ordered times at or before that cutoff; each row audit timestamp uses the actual database write time instead. Historical generation belongs to the separate backfill entry point. It creates sales and production only between 07:00 and 22:00 in the branch timezone, and does not write anything before the branch `opening_date`. The first SQL initialization sets `opening_date` from `HISTORY_DAYS`; opening hours are constants at the top of the Python file.

The simulator still uses hourly Open-Meteo weather in `simulate_operations.py` to calculate demand factors and records that context in `simulation_runs.notes` and sale notes. Detailed daily weather is collected separately by `data_platform/weather/collect_daily_weather.py` and persisted in `bakery.weather_daily`; the dbt pipeline publishes it as `analytics_mart.fct_daily_weather` and links it to `dim_date`. The collector is scheduled by Dagu at 22:00, before the 22:15 dbt DAG. It requests the daily variables documented by Open-Meteo, including temperature, apparent temperature, humidity, precipitation/rain/snow, WMO code, sunrise/sunset, daylight/sunshine, wind and shortwave radiation. The simulator's demand behavior is unchanged: heavy rain (at least 5 mm in the preceding hour or WMO code 65, 67 or 82) cuts the weather demand factor to 0.35. Thunderstorms use 0.40, moderate rain 0.65, light rain 0.85, dry/neutral weather 1.00, and sunny conditions 1.15. Sunny means at least 150 W/m² shortwave radiation or a clear/mainly-clear WMO code, with no rain. These factors combine with the calendar: weekends raise order volume by about 30%, Vietnamese public holidays by about 50%, and a holiday on a weekend by about 80%. The `holidays` library supplies Vietnam's calendar, including Lunar New Year and observed dates. Temperature of 32°C or more raises the chance of a drink; below 30°C lowers it. Each sale represents one customer and may contain zero or one drink, always one serving, so many customers buy no drink.

Each open-hours run starts with a random weekday baseline of 1 to `--max-orders` paid orders (default 3), then adjusts demand for weather and the calendar, so weekends and holidays can exceed that baseline. Stock is deducted from FEFO lots. The same run can record customer/loyalty activity, promotion use, cash movement, low-stock purchase orders, due purchase receipts, production batches, and expired-stock waste. Purchase orders are received no sooner than 24 hours after ordering, and only on the later run that observes them as due. Outside opening hours, the script can still process due receipts, expired lots, close a shift, and create reorder orders, but will not create sales or production.

## Historical backfill behavior

The bootstrap backfill uses 11:00 local time for each day. The standalone `backfill_operations.py` command also supports `--end-date YYYY-MM-DD`, `--run-time HH:MM`, `--branch`, `--dsn`, `--max-orders` and `--seed`. It uses the shared operation logic, including hourly historical weather, calendar demand, FEFO stock, sales, production, purchasing and loyalty. It fills missing dates in the requested range and safely exits when all dates are already complete.

Pass `--dsn` to override `.env`, `--branch MAIN` to choose a branch, or `--seed 1234` to reproduce random choices. The seed does not change the run timestamp. `Faker` is optional; without it, the script uses simple fallback names and leaves email/date of birth blank. If Open-Meteo is unreachable, the script uses neutral weather assumptions and records a warning in the run output. Weather data comes from an approximately 9 km model/reanalysis grid, not a street-level rain gauge. Open-Meteo data is provided under CC BY 4.0; the simulator records attribution in the run notes. See the [Open-Meteo Historical Weather API](https://open-meteo.com/en/docs/historical-weather-api) and [terms](https://open-meteo.com/en/terms). The Vietnam calendar library supports the country calendar and observed days off; see [python-holidays](https://github.com/vacanza/holidays).

All menu prices, supplier costs, recipe quantities, shelf lives, opening hours, reorder levels, weather thresholds and demand probabilities are illustrative simulation values and should be replaced or calibrated with store data for a realistic forecast.

## Audit columns and soft deletion

All 34 audited operational tables now have `_created_at`, `_last_updated_at`,
`_is_deleted`, `_deleted_at`. `simulation_runs` remains unchanged. PostgreSQL
triggers own the three timestamps; insert/update statements should not supply
them. Daily and historical runners both use real database write time for audit
fields, while business event timestamps retain their scheduled dates/times.

Operational selection, stock balances, loyalty balances, promotion usage,
receiving, refunds and reordering exclude logically deleted rows. Unique phone
checks still inspect every row because a soft-deleted phone remains reserved
by the existing unique constraint. The generator never randomly deletes data.
Logical deletion does not cascade or reverse a business transaction.

Both runners check audit fields/triggers before generating data. If the check
fails, recreate the PostgreSQL volume and run the bootstrap flow again.
