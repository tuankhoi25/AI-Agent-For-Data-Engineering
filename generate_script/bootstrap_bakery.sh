#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$PROJECT_ROOT/.env"
COMPOSE_FILE="$PROJECT_ROOT/docker-compose.yml"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Không tìm thấy file .env: $ENV_FILE" >&2
  exit 1
fi
if [[ ! -f "$COMPOSE_FILE" ]]; then
  echo "Không tìm thấy docker-compose.yml: $COMPOSE_FILE" >&2
  exit 1
fi

# Preserve an explicitly exported host-side URL, then load the project's other settings.
EXPORTED_DATABASE_URL="${DATABASE_URL:-}"
set -a
source "$ENV_FILE"
set +a
if [[ -n "$EXPORTED_DATABASE_URL" ]]; then
  DATABASE_URL="$EXPORTED_DATABASE_URL"
fi
export DATABASE_URL

HISTORY_DAYS="${HISTORY_DAYS:-30}"
SIMULATOR_MAX_ORDERS="${SIMULATOR_MAX_ORDERS:-3}"
: "${POSTGRES_USER:?Thiếu POSTGRES_USER trong .env}"
: "${POSTGRES_DB:?Thiếu POSTGRES_DB trong .env}"
: "${DATABASE_URL:?Thiếu DATABASE_URL trong .env hoặc môi trường}"

if [[ -x "$PROJECT_ROOT/.venv/bin/python" ]]; then
  PYTHON_BIN="$PROJECT_ROOT/.venv/bin/python"
else
  PYTHON_BIN="${PYTHON:-python3}"
fi

"$PYTHON_BIN" - <<'PY'
import os
import sys
from urllib.parse import urlparse

host = urlparse(os.environ["DATABASE_URL"]).hostname
database = urlparse(os.environ["DATABASE_URL"]).path.lstrip("/")
if host not in {"localhost", "127.0.0.1"}:
    print(
        f"DATABASE_URL phải dùng host localhost hoặc 127.0.0.1; hiện tại host là {host!r}.",
        file=sys.stderr,
    )
    raise SystemExit(1)
if database != os.environ["POSTGRES_DB"]:
    print(
        "DATABASE_URL và POSTGRES_DB đang trỏ tới hai database khác nhau: "
        f"{database!r} != {os.environ['POSTGRES_DB']!r}.",
        file=sys.stderr,
    )
    raise SystemExit(1)
PY

compose=(docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE")
sql_dir="$PROJECT_ROOT/data_platform/postgres"
simulator_dir="$PROJECT_ROOT/generate_script"
schema_name="bakery"

if ! "${compose[@]}" exec -T postgres pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB" >/dev/null 2>&1; then
  echo "PostgreSQL chưa chạy hoặc chưa sẵn sàng. Hãy chạy docker compose up -d thành công trước khi bootstrap." >&2
  exit 1
fi

echo "Đang kiểm tra schema $schema_name..."
echo "Compose: $COMPOSE_FILE | PostgreSQL database: $POSTGRES_DB"

expected_bakery_tables=35
existing_bakery_tables="$("${compose[@]}" exec -T postgres \
  psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 -At \
  -c "SELECT count(*) FROM unnest(ARRAY[
    'branches', 'product_categories', 'units_of_measure', 'suppliers',
    'customers', 'employees', 'allergens', 'stock_items', 'products',
    'supplier_products', 'product_allergens', 'recipes', 'recipe_items',
    'purchase_orders', 'purchase_order_items', 'goods_receipts',
    'inventory_lots', 'goods_receipt_items', 'stock_movements',
    'production_batches', 'production_consumptions', 'promotions',
    'promotion_products', 'sales', 'sale_items', 'sale_promotions',
    'payments', 'loyalty_transactions', 'returns', 'return_items',
    'waste_records', 'shifts', 'cash_movements', 'simulation_runs', 'weather_daily'
  ]::text[]) AS expected(table_name)
  WHERE to_regclass(format('bakery.%I', expected.table_name)) IS NOT NULL;")"

if [[ "$existing_bakery_tables" -eq "$expected_bakery_tables" ]]; then
  echo "Đã có đủ $expected_bakery_tables bảng trong schema $schema_name; bỏ qua bước nạp lại SQL."
elif [[ "$existing_bakery_tables" -eq 0 ]]; then
  echo "Schema $schema_name chưa có bảng tiệm bánh; đang áp dụng bộ SQL khởi tạo..."
  for sql_file in "$sql_dir"/[0-9][0-9]_*.sql; do
    echo "Applying $(basename "$sql_file")"
    "${compose[@]}" exec -T postgres \
      psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
      -v ON_ERROR_STOP=1 --set "history_days=$HISTORY_DAYS" \
      < "$sql_file"
  done
else
  echo "Schema $schema_name chỉ có $existing_bakery_tables/$expected_bakery_tables bảng. Dừng để tránh nạp lại seed vào dữ liệu đang vận hành; hãy hoàn tất schema trước." >&2
  exit 1
fi

table_count="$("${compose[@]}" exec -T postgres \
  psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 -At \
  -c "SELECT count(*) FROM information_schema.tables WHERE table_schema = '$schema_name' AND table_type = 'BASE TABLE';")"
if [[ "$table_count" -eq 0 ]]; then
  echo "Bootstrap không tạo được bảng nào trong schema $schema_name (database: $POSTGRES_DB)." >&2
  exit 1
fi
echo "Đã tạo/nạp $table_count bảng trong schema $schema_name của database $POSTGRES_DB."

echo "Đang tạo ${HISTORY_DAYS} ngày lịch sử..."
"$PYTHON_BIN" "$simulator_dir/backfill_operations.py" \
  --days "$HISTORY_DAYS" \
  --max-orders "$SIMULATOR_MAX_ORDERS"

echo "Hoàn tất bootstrap và backfill."
