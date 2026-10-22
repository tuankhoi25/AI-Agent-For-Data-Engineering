-- Run before platform schemas and bakery tables in POSTGRES_DB.
-- The Dockerfile installs the binaries while building the PostgreSQL image;
-- Compose preloads the library before the entrypoint runs this init SQL.
-- Keep extension creation here to survive docker compose down -v.
CREATE EXTENSION IF NOT EXISTS pg_duckdb WITH SCHEMA public;

-- Cube connects as cube_core and is allowed to use DuckDB through the
-- duckdb.postgres_role setting in docker-compose.yml. Other application roles
-- keep normal PostgreSQL execution unless they explicitly receive access.
