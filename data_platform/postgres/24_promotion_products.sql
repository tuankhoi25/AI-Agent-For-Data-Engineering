SET search_path TO bakery;

CREATE TABLE IF NOT EXISTS promotion_products (
    promotion_id BIGINT NOT NULL REFERENCES promotions(promotion_id) ON DELETE CASCADE,
    product_id BIGINT NOT NULL REFERENCES products(product_id) ON DELETE CASCADE,
    PRIMARY KEY (promotion_id, product_id),
    _created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    _last_updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    _is_deleted BOOLEAN NOT NULL DEFAULT FALSE,
    _deleted_at TIMESTAMPTZ,
    CONSTRAINT promotion_products_audit_timestamps_check CHECK (_last_updated_at >= _created_at),
    CONSTRAINT promotion_products_audit_deletion_check CHECK ((_is_deleted AND _deleted_at IS NOT NULL) OR (NOT _is_deleted AND _deleted_at IS NULL))
);

CREATE OR REPLACE TRIGGER bakery_row_audit
BEFORE INSERT OR UPDATE ON promotion_products
FOR EACH ROW EXECUTE FUNCTION bakery.set_row_audit();

COMMENT ON COLUMN promotion_products._created_at IS 'Database insertion time set by row-audit trigger; immutable after insert. Not the business event time. Existing rows receive migration adoption time.';
COMMENT ON COLUMN promotion_products._last_updated_at IS 'Database time of the latest INSERT or UPDATE, including soft deletion and restoration; trigger-managed. Not a commit sequence or business event time.';
COMMENT ON COLUMN promotion_products._is_deleted IS 'Soft-delete flag: false means retained in normal operations; true means logically deleted. Independent of is_active and business status; no cascading or reversal.';
COMMENT ON COLUMN promotion_products._deleted_at IS 'Database time of the current soft-deletion episode; set when _is_deleted becomes true, preserved while true and cleared on restoration. NULL for non-deleted rows.';


INSERT INTO promotion_products (promotion_id, product_id)
SELECT p.promotion_id, pr.product_id
FROM promotions p CROSS JOIN products pr
JOIN product_categories c ON c.category_id=pr.category_id
WHERE p.promotion_code='OPENING-10-PASTRY'
  AND c.category_code IN ('VIENNOISERIE','MACARON','ENTREMET')
ON CONFLICT (promotion_id, product_id) DO NOTHING;
