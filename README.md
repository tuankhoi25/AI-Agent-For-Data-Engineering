# Bakery data platform

Data platform cho tiệm bánh Maison Douce: PostgreSQL lưu dữ liệu vận hành,
dbt xây dựng analytics, Dagu điều phối pipeline, Marmot quản lý metadata và
lineage, Cube/DBHub phục vụ truy vấn cho trợ lý phân tích.

```text
SQL seed + simulator + Open-Meteo
  → bakery → analytics_staging → analytics_core → analytics_mart
                                                     ↓
                                                Cube / DBHub → Assistant

PostgreSQL ingestion + dbt artifacts + Dagu metadata → Marmot
```

Thực hiện các bước dưới đây trong **cùng một terminal**, tại thư mục gốc repo.
Chờ mỗi tác vụ thành công trước khi chuyển sang bước phụ thuộc.

## 1. Chuẩn bị môi trường

Cần Docker Desktop đang chạy, Docker Compose, Python 3.12, `curl` và `jq`.

```bash
# Mở terminal tại thư mục repo sau khi clone, ví dụ: cd Bakery

# Tạo cấu hình local nếu chưa có; không ghi đè cấu hình đang dùng.
if [ ! -f .env ]; then
  cp .env.example .env
fi

# Chỉ tạo virtual environment nếu chưa có .venv.
if [ ! -x .venv/bin/python ]; then
  python3.12 -m venv .venv
fi
./.venv/bin/python -m pip install -r requirements.txt

# Nạp cấu hình cho các lệnh API và Python chạy trên máy host.
set -a
source ./.env
set +a

MARMOT_API_BASE="${MARMOT_HOST%/}/api/v1"
DAGU_API_BASE="http://localhost:${DAGU_HOST_PORT:-8088}/api/v1"

docker info
docker compose --env-file .env -f docker-compose.yml config --quiet
```

Kiểm tra các nhóm cấu hình trong `.env`:

Điền password, API key và model của bạn trong `.env`. Tạo encryption key cho
Marmot bằng `openssl rand -base64 32`; các password/secret khác có thể tạo bằng
`openssl rand -hex 24`. `.env.example` chỉ chứa placeholder; không dùng nguyên
các giá trị `replace_with_*` để vận hành. API key Marmot được tạo sau khi
instance Marmot đầu tiên sẵn sàng, trước khi bật các dịch vụ sử dụng key đó.

| Nhóm | Biến và cách sử dụng |
|---|---|
| PostgreSQL trong Docker | `POSTGRES_HOST=postgres`, `POSTGRES_PORT=5432`, `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`. |
| PostgreSQL từ máy host | `DATABASE_URL` dùng `localhost` hoặc `127.0.0.1`, cổng `POSTGRES_HOST_PORT`, cùng database với `POSTGRES_DB`. |
| Marmot | `MARMOT_HOST` là URL từ máy host, `MARMOT_HOST_PORT`, `MARMOT_API_KEY`, `MARMOT_ENCRYPTION_KEY`. |
| Dữ liệu giả lập | `HISTORY_DAYS` chọn khoảng lịch sử; `SIMULATOR_MAX_ORDERS` chọn mức đơn nền cho bootstrap. Đặt trước lần khởi tạo database đầu tiên. |
| Trợ lý và semantic layer | `OPENAI_API_KEY`, `BAKERY_AGENT_MODEL` và các biến `CUBEJS_*`, `DBHUB_*`, `MCP_SERVER_HOST_PORT`, `ASSISTANT_UI_HOST_PORT`, `BAKERY_AGENT_HOST_PORT`. |

Phân biệt địa chỉ từ máy host (`localhost` và cổng publish) với địa chỉ giữa
các container (`postgres:5432`, `marmot:8080`). Giữ nguyên encryption key của
Marmot khi sử dụng lại database đã lưu credentials.

## 2. Khởi động PostgreSQL và Marmot

Với lần dựng platform đầu tiên, khởi động hai dịch vụ nền trước; Dagu và các
dịch vụ truy vấn/trợ lý được bật ở các bước sau khi dữ liệu đã sẵn sàng.

```bash
docker compose --env-file .env -f docker-compose.yml up -d --build postgres marmot
docker compose ps postgres marmot
docker compose logs --tail 100 postgres marmot
```

