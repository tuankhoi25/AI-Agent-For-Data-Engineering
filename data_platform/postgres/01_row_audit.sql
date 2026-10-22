-- Shared by all 33 operational tables. simulation_runs is deliberately excluded.
-- Run after 01_bakery_schema.sql and before the CREATE TABLE/seed files.
SET search_path TO bakery;

CREATE OR REPLACE FUNCTION bakery.set_row_audit()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog
AS $$
DECLARE
    audit_time TIMESTAMPTZ := clock_timestamp();
BEGIN
    IF TG_OP = 'INSERT' THEN
        -- Callers cannot backdate or override audit timestamps, even during backfill.
        NEW._created_at := audit_time;
        NEW._last_updated_at := audit_time;
        NEW._deleted_at := CASE WHEN NEW._is_deleted THEN audit_time ELSE NULL END;
    ELSE
        NEW._created_at := OLD._created_at;
        -- Keep row-local time monotonic even if the server clock moves backwards.
        NEW._last_updated_at := GREATEST(audit_time, OLD._last_updated_at, OLD._created_at);
        IF NEW._is_deleted THEN
            IF OLD._is_deleted THEN
                NEW._deleted_at := OLD._deleted_at;
            ELSE
                NEW._deleted_at := NEW._last_updated_at;
            END IF;
        ELSE
            NEW._deleted_at := NULL;
        END IF;
    END IF;
    RETURN NEW;
END;
$$;

COMMENT ON FUNCTION bakery.set_row_audit() IS
'Trigger-managed insertion, modification and soft-deletion timestamps. DELETE is not intercepted; use UPDATE _is_deleted=true for logical deletion. No cascading or business reversal.';
