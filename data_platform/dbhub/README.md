# DBHub management reporting tools

DBHub 1.4.0 connects to **Cube's PostgreSQL-compatible SQL API**, which queries
the bakery's modeled data in PostgreSQL. It does not connect directly to the
operational database. `dbhub.toml` contains the fixed, parameterized report SQL.
The assistant chooses a report and passes values instead of generating SQL for
every common question. All 13 custom tools are read-only.

The intended audience is stakeholders, branch managers and operations managers.

| Tool | Common management question | Output grain / limit |
| --- | --- | --- |
| `get_reporting_coverage` | Dữ liệu báo cáo đang có tới ngày nào? | Dataset; 7 rows |
| `get_sales_summary` | Doanh thu, số đơn, AOV, giảm giá và hoàn tiền kỳ này bao nhiêu? | Currency; 20 rows |
| `get_sales_comparison` | Tuần này so với tuần trước tăng giảm thế nào? | Period/currency; 40 rows |
| `get_sales_trend` | Doanh thu thay đổi theo từng ngày như thế nào? | Observed business day; 1000 rows |
| `get_branch_performance` | Chi nhánh nào có doanh thu cao nhất? | Branch identity/name/currency; 200 rows |
| `get_channel_performance` | Kênh bán nào đóng góp nhiều doanh thu? | Channel/currency; 100 rows |
| `get_product_performance` | Top 10 sản phẩm theo doanh thu sau hoàn tiền là gì? | Product/name/category/UOM; 100 rows |
| `get_customer_purchase_segments` | Bao nhiêu khách đã mua nhiều lần trong kỳ? | Within-period purchase segment/currency; 100 rows |
| `get_inventory_position` | Tồn kho hiện tại của từng nguyên liệu ở chi nhánh MAIN? | Branch/item/movement UOM; 200 rows |
| `get_inventory_expiry` | Lô nào đã hết hạn hoặc sắp hết hạn trong 7 ngày? | Positive-stock lot; 200 rows |
| `get_production_waste_summary` | Sản xuất đạt bao nhiêu so với kế hoạch, hao hụt ghi nhận bao nhiêu? | Branch/UOM; 200 rows |
| `get_procurement_backlog` | Dòng đơn mua nào chưa nhận đủ hoặc đã quá ngày giao? | Purchase-order line; 200 rows |
| `get_cash_variances` | Ca đã đóng nào thiếu/thừa tiền vượt 10.000 đồng? | Closed, counted shift; 200 rows |

Example tool arguments:

```json
{"start_date":"2026-10-12","end_date":"2026-10-21","branch_code":"MAIN"}
```

Use those arguments for `get_sales_summary`. Dates are **inclusive local business
dates** in Asia/Ho_Chi_Minh; reject reversed ranges. Optional branch/item codes
default to `""` (all). A filtered query with no rows is not proof of zero business
activity. A fixed SQL row cap is intentional: Cube's prepared SQL planner does
not support a computed/parameterized LIMIT. For top 10 products the tool returns
up to 100 ranked rows; the assistant presents the first 10. At a cap, disclose
possible truncation or narrow the scope. A top-N list cannot establish a full
company total, category total or all exceptions.

## Metric contracts

- Sales summary, comparison, branch/channel performance and customer segments
  use one-row-per-receipt `fct_sales`, completed and not deleted, with currencies
  separated. Receipt revenue includes tax; after-refund revenue subtracts
  completed-return refunds attributed to the **original sale date**. These are
  not refund-event-date reports or profit/P&L reports. Weighted average ticket is
  total original receipt revenue / total orders.
- Trend and product tools use `mart_daily_sales` / `mart_product_sales`, which
  have no currency column. The agent must first confirm single-currency VND
  scope with `get_sales_summary`; mixed currency requires fact-based analysis.
  Product-line revenue differs from receipt revenue: receipt-level adjustments
  and tax are not allocated here. Names/categories can split a product/branch
  across historical SCD versions. Product quantities remain separated by unit.
- Repeat purchase means 2+ receipts **within the requested window**. It does not
  mean lifetime retention or new/returning customers. Anonymous receipts cannot
  be deduplicated into people; their identified-customer count is zero.
- Inventory is the current materialized snapshot, not historical stock. Its
  `as_of_date` must be shown if stale. Available quantity was classified at that
  snapshot date. The expiry tool reclassifies existing positive-stock lots at
  `reference_date`, includes already-expired lots and lots expiring through
  `reference_date + days_ahead`, and follows the mart rule that a lot is expired
  **after** its expiry date. It does not reconstruct historical inventory.
- Production durations are weighted by completed batch counts, excluding null
  durations. Quantities stay separated by UOM. Recorded waste covers stock items
  beyond the produced output; dividing it by output does not establish waste rate.
- Procurement reports current outstanding line quantities using same-unit
  receipts. Canceled/draft lines are excluded. Mismatched receipt units must be
  flagged as provisional quantities. `overdue_only` defaults to true; overdue is
  evaluated at the **end** of `reference_date`. Use yesterday for overdue as of
  the start of today, or ad hoc timestamp SQL for overdue right now. Setting
  `overdue_only=false` includes unknown delivery dates. This is not past status,
  accounts payable or a supplier quality score.
- Cash variance is counted cash minus expected cash on closed, counted shifts;
  positive is surplus and negative is shortage. Tolerance is an absolute VND
  amount; opposite signs are not netted away. Open/uncounted shifts are excluded.
- Coverage's source-change timestamp is not ETL completion time. Missing dates
  stay missing. Do not silently substitute a different reporting period.

## Agent integration and reload

The UI agent discovers all DBHub tools in `agent/main.py` at startup. Its prompt
and shared `skills/dbhub-sql/SKILL.md` prefer named tools for covered reports.
Marmot remains the business knowledge base; Cube REST / DBHub `execute_sql`
remain available for questions outside these tools' scope.

DBHub watches its mounted TOML and hot reloads it. The agent must be recreated
to discover added/removed tools; prompt changes need its image rebuilt:

```bash
docker compose up -d --no-deps --build bakery_agent
```

No automatic report SQL generator or extra service is involved.

## Verification

From the repository root with root requirements installed:

```bash
./.venv/bin/python -m unittest discover -s data_platform/dbhub/test -v
# Opt-in read-only integration against the running stack; no LLM calls:
./.venv/bin/python data_platform/dbhub/test/smoke_reporting_tools.py
```

Use `--url http://localhost:PORT/mcp` if the DBHub port differs. Integration checks
all 13 tools, optional parameters, filters, an inclusive one-day range, empty
periods and sales totals across branch/channel/customer/trend reports. Fixture
tests check refunds, currencies, date/status exclusion, anonymous customers,
batch-weighted duration, cash tolerance and expiry-day classification.

Validated on 2026-10-23: 13 isolated fixture tests passed, all 13 tools executed
successfully through live DBHub/Cube, and the running agent discovered them.
Two real-model Vietnamese management questions selected `get_sales_summary`
and `get_inventory_expiry` respectively, without `execute_sql` or
`run_cube_query`. The expiry answer disclosed the snapshot date and kept
incompatible units separate. Real-model conversation checks consume API usage;
the integration script above does not call an LLM.
