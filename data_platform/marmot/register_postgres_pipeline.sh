#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
ENV_FILE="$PROJECT_ROOT/.env"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Không tìm thấy file .env: $ENV_FILE" >&2
  exit 1
fi

set -a
source "$ENV_FILE"
set +a

: "${POSTGRES_HOST:?Thiếu POSTGRES_HOST trong .env}"
: "${POSTGRES_PORT:?Thiếu POSTGRES_PORT trong .env}"
: "${POSTGRES_DB:?Thiếu POSTGRES_DB trong .env}"
: "${POSTGRES_USER:?Thiếu POSTGRES_USER trong .env}"
: "${POSTGRES_PASSWORD:?Thiếu POSTGRES_PASSWORD trong .env}"
: "${MARMOT_API_KEY:?Thiếu MARMOT_API_KEY trong .env}"
: "${MARMOT_HOST:?Thiếu MARMOT_HOST trong .env}"

for command_name in curl jq; do
  if ! command -v "$command_name" >/dev/null 2>&1; then
    echo "Thiếu lệnh $command_name trong PATH." >&2
    exit 1
  fi
done

API_ROOT="${MARMOT_HOST%/}"
API_URL="$API_ROOT/api/v1/ingestion/schedules"
PIPELINE_NAME="bakery-postgres"
PIPELINE_TEMPLATE="$PROJECT_ROOT/data_platform/marmot/postgres-pipeline.json"

payload="$(jq \
  --arg name "$PIPELINE_NAME" \
  --arg host "$POSTGRES_HOST" \
  --arg database "$POSTGRES_DB" \
  --arg user "$POSTGRES_USER" \
  --arg password "$POSTGRES_PASSWORD" \
  --argjson port "$POSTGRES_PORT" \
  '.name = $name
   | .config.host = $host
   | .config.database = $database
   | .config.port = $port
   | .config.user = $user
   | .config.password = $password' \
  "$PIPELINE_TEMPLATE")"

headers=(
  --header "Authorization: Bearer $MARMOT_API_KEY"
  --header "Accept: application/json"
)

api_request() {
  local response status body safe_body

  if ! response="$(curl --silent --show-error --write-out $'\n%{http_code}' "$@")"; then
    echo "Không kết nối được Marmot API: $API_ROOT" >&2
    return 1
  fi

  status="${response##*$'\n'}"
  body="${response%$'\n'*}"
  if [[ ! "$status" =~ ^2[0-9]{2}$ ]]; then
    # Avoid printing credentials if the server happens to echo submitted config.
    if safe_body="$(jq -c 'walk(if type == "object" then del(.password, .api_key, .token) else . end)' <<< "$body" 2>/dev/null)"; then
      body="$safe_body"
    fi
    echo "Marmot API trả HTTP $status cho $API_URL" >&2
    if [[ -n "$body" ]]; then
      echo "Phản hồi: $body" >&2
    fi
    if [[ "$status" == "401" ]]; then
      cat >&2 <<'MESSAGE'
MARMOT_API_KEY bị server hiện tại từ chối. Nếu PostgreSQL/Marmot vừa chuyển sang
volume bakery_marmot_data mới, hãy tạo API key trong Marmot hiện tại rồi cập nhật
MARMOT_API_KEY trong .env. Không gửi API key vào chat.
MESSAGE
    fi
    if [[ "$body" == *"Failed to encrypt config"* ]]; then
      cat >&2 <<'MESSAGE'
Marmot Server không mã hóa được schedule config. Hãy kiểm tra lỗi chi tiết trong
log Marmot và xác nhận plugin của schedule đã được nạp. Không tạo key mới nếu
đã có credentials được lưu bằng key cũ.
MESSAGE
    fi
    return 1
  fi

  printf '%s' "$body"
}

PLUGIN_ID="$(jq -r '.plugin_id' "$PIPELINE_TEMPLATE")"
echo "Đang chờ plugin $PLUGIN_ID được Marmot nạp..."
plugin_ready=false
for attempt in {1..120}; do
  plugins="$(api_request "${headers[@]}" "$API_ROOT/api/v1/plugins")"
  if jq -e --arg id "$PLUGIN_ID" \
    '.loading == false and any(.plugins[]?; .id == $id)' \
    <<< "$plugins" >/dev/null; then
    plugin_ready=true
    break
  fi

  loading="$(jq -r '.loading // false' <<< "$plugins")"
  if [[ "$loading" == "false" ]]; then
    echo "Marmot đã nạp plugin xong nhưng không có plugin $PLUGIN_ID." >&2
    echo "Plugin hiện có: $(jq -r '[.plugins[]?.id] | join(", ")' <<< "$plugins")" >&2
    echo "Kiểm tra log Marmot để biết vì sao plugin PostgreSQL không được cài/nạp." >&2
    exit 1
  fi

  if (( attempt % 6 == 0 )); then
    echo "Plugin còn đang nạp; đã chờ $((attempt * 5)) giây..."
  fi
  sleep 5
done

if [[ "$plugin_ready" != true ]]; then
  echo "Hết thời gian chờ plugin $PLUGIN_ID. Kiểm tra log Marmot rồi chạy lại script." >&2
  exit 1
fi

echo "Đang kiểm tra scheduled pipeline $PIPELINE_NAME trên Marmot..."
schedules="$(api_request \
  "${headers[@]}" \
  "$API_URL?limit=1000&offset=0")"
matches="$(jq -c --arg name "$PIPELINE_NAME" \
  '[.schedules[]? | select(.name == $name)]' <<< "$schedules")"
match_count="$(jq 'length' <<< "$matches")"

if (( match_count > 1 )); then
  echo "Có nhiều schedule tên $PIPELINE_NAME; hãy xóa bản trùng trong Marmot rồi chạy lại." >&2
  exit 1
elif (( match_count == 1 )); then
  schedule_id="$(jq -r '.[0].id' <<< "$matches")"
  response="$(api_request \
    --request PUT \
    "${headers[@]}" \
    --header "Content-Type: application/json" \
    --data-binary "$payload" \
    "$API_URL/$schedule_id")"
  action="Đã cập nhật"
else
  response="$(api_request \
    --request POST \
    "${headers[@]}" \
    --header "Content-Type: application/json" \
    --data-binary "$payload" \
    "$API_URL")"
  action="Đã tạo"
fi

next_run="$(jq -r '.next_run_at // empty' <<< "$response")"
echo "$action scheduled pipeline $PIPELINE_NAME (cron: 0 2 * * 0)."
if [[ -n "$next_run" ]]; then
  echo "Lần chạy kế tiếp theo Marmot: $next_run"
fi
