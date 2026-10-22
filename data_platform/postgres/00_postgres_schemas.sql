-- Run before the bakery table and seed files. Marmot uses unqualified
-- PostgreSQL objects, so its role search_path selects the dedicated schema.

\getenv marmot_user POSTGRES_USER
\getenv cube_user CUBEJS_DB_USER
\getenv cube_pass CUBEJS_DB_PASS
\getenv db_name POSTGRES_DB

SELECT format('CREATE ROLE %I LOGIN PASSWORD %L', :'cube_user', :'cube_pass')
WHERE NOT EXISTS (
  SELECT 1 FROM pg_roles WHERE rolname = :'cube_user'
)
\gexec

ALTER ROLE :"cube_user" WITH LOGIN PASSWORD :'cube_pass';

CREATE SCHEMA IF NOT EXISTS bakery AUTHORIZATION :"marmot_user";
CREATE SCHEMA IF NOT EXISTS marmot AUTHORIZATION :"marmot_user";
CREATE SCHEMA IF NOT EXISTS cube_core AUTHORIZATION :"cube_user";
CREATE SCHEMA IF NOT EXISTS analytics_staging AUTHORIZATION :"marmot_user";
CREATE SCHEMA IF NOT EXISTS analytics_core AUTHORIZATION :"marmot_user";
CREATE SCHEMA IF NOT EXISTS analytics_mart AUTHORIZATION :"marmot_user";

COMMENT ON SCHEMA bakery IS 'Bakery operational data: sales, inventory, production and purchasing.';
COMMENT ON SCHEMA marmot IS 'Marmot catalog application metadata.';
COMMENT ON SCHEMA cube_core IS 'Cube Core namespace; Cube Store persistence is mounted separately.';

ALTER ROLE :"marmot_user" IN DATABASE :"db_name"
  SET search_path TO marmot, public;

ALTER ROLE :"cube_user" IN DATABASE :"db_name"
  SET search_path TO bakery, cube_core, public;

GRANT USAGE ON SCHEMA bakery TO :"cube_user";
GRANT SELECT ON ALL TABLES IN SCHEMA bakery TO :"cube_user";
ALTER DEFAULT PRIVILEGES FOR ROLE :"marmot_user" IN SCHEMA bakery
  GRANT SELECT ON TABLES TO :"cube_user";

-- Cube reads the curated mart layer through the same PostgreSQL connector.
-- Keep the grant read-only; dbt remains the owner and writer of analytics_*.
GRANT USAGE ON SCHEMA analytics_mart TO :"cube_user";
GRANT SELECT ON ALL TABLES IN SCHEMA analytics_mart TO :"cube_user";
ALTER DEFAULT PRIVILEGES FOR ROLE :"marmot_user" IN SCHEMA analytics_mart
  GRANT SELECT ON TABLES TO :"cube_user";
