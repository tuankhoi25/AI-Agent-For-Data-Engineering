"""Execute the actual report SQL against isolated fixtures, without Docker or APIs."""
import tomllib
import unittest
from pathlib import Path

import duckdb


TOOLS = {t['name']: t for t in tomllib.loads(
    (Path(__file__).parents[1] / 'dbhub.toml').read_text())['tools']}


class ReportingMetricsTests(unittest.TestCase):
    def setUp(self):
        self.db = duckdb.connect(':memory:')
        self.db.execute('''CREATE TABLE fct_sales (
          business_date DATE, branch_id INT, branch_code VARCHAR, branch_name VARCHAR,
          currency_code VARCHAR, customer_id INT, channel VARCHAR,
          is_sale_completed BOOLEAN, _is_deleted BOOLEAN, subtotal DECIMAL(18,2),
          discount_total DECIMAL(18,2), tax_total DECIMAL(18,2), total_amount DECIMAL(18,2),
          refund_amount DECIMAL(18,2), revenue_after_refund DECIMAL(18,2),
          collected_payment_amount DECIMAL(18,2))''')
        # One customer repeats, one buys once, one receipt is anonymous.
        # Different currencies, a different branch, excluded states and date boundaries.
        rows = [
            ('2026-10-01', 1, 'MAIN', 'Main', 'VND', 1, 'IN_STORE', True, False, 100, 0, 0, 100, 0, 100, 100),
            ('2026-10-02', 1, 'MAIN', 'Main', 'VND', 1, 'IN_STORE', True, False, 400, 0, 0, 400, 50, 350, 400),
            ('2026-10-02', 1, 'MAIN', 'Main', 'VND', None, 'DELIVERY', True, False, 200, 0, 0, 200, 0, 200, 200),
            ('2026-10-02', 1, 'MAIN', 'Main', 'VND', 2, 'DELIVERY', True, False, 300, 0, 0, 300, 0, 300, 300),
            ('2026-10-02', 2, 'OTHER', 'Other', 'VND', 3, 'IN_STORE', True, False, 500, 0, 0, 500, 0, 500, 500),
            ('2026-10-02', 1, 'MAIN', 'Main', 'USD', 4, 'IN_STORE', True, False, 10, 0, 0, 10, 0, 10, 10),
        ]
        for day, complete, deleted in [('2026-09-30', True, False), ('2026-10-03', True, False),
                                        ('2026-10-02', False, False), ('2026-10-02', True, True)]:
            rows.append((day, 1, 'MAIN', 'Main', 'VND', 9, 'IN_STORE', complete, deleted,
                         9999, 0, 0, 9999, 0, 9999, 9999))
        self.db.executemany('INSERT INTO fct_sales VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)', rows)

    def tearDown(self):
        self.db.close()

    def report(self, name, **kwargs):
        tool = TOOLS[name]
        values = {str(i): kwargs[p['name']] if p['name'] in kwargs else p['default']
                  for i, p in enumerate(tool.get('parameters', []), 1)}
        result = self.db.execute(tool['statement'], values)
        columns = [col[0] for col in result.description]
        return [dict(zip(columns, row)) for row in result.fetchall()]

    def sales(self, name='get_sales_summary', **kwargs):
        return self.report(name, start_date='2026-10-01', end_date='2026-10-02', **kwargs)

    def test_inclusive_dates_status_refunds_and_currency_separation(self):
        rows = {r['currency_code']: r for r in self.sales(branch_code='MAIN')}
        self.assertEqual(rows['VND']['order_count'], 4)
        self.assertEqual(rows['VND']['receipt_revenue'], 1000)
        self.assertEqual(rows['VND']['net_revenue_after_refund'], 950)
        self.assertEqual(rows['USD']['receipt_revenue'], 10)
        self.assertEqual(rows['VND']['average_ticket'], 250)

    def test_unknown_and_injection_shaped_branch_do_not_expand_scope(self):
        self.assertEqual(self.sales(branch_code="MAIN' OR 1=1 --"), [])
        self.assertEqual(self.sales(branch_code='UNKNOWN'), [])

    def test_missing_period_is_missing_not_a_zero_revenue_row(self):
        self.assertEqual(self.report('get_sales_summary', start_date='2025-01-01', end_date='2025-01-31'), [])
        with self.assertRaises(duckdb.ConversionException):
            self.report('get_sales_summary', start_date='invalid-date', end_date='2026-10-02')

    def test_comparison_preserves_overlapping_periods_and_missing_baseline(self):
        rows = self.sales('get_sales_comparison', branch_code='MAIN',
                          previous_start_date='2026-10-01', previous_end_date='2026-10-01')
        prior = [r for r in rows if r['period'] == 'previous']
        self.assertEqual(len(prior), 1)
        self.assertEqual(prior[0]['receipt_revenue'], 100)

    def test_branch_and_channel_totals_reconcile_to_summary(self):
        summary = {r['currency_code']: r for r in self.sales()}
        for name in ('get_branch_performance', 'get_channel_performance'):
            rows = self.sales(name)
            for currency, expected in summary.items():
                self.assertEqual(sum(r['receipt_revenue'] for r in rows if r['currency_code'] == currency),
                                 expected['receipt_revenue'])

    def test_repeat_segments_do_not_count_anonymous_receipts_as_people(self):
        segments = {r['segment']: r for r in self.sales('get_customer_purchase_segments', branch_code='MAIN')
                    if r['currency_code'] == 'VND'}
        self.assertEqual(segments['identified_repeat_in_period']['identified_customer_count'], 1)
        self.assertEqual(segments['identified_repeat_in_period']['order_count'], 2)
        self.assertEqual(segments['anonymous']['identified_customer_count'], 0)
        self.assertEqual(segments['anonymous']['order_count'], 1)
        self.assertEqual(segments['identified_one_order']['identified_customer_count'], 1)

    def test_cash_variance_tolerance_counts_opposite_signs_separately(self):
        self.db.execute('''CREATE TABLE mart_cash_reconciliation AS
            SELECT 1 AS shift_id, 'S1' AS shift_code, 'MAIN' AS branch_code, 'Main' AS branch_name,
            DATE '2026-10-01' AS business_date, 'E1' AS employee_code, 'CLOSED' AS status,
            100 AS opening_cash, 200 AS cash_in_amount, 0 AS cash_out_amount,
            300 AS expected_ending_cash, 290 AS counted_cash, -10 AS cash_variance
            UNION ALL SELECT 2,'S2','MAIN','Main',DATE '2026-10-02','E2','CLOSED',100,200,0,300,310,10
            UNION ALL SELECT 3,'S3','MAIN','Main',DATE '2026-10-02','E3','OPEN',100,200,0,300,NULL,NULL''')
        rows = self.sales('get_cash_variances', tolerance=5)
        self.assertEqual({r['cash_variance'] for r in rows}, {-10, 10})
        self.assertEqual(self.sales('get_cash_variances', tolerance=10), [])

    def test_expiry_uses_snapshot_and_includes_expiry_day_without_negative_stock(self):
        self.db.execute('''CREATE TABLE mart_inventory_position AS
            SELECT DATE '2026-10-01' AS as_of_date, 'MAIN' AS branch_code, 'Main' AS branch_name,
            'FLOUR' AS stock_item_code, 'Flour' AS stock_item_name, 1 AS inventory_lot_id,
            'L1' AS lot_code, 'G' AS movement_uom_code, 100 AS on_hand_quantity,
            DATE '2026-10-01' AS expires_at
            UNION ALL SELECT DATE '2026-10-01','MAIN','Main','FLOUR','Flour',2,'L2','G',20,DATE '2026-10-02'
            UNION ALL SELECT DATE '2026-10-01','MAIN','Main','FLOUR','Flour',3,'L3','G',10,DATE '2026-10-03'
            UNION ALL SELECT DATE '2026-10-01','MAIN','Main','FLOUR','Flour',4,'L4','G',-10,DATE '2026-10-01' ''')
        rows = self.report('get_inventory_expiry', reference_date='2026-10-02', days_ahead=0)
        self.assertEqual([(r['lot_code'], r['expiry_status']) for r in rows],
                         [('L1', 'expired'), ('L2', 'expiring_soon')])

    def test_operations_keeps_units_and_weights_duration_by_batch_count(self):
        self.db.execute('''CREATE TABLE mart_daily_operations AS
            SELECT DATE '2026-10-01' AS business_date, 'MAIN' AS branch_code, 'Main' AS branch_name,
            'EA' AS uom_code, 1 AS completed_batch_count, 10 AS planned_output_quantity,
            9 AS produced_output_quantity, 10 AS avg_production_duration_minutes,
            1 AS waste_record_count, 1 AS wasted_quantity
            UNION ALL SELECT DATE '2026-10-02','MAIN','Main','EA',3,30,27,30,0,0
            UNION ALL SELECT DATE '2026-10-02','MAIN','Main','G',0,NULL,NULL,NULL,1,500''')
        rows = {r['uom_code']: r for r in self.sales('get_production_waste_summary')}
        self.assertEqual(rows['EA']['batch_weighted_duration_minutes'], 25)
        self.assertEqual(rows['EA']['output_attainment_pct'], 90)
        self.assertEqual(rows['G']['wasted_quantity'], 500)
        self.assertIsNone(rows['G']['output_attainment_pct'])

    def test_trend_weights_tickets_instead_of_averaging_branch_averages(self):
        self.db.execute('''CREATE TABLE mart_daily_sales AS
            SELECT DATE '2026-10-01' AS business_date, 'MAIN' AS branch_code, 1 AS order_count,
            100 AS receipt_revenue, 0 AS discount_amount, 0 AS refund_amount, 100 AS net_revenue_after_refund
            UNION ALL SELECT DATE '2026-10-01','OTHER',9,2700,0,0,2700''')
        row = self.sales('get_sales_trend')[0]
        self.assertEqual(row['order_count'], 10)
        self.assertEqual(row['average_ticket'], 280)

    def test_product_ranking_keeps_units_and_line_revenue_distinct(self):
        self.db.execute('''CREATE TABLE mart_product_sales AS
            SELECT DATE '2026-10-01' AS business_date, 'MAIN' AS branch_code,
            1 AS product_id, 'P1' AS sku, 'Product' AS product_name, 'BAKERY' AS category_code,
            'Bakery' AS category_name, 'EA' AS uom_code, 10 AS sold_quantity, 1 AS returned_quantity,
            9 AS net_quantity, 100 AS gross_sales, 10 AS line_discount_amount,
            10 AS refund_amount, 80 AS net_line_sales_after_refund
            UNION ALL SELECT DATE '2026-10-02','MAIN',1,'P1','Product','BAKERY','Bakery','BOX',2,0,2,200,0,0,200''')
        rows = self.sales('get_product_performance')
        self.assertEqual([r['uom_code'] for r in rows], ['BOX', 'EA'])
        self.assertEqual(rows[1]['net_quantity'], 9)
        self.assertEqual(rows[1]['net_line_sales_after_refund'], 80)

    def test_inventory_keeps_signed_and_usable_stock_separate(self):
        self.db.execute('''CREATE TABLE mart_inventory_position AS
            SELECT 'MAIN' AS branch_code, 'Main' AS branch_name, 1 AS stock_item_id,
            'FLOUR' AS stock_item_code, 'Flour' AS stock_item_name, 'G' AS movement_uom_code,
            DATE '2026-10-01' AS as_of_date, 100 AS on_hand_quantity,
            100 AS positive_on_hand_quantity, 0 AS available_quantity
            UNION ALL SELECT 'MAIN','Main',1,'FLOUR','Flour','G',DATE '2026-10-01',-20,0,0
            UNION ALL SELECT 'MAIN','Main',1,'FLOUR','Flour','G',DATE '2026-10-01',50,50,50''')
        row = self.report('get_inventory_position')[0]
        self.assertEqual((row['on_hand_quantity'], row['positive_on_hand_quantity'], row['available_quantity']),
                         (130, 150, 50))
        self.assertEqual(row['negative_lot_count'], 1)

    def test_procurement_cutoff_unknown_dates_and_mismatched_units(self):
        self.db.execute('''CREATE TABLE mart_procurement_status AS
            SELECT 1 AS purchase_order_item_id, 1 AS purchase_order_id, 'PO1' AS po_number,
            'ORDERED' AS purchase_order_status, 'SUP1' AS supplier_code, 'Supplier' AS supplier_name,
            'MAIN' AS branch_code, 'FLOUR' AS stock_item_code, 'Flour' AS stock_item_name,
            'G' AS ordered_uom_code, 100 AS ordered_quantity, 20 AS received_quantity_same_uom,
            80 AS remaining_quantity_same_uom, 1 AS unit_mismatch_receipt_line_count,
            'VND' AS currency_code, 1000 AS expected_line_amount, 200 AS actual_received_amount,
            TIMESTAMP '2026-10-02 23:59:59' AS expected_at, TIMESTAMP '2026-10-01' AS _record_updated_at
            UNION ALL SELECT 2,2,'PO2','CANCELLED','SUP1','Supplier','MAIN','FLOUR','Flour','G',100,0,100,0,'VND',1000,0,TIMESTAMP '2026-10-01',TIMESTAMP '2026-10-01'
            UNION ALL SELECT 3,3,'PO3','ORDERED','SUP1','Supplier','MAIN','FLOUR','Flour','G',100,0,100,0,'VND',1000,0,NULL,TIMESTAMP '2026-10-01'
            UNION ALL SELECT 4,4,'PO4','ORDERED','SUP1','Supplier','MAIN','FLOUR','Flour','G',100,0,100,0,'VND',1000,0,TIMESTAMP '2026-10-03',TIMESTAMP '2026-10-01' ''')
        rows = self.report('get_procurement_backlog', reference_date='2026-10-02')
        self.assertEqual([r['po_number'] for r in rows], ['PO1'])
        self.assertEqual(rows[0]['unit_mismatch_receipt_line_count'], 1)
        all_rows = self.report('get_procurement_backlog', reference_date='2026-10-02', overdue_only=False)
        self.assertEqual([r['po_number'] for r in all_rows], ['PO1', 'PO4', 'PO3'])


if __name__ == '__main__':
    unittest.main()
