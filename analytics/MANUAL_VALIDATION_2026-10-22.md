# Kết quả chạy ETL thủ công — 22/10/2026

Pipeline đã chạy thành công trên PostgreSQL 16.15 với pg_duckdb 1.1.0.
Sau khi sửa các lỗi phát hiện qua lần chạy live, đã hoàn thành hai batch
liên tiếp; batch không đổi source không làm thay đổi nội dung target hoặc SK.

## Phạm vi dữ liệu

| Thành phần | Kết quả |
|---|---:|
| Bảng source trong `bakery` | 34 |
| Bảng staging | 34 |
| Bảng core | 33 |
| Bảng mart, gồm 12 dimension và 2 fact | 21 |
| Snapshot kỹ thuật trong `analytics_mart` | 12 |
| Data tests dbt | 160 pass |
| Đối soát source → staging → core → mart | 110 pass |
| Fingerprint source, target và sequence trước/sau chạy lặp | 146 không đổi |
| Bảng ETL được DuckDB thực sự lập kế hoạch và thực thi truy vấn tất cả cột | 100 |

Source hiện có 834 hóa đơn, 2.319 dòng bán và 5.825 biến động kho.
834 hóa đơn đã bán trong kỳ 05/10–21/10/2026 có tổng tiền gốc
154.911.400 VND. Mart doanh số ngày có 17 dòng chi nhánh/ngày;
mart sản phẩm có 444 dòng; tồn kho có 339 dòng; vận hành có 36 dòng
chi nhánh/ngày/đơn vị.

## Các lỗi đã sửa và cách xử lý target

1. Hook được render khi parse nên sequence trỏ nhầm `analytics`, trong khi
   dimension nằm ở `analytics_mart`. Đổi các hook sang Jinja render lúc chạy;
   áp dụng cho sequence, xóa grain bị ảnh hưởng và refresh hạn dùng tồn kho.
2. `FULL JOIN` với `IS NOT DISTINCT FROM` không được PostgreSQL hỗ trợ trong
   mart vận hành. Đổi sang equijoin trên các khóa không NULL.
3. Các phép tính/tổng hợp tạo `NUMERIC` không có precision khiến pg_duckdb
   fallback về PostgreSQL. Khai báo `numeric(38,9)` cho đầu ra tính toán,
   giữ kiểu decimal cho tiền/lượng. Các giá trị trung bình và thời lượng
   được làm tròn về chín chữ số thập phân.
4. Kiểm tra engine trong transaction tường minh không tạo DuckDB plan trên
   phiên bản đang chạy. Chuyển bước kiểm tra báo cáo sang autocommit chỉ đọc;
   kiểm tra `EXPLAIN` có `DuckDBScan` và đối chiếu kết quả hai engine.
5. `line_amount_after_recorded_discount` bị trừ giảm giá lần nữa, mặc dù
   `line_total` đã là số sau giảm. Đổi sang sử dụng trực tiếp `line_total`.
6. Mart vận hành từng cộng lượng khác đơn vị trong cùng ngày/chi nhánh.
   Thêm `uom_id` vào grain, khóa incremental và đầu ra.
7. Chuẩn hóa hàm thời gian snapshot về TIMESTAMPTZ phù hợp cột audit nguồn,
   loại bỏ cảnh báo lệch kiểu timestamp trong lần chạy live.

Đã drop và tạo lại đúng 16 bảng tính toán bị ảnh hưởng: 7 bảng core và 9 bảng
fact/reporting mart. Đây là các bảng có thể tính lại từ staging. Không dùng
`CASCADE`, không xóa volume, staging, dimension, snapshot hay sequence SK.
Các bảng đã xóa đã được dựng lại thành công từ dữ liệu còn giữ.

Không sửa dữ liệu OLTP. Fingerprint của cả 34 bảng `bakery` được chụp trước
lúc dựng lại target và đối chiếu sau cùng: toàn bộ không đổi. Các schema
ứng dụng `marmot`, `cube_core` và cấu hình dịch vụ không bị thay đổi.

## Các kiểm tra đã thực hiện

- Đủ 33 audit trigger, đúng kiểu và nullability của bốn cột metadata nguồn.
- So sánh toàn bộ payload nguồn với phiên bản mới nhất ở staging, gồm
  tombstone; đối chiếu business key, phiên bản và cờ xóa giữa source/core.
- Kiểm tra trùng business key core, SK fact/dimension, một phiên bản current,
  khoảng hiệu lực SCD2 và đối soát tiền hóa đơn/dòng bán.
- Đối chiếu doanh số ngày/sản phẩm, tồn kho, điểm khách hàng, quỹ tiền mặt,
  sản xuất và hủy theo đúng grain/đơn vị với source.
- Không còn cột `NUMERIC` thiếu precision trong ba schema analytics.
- DuckDB truy vấn được đủ 100 bảng target, và báo cáo doanh số ngày cho
  kết quả bằng PostgreSQL trên 17 grain chi nhánh/ngày.
- Batch lặp pass `260/260` bước: 100 model/snapshot thành công, 160 tests pass,
  không warning/error/skip. Thời gian dbt build khoảng 11 giây ở quy mô này.
- 8 regression tests offline pass; thêm 6 kiểm tra SQL fact incremental
  PostgreSQL với return hoàn tất, hủy và xóa mềm trên TEMP fixture, rollback
  toàn bộ sau kiểm tra.

## Giới hạn kiểm chứng

Source hiện chưa có phiếu trả hàng. Kiểm tra return trên dữ liệu thật vì vậy
không có mẫu; sáu TEMP fixture kiểm chứng logic tính fact nhưng không thay
thế một lần chạy end-to-end với nghiệp vụ trả hàng thực tế.

SCD2 trước lần quan sát đầu vẫn dùng giả định trạng thái đầu tiên, được ghi
nhận bằng `_observed_from`; không có dữ liệu để khôi phục các thay đổi thuộc
tính chưa từng được ghi nhận trước đó. Các kiểm tra không biến giả định này
thành lịch sử đã được chứng minh.

## Chạy thủ công về sau

```bash
./.venv/bin/python analytics/run_pipeline.py --run
```

Lệnh chỉ chạy ETL/tests và kiểm tra engine. Việc tạo thêm nghiệp vụ do
simulator thực hiện riêng. Chưa thêm orchestration hoặc lịch tự động.

Bằng chứng máy đọc được nằm ở `analytics/target/manual_validation.json`,
`analytics/target/run_results.json` và hai log
`analytics/target/manual_build.log`, `analytics/target/manual_rerun.log`.