Đợi PostgreSQL báo `healthy`, rồi mở Marmot tại `MARMOT_HOST`
(cấu hình hiện tại: <http://localhost:8085>). Nếu là database Marmot mới,
tạo API key trong Marmot và cập nhật `MARMOT_API_KEY` trong `.env`, sau đó nạp lại:

```bash
set -a
source ./.env
set +a
MARMOT_API_BASE="${MARMOT_HOST%/}/api/v1"
```

Trên volume PostgreSQL mới, các file SQL đánh số trong `data_platform/postgres/`
tự chạy để tạo schema, bảng, trigger và seed khai trương. Schema `bakery` có
35 bảng: 34 bảng có audit/soft delete và bảng điều khiển `simulation_runs`.

## 3. Generate dữ liệu nghiệp vụ

### Bootstrap và tạo lịch sử lần đầu

```bash
bash generate_script/bootstrap_bakery.sh
```

Script kiểm tra đủ 35 bảng, bỏ qua việc nạp lại SQL nếu schema đã đầy đủ,
rồi backfill `HISTORY_DAYS` ngày đến hôm qua với mức đơn nền
`SIMULATOR_MAX_ORDERS`. Các ngày đã hoàn tất được bỏ qua để tránh tạo trùng.
Nếu schema chỉ có một phần số bảng, script dừng để tránh replay seed vào dữ
liệu hiện có. SQL khởi tạo không tự chạy lại trên volume đã có dữ liệu.

### Tạo thêm hoạt động hôm nay

```bash
./.venv/bin/python generate_script/simulate_operations.py --max-orders 100
```

`--max-orders` là mức đơn nền cho một lượt mô phỏng; số đơn thực tế còn phụ
thuộc thời tiết, lịch và tồn kho. Simulator dùng giờ thật từ database, chỉ tạo
bán hàng/sản xuất trong khung 07:00–trước 22:00 theo giờ chi nhánh, không tạo
giao dịch tương lai. Chạy lại có thể tạo thêm nghiệp vụ.

### Backfill một khoảng lịch sử khác khi cần

```bash
# Mặc định kết thúc vào hôm qua; các ngày đã hoàn tất vẫn được bỏ qua.
./.venv/bin/python generate_script/backfill_operations.py \
  --days 20 --run-time 11:00 --max-orders 100
```

Có thể thêm `--end-date YYYY-MM-DD` để chọn ngày cuối cụ thể. Phạm vi phải phù
hợp với ngày mở bán của chi nhánh. Bootstrap và generate nghiệp vụ chạy thủ
công, bên ngoài các DAG; hoàn tất việc tạo dữ liệu trước khi chạy dbt.

## 4. Tạo PostgreSQL pipeline trong Marmot và trigger sync qua API

### Đăng ký pipeline

```bash
bash data_platform/marmot/register_postgres_pipeline.sh
```

Script chờ Marmot load xong plugin PostgreSQL rồi tạo/cập nhật schedule tên
**`bakery-postgres`**, dùng `.env` và `data_platform/marmot/postgres-pipeline.json`.
Lịch đăng ký là `0 2 * * 0`. **Đăng ký schedule chưa chạy ingestion ngay**;
trigger lần đầu để các bảng và cột nguồn xuất hiện trong catalog.

### Lấy schedule ID và gọi trigger

```bash
POSTGRES_SCHEDULE_ID="$(
  curl --fail --silent --show-error \
    -H "Authorization: Bearer ${MARMOT_API_KEY}" \
    "${MARMOT_API_BASE}/ingestion/schedules?limit=1000&offset=0" \
  | jq -er '
      [.schedules[] | select(.name == "bakery-postgres")]
      | if length == 1 then .[0].id
        else error("Can dung mot schedule bakery-postgres; kiem tra buoc dang ky")
        end'
)"

POSTGRES_SYNC_RUN_ID="$(
  curl --fail --silent --show-error -X POST \
    -H "Authorization: Bearer ${MARMOT_API_KEY}" \
    "${MARMOT_API_BASE}/ingestion/schedules/${POSTGRES_SCHEDULE_ID}/trigger" \
  | jq -er '.id'
)"

printf 'PostgreSQL sync run ID: %s\n' "$POSTGRES_SYNC_RUN_ID"
```

API trả về ingestion run; lấy trường `id` để theo dõi đúng lần chạy:

```bash
curl --fail --silent --show-error \
  -H "Authorization: Bearer ${MARMOT_API_KEY}" \
  "${MARMOT_API_BASE}/ingestion/runs/${POSTGRES_SYNC_RUN_ID}" \
  | jq '{id, status, error}'
```

Gọi lại lệnh GET khi run còn chờ/đang chạy. Chỉ sang bước enrich khi `status`
là `succeeded`, `completed` hoặc `success`. Nếu `failed`/`cancelled`, xem lỗi
trong Marmot trước. Có thể theo dõi cùng run trên giao diện ingestion của Marmot.
Pipeline nguồn đưa 34 bảng nghiệp vụ vào catalog, loại `simulation_runs`.

## 5. Enrich Marmot cho các bảng nguồn

Sau khi PostgreSQL ingestion thành công:

```bash
# Kiểm tra định nghĩa và asset trước khi ghi.
./.venv/bin/python data_platform/marmot/enrich_bakery_metadata.py --dry-run

# Ghi mô tả nghiệp vụ, cột, glossary, data products và documentation.
./.venv/bin/python data_platform/marmot/enrich_bakery_metadata.py
```

Script này enrich asset của schema **`bakery`**. Nếu báo thiếu bảng hoặc cột,
kiểm tra PostgreSQL sync ở bước 4 đã hoàn tất và lấy đúng schema mới. Khi chạy
lại ingestion nguồn về sau, chạy lại enrichment để cập nhật các định nghĩa.

## 6. Khởi động Dagu và lấy dữ liệu thời tiết

```bash
docker compose --env-file .env -f docker-compose.yml up -d --build dagu
docker compose ps dagu

curl --fail --silent --show-error "${DAGU_API_BASE}/health"
```

Mở Dagu UI tại <http://localhost:8088> (hoặc cổng `DAGU_HOST_PORT`). Đợi Dagu
healthy trước khi gọi enqueue. Dagu hiện dùng chế độ local `auth.mode: none`,
cổng chỉ bind `127.0.0.1`.

Trigger weather DAG để lấy 7 ngày hoàn chỉnh gần nhất từ Open-Meteo vào
`bakery.weather_daily`:

```bash
curl --fail --silent --show-error -X POST \
  "${DAGU_API_BASE}/dags/weather-daily/enqueue" \
  -H 'Content-Type: application/json' -d '{}' | jq

curl --fail --silent --show-error \
  "${DAGU_API_BASE}/dags/weather-daily/dag-runs" \
  | jq '.dagRuns[:5] | map({dagRunId, status: .statusLabel, startedAt, finishedAt})'
```

**Chờ run vừa enqueue chuyển sang `succeeded`** trước khi chạy dbt. Muốn lấy
thời tiết cho khoảng backfill dài hơn, khi queue Dagu trống có thể chạy collector
riêng; ví dụ lấy 30 ngày thay vì mặc định 7 ngày:

```bash
docker compose exec -T dagu python data_platform/weather/collect_daily_weather.py --days 30
```

Collector hỗ trợ thêm `--start-date YYYY-MM-DD` và `--end-date YYYY-MM-DD`.
Lệnh collector riêng ghi dữ liệu weather; chạy xong rồi mới enqueue ETL.

## 7. Chạy pipeline dbt staging → core → mart

Hằng đêm, các DAG thành phần được schedule riêng và chạy cách nhau để phân
bố tải bộ nhớ; xem lịch ở mục 10. Không còn DAG cha gom toàn bộ pipeline.
Khi chạy thủ công, enqueue từng DAG theo dependency và chờ mỗi run
`succeeded` trước khi enqueue DAG tiếp theo. Mỗi DAG dbt tự có chuỗi task
`dbt run → dbt test → publish → metadata`; mỗi DAG tự cập nhật metadata Dagu lên Marmot.

```text
source_core (preflight → staging → core → snapshots → holiday seed → test → publish)
  ├─ dimensions_reference → dimensions_products ─┐
  └─ dimensions_parties ────────────────────────┤
       ├─ facts_sales → marts_sales             │
       ├─ facts_weather (sau dimensions_reference)
       └─ marts_operations (sau parties/products)
  → metadata task trong từng DAG (Dagu graph + run history → Marmot)
```

- Staging lưu phiên bản nguồn, bao gồm tombstone; core cập nhật incremental.
- Mart gồm 12 dimensions SCD2, `dim_date` Type 0, 3 facts và 7 reporting marts.
  Calendar dùng seed ngày lễ Việt Nam; weather fact liên kết qua `date_sk`.
- dbt dùng adapter PostgreSQL. Các bảng nằm trong `analytics_staging`,
  `analytics_core`, `analytics_mart`; không có file database DuckDB riêng.
- Các quality check liên DAG như DuckDB parity và deep audit không còn nằm trong
  lịch component; chạy thủ công khi cần kiểm tra toàn hệ thống.
- Sau mỗi task `publish`, component bundle được ingest ngay vào Marmot. Task
  `metadata` kế tiếp đồng bộ DAG, task, dependency, schedule và run history
  lên Marmot. Không còn quality gate liên DAG tự động hoặc aggregate artifact.
- Lịch riêng dùng chung batch `daily-YYYY-MM-DD`; các job sau nửa đêm vẫn
  thuộc batch tối hôm trước đến 06:00. DAG con kiểm tra upstream thành công
  trong đúng batch trước khi ghi. DAG cha thủ công dùng run ID của cha làm
  batch ID cho tất cả DAG con.
- dbt mặc định `DBT_THREADS=1`, queue `bakery` chỉ chạy một DAG một lúc.
  Cấu hình, model thuộc từng DAG và cách chạy lại:
  [Dagu workflows](data_platform/dagu/README.md).

Không chạy manual runner hoặc dbt trực tiếp song song với Dagu. Nếu thay source
hoặc code sau một run lỗi, enqueue batch mới đầy đủ. Generate dữ liệu không phải
một phase của pipeline này.

## 8. Enrich mart thủ công

Các DAG component đã tự publish dbt assets và metadata Dagu. Khi cần cập nhật
mô tả nghiệp vụ, grain, keys, SCD type hoặc documentation cho 23 bảng trong
**`analytics_mart`**, chạy script thủ công:

```bash
./.venv/bin/python data_platform/marmot/enrich_bakery_mart_metadata.py --dry-run
./.venv/bin/python data_platform/marmot/enrich_bakery_mart_metadata.py
```

Phân biệt hai script: `enrich_bakery_metadata.py` dành cho bảng nguồn `bakery`;
`enrich_bakery_mart_metadata.py` dành cho các model `analytics_mart`.
Nếu báo `Missing analytics_mart assets`, kiểm tra các DAG `marts-*` đã publish
thành công trước khi chạy enrichment.

## 9. Bật toàn bộ platform và mở trợ lý

```bash
docker compose --env-file .env -f docker-compose.yml up -d --build
docker compose ps
```

Lệnh này khởi động thêm Cube API/refresh worker, CubeStore, DBHub, MCP server,
agent và frontend. Khi `bakery_agent` và `assistant_ui` healthy, mở giao diện:

| Dịch vụ | Địa chỉ từ máy host |
|---|---|
| Bakery assistant | <http://localhost:3000> — `ASSISTANT_UI_HOST_PORT` |
| Marmot | <http://localhost:8085> — `MARMOT_HOST_PORT` |
| Dagu | <http://localhost:8088> — `DAGU_HOST_PORT`, mặc định 8088 |
| Cube | <http://localhost:4000> — `CUBEJS_HOST_PORT` |
| Bakery MCP | <http://localhost:8001/mcp> — `MCP_SERVER_HOST_PORT` |
| DBHub MCP | <http://localhost:8086/mcp> — `DBHUB_HOST_PORT` |

Các địa chỉ trên tương ứng cấu hình hiện tại; nếu đổi `.env`, dùng cổng mới.
Cube/DBHub truy vấn qua semantic layer; cache/rollup có chu kỳ refresh một phút,
nên số liệu mới có thể chưa xuất hiện ngay sau khi ETL commit.

## 10. Vận hành hằng ngày và khởi động lại

Khi dữ liệu đã được khởi tạo, bật lại toàn bộ dịch vụ bằng
`docker compose --env-file .env -f docker-compose.yml up -d`;
không cần bootstrap lại mỗi lần restart. Lịch Dagu dùng `Asia/Ho_Chi_Minh`:

| DAG | Lịch | Công việc |
|---|---|---|
| `weather-daily` | `0 22 * * *` — 22:00 | Lấy 7 ngày weather hoàn chỉnh gần nhất, kết thúc hôm qua. |
| `source-core` | `15 22 * * *` — 22:15 | Staging, core, snapshots và seed ngày lễ. |
| `dimensions-reference` | `30 22 * * *` — 22:30 | Allergens, categories, UOM, suppliers, promotions và date. |
| `dimensions-parties` | `40 22 * * *` — 22:40 | Branches, customers, employees. |
| `dimensions-products` | `50 22 * * *` — 22:50 | Stock items, lots, products, recipes. |
| `facts-sales` | `5 23 * * *` — 23:05 | Facts hóa đơn và dòng bán. |
| `facts-weather` | `15 23 * * *` — 23:15 | Fact thời tiết theo ngày/địa điểm. |
| `marts-sales` | `25 23 * * *` — 23:25 | Sales ngày, sản phẩm, customer 360. |
| `marts-operations` | `35 23 * * *` — 23:35 | Kho, mua hàng, sản xuất/hủy và quỹ. |

Tất cả dùng queue `bakery`, `max_concurrency: 1`; dbt mặc định một thread.
Các mốc là giờ enqueue mong muốn: nếu job trước còn chạy, job sau chờ queue,
không chạy chồng. Khoảng cách 10–20 phút là cấu hình ban đầu, cần đối chiếu
thời gian/RSS thực tế khi dữ liệu tăng. Dagu scheduler hoạt động khi container
chạy; source nghiệp vụ vẫn phải generate và commit trước ETL. Upstream lỗi
làm downstream thiếu prerequisite và thất bại trước khi ghi, không dùng lẫn
batch tối trước. Cron catalog kiểm tra batch mới đã publish thành công.

Chạy thủ công trong ngày theo thứ tự: **generate nghiệp vụ → weather → dbt →
catalog** bằng các lệnh ở trên. Chờ từng run thành công. Chỉ cần PostgreSQL sync
và enrich nguồn lại khi cần refresh catalog nguồn, chẳng hạn sau khi thay schema
hoặc định nghĩa nghiệp vụ. Sửa lịch trong `data_platform/dagu/dags/*.yaml`;
Prefect đã ngừng sử dụng, code cũ nằm trong `data_platform/prefect/`.

```bash
# Xem trạng thái và log.
docker compose ps
docker compose logs --tail 100 dagu marmot
docker compose logs --tail 100 bakery_agent assistant_ui

# Dừng dịch vụ, giữ dữ liệu để khởi động lại.
docker compose stop
```

Giữ volume `postgres_data`, `dagu_data` và thư mục `analytics/target/dagu/`
để giữ dữ liệu, lịch sử và artifacts. `docker compose down -v` xóa named volumes;
không dùng cho restart thông thường.

Nếu API Marmot trả `401`, kiểm tra key của đúng instance và nạp lại `.env`;
nếu key đổi khi Dagu/agent đã chạy, dùng `docker compose up -d dagu bakery_agent mcp_server`
để Compose áp dụng environment mới. Nếu plugin chưa sẵn sàng, chờ load xong
trước khi ingestion; HTTP health ready chưa chứng minh plugins đã ready.

## Tài liệu chi tiết

- [Nghiệp vụ Maison Douce](BUSINESS_LOGIC.md)
- [Bootstrap và simulator](generate_script/README.md)
- [PostgreSQL, audit và soft delete](data_platform/postgres/README.md)
- [dbt analytics và kiểm chứng](analytics/README.md)
- [Marmot enrichment nguồn](data_platform/marmot/README.md)
- [Cube semantic model](data_platform/cube/README.md)
- [MCP tools](data_platform/mcp_server/README.md)
- [Bakery assistant và Perspective](data_platform/assistant_ui/README.md)

## Cấu trúc test và chuẩn bị GitHub

```text
analytics/test/                       Python regression, dbt SQL tests, return fixture
data_platform/dagu/test/              Unit tests và smoke test Dagu
data_platform/assistant_ui/test/      Browser fixtures và Python agent tests
generate_script/simulate_operations.py
generate_script/backfill_operations.py
notebooks/assistant_demo.ipynb        Notebook demo, không lưu outputs
```

DDL PostgreSQL, code generate, seed ngày lễ Việt Nam, test fixtures và
`package-lock.json` là đầu vào được version. Dữ liệu sinh ra, database/cache,
dbt artifacts/logs, virtual environments, `node_modules`, bản rollback và
credentials được loại bằng `.gitignore`. Assets Perspective trong `public/`
được tạo lại từ npm dependencies qua `predev`/`prebuild`.

Kiểm tra offline, không khởi động Docker hoặc gọi model API:

```bash
./.venv/bin/python -m pip install -r requirements-dev.txt
./.venv/bin/python -m unittest discover -s analytics/test -v
./.venv/bin/python -m unittest discover -s data_platform/dagu/test -v
./.venv/bin/python analytics/run_pipeline.py --check
bash -n generate_script/bootstrap_bakery.sh
```

Smoke test native Dagu chỉ chạy khi đặt `DAGU_TEST_BINARY` trỏ tới binary
Dagu 2.21.0; test dùng artifacts giả và thư mục tạm. Test browser và Python
agent có hướng dẫn riêng trong [Assistant UI](data_platform/assistant_ui/README.md).

Trước commit, xem `git status --short` và `git diff --cached` để biết chính xác
nội dung sẽ được đưa lên GitHub. `.env` được giữ local; người clone repo tự
tạo `.env` từ `.env.example`. Không commit notebook outputs hoặc database dump.
