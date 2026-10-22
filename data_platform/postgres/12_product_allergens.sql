SET search_path TO bakery;

CREATE TABLE IF NOT EXISTS product_allergens (
    product_id BIGINT NOT NULL REFERENCES products(product_id) ON DELETE CASCADE,
    allergen_id BIGINT NOT NULL REFERENCES allergens(allergen_id),
    is_confirmed BOOLEAN NOT NULL DEFAULT FALSE,
    notes TEXT,
    PRIMARY KEY (product_id, allergen_id),
    _created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    _last_updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    _is_deleted BOOLEAN NOT NULL DEFAULT FALSE,
    _deleted_at TIMESTAMPTZ,
    CONSTRAINT product_allergens_audit_timestamps_check CHECK (_last_updated_at >= _created_at),
    CONSTRAINT product_allergens_audit_deletion_check CHECK ((_is_deleted AND _deleted_at IS NOT NULL) OR (NOT _is_deleted AND _deleted_at IS NULL))
);

CREATE OR REPLACE TRIGGER bakery_row_audit
BEFORE INSERT OR UPDATE ON product_allergens
FOR EACH ROW EXECUTE FUNCTION bakery.set_row_audit();

COMMENT ON COLUMN product_allergens._created_at IS 'Database insertion time set by row-audit trigger; immutable after insert. Not the business event time. Existing rows receive migration adoption time.';
COMMENT ON COLUMN product_allergens._last_updated_at IS 'Database time of the latest INSERT or UPDATE, including soft deletion and restoration; trigger-managed. Not a commit sequence or business event time.';
COMMENT ON COLUMN product_allergens._is_deleted IS 'Soft-delete flag: false means retained in normal operations; true means logically deleted. Independent of is_active and business status; no cascading or reversal.';
COMMENT ON COLUMN product_allergens._deleted_at IS 'Database time of the current soft-deletion episode; set when _is_deleted becomes true, preserved while true and cleared on restoration. NULL for non-deleted rows.';


-- No product/allergen mapping is seeded: allergen declarations must match the actual recipe and supplier labels.

-- Các cảnh báo này được suy ra từ recipe giả lập; is_confirmed=FALSE cho tới khi kiểm tra công thức và nhãn nhà cung cấp.
INSERT INTO product_allergens (product_id, allergen_id, is_confirmed, notes)
SELECT p.product_id, a.allergen_id, FALSE, 'Suy ra từ công thức mô phỏng; cần xác nhận trước khi dùng cho thông tin khách hàng.'
FROM (VALUES
('BAK-CROISSANT','WHEAT_GLUTEN'),('BAK-CROISSANT','DAIRY'),('BAK-CROISSANT','EGG'),
('BAK-PAIN-CHOC','WHEAT_GLUTEN'),('BAK-PAIN-CHOC','DAIRY'),('BAK-PAIN-CHOC','EGG'),
('BAK-PAIN-RAISIN','WHEAT_GLUTEN'),('BAK-PAIN-RAISIN','DAIRY'),('BAK-PAIN-RAISIN','EGG'),
('BAK-CASHEW-CROISSANT','WHEAT_GLUTEN'),('BAK-CASHEW-CROISSANT','DAIRY'),('BAK-CASHEW-CROISSANT','EGG'),('BAK-CASHEW-CROISSANT','TREE_NUTS'),
('BAK-CASHEW-PAIN-CHOC','WHEAT_GLUTEN'),('BAK-CASHEW-PAIN-CHOC','DAIRY'),('BAK-CASHEW-PAIN-CHOC','EGG'),('BAK-CASHEW-PAIN-CHOC','TREE_NUTS'),
('BAK-MAC-HOUJICHA','DAIRY'),('BAK-MAC-HOUJICHA','EGG'),('BAK-MAC-HOUJICHA','TREE_NUTS'),
('BAK-MAC-OOLONG','DAIRY'),('BAK-MAC-OOLONG','EGG'),('BAK-MAC-OOLONG','TREE_NUTS'),
('BAK-MAC-IRON-GODDESS','DAIRY'),('BAK-MAC-IRON-GODDESS','EGG'),('BAK-MAC-IRON-GODDESS','TREE_NUTS'),
('BAK-MAC-TRUFFLE','DAIRY'),('BAK-MAC-TRUFFLE','EGG'),('BAK-MAC-TRUFFLE','TREE_NUTS'),
('BAK-MAC-LONGJING','DAIRY'),('BAK-MAC-LONGJING','EGG'),('BAK-MAC-LONGJING','TREE_NUTS'),
('BAK-ENT-CAPUCINE','WHEAT_GLUTEN'),('BAK-ENT-CAPUCINE','DAIRY'),('BAK-ENT-CAPUCINE','EGG'),
('BAK-ENT-APOLLINE','WHEAT_GLUTEN'),('BAK-ENT-APOLLINE','DAIRY'),('BAK-ENT-APOLLINE','EGG'),
('BAK-ENT-LEONIE','WHEAT_GLUTEN'),('BAK-ENT-LEONIE','DAIRY'),('BAK-ENT-LEONIE','EGG'),
('BAK-ENT-SOLENE','WHEAT_GLUTEN'),('BAK-ENT-SOLENE','DAIRY'),('BAK-ENT-SOLENE','EGG'),
('BAK-ANTONIO-BLUEBERRY','WHEAT_GLUTEN'),('BAK-ANTONIO-BLUEBERRY','DAIRY'),('BAK-ANTONIO-BLUEBERRY','EGG'),
('DRK-LATTE','DAIRY'),('DRK-CAPPUCCINO','DAIRY'),('DRK-MOCHA','DAIRY'),('DRK-ICED-LATTE','DAIRY'),('DRK-HOT-CHOC','DAIRY'),
('RTL-MAC-BOX6','DAIRY'),('RTL-MAC-BOX6','EGG'),('RTL-MAC-BOX6','TREE_NUTS'),
('RTL-MAC-BOX12','DAIRY'),('RTL-MAC-BOX12','EGG'),('RTL-MAC-BOX12','TREE_NUTS'),
('RTL-MINI-CROISSANT8','WHEAT_GLUTEN'),('RTL-MINI-CROISSANT8','DAIRY'),('RTL-MINI-CROISSANT8','EGG'),
('RTL-MINI-RAISIN8','WHEAT_GLUTEN'),('RTL-MINI-RAISIN8','DAIRY'),('RTL-MINI-RAISIN8','EGG')
) AS v(sku, allergen_code)
JOIN products p ON p.sku=v.sku
JOIN allergens a ON a.allergen_code=v.allergen_code
ON CONFLICT (product_id, allergen_id) DO UPDATE SET is_confirmed=EXCLUDED.is_confirmed, notes=EXCLUDED.notes;
