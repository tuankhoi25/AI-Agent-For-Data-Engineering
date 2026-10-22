#!/usr/bin/env python3
"""Generate historical daily operations before switching to the daily runner.

This helper intentionally supplies past cutoffs to the shared simulator, which
then schedules ordered business events before each day's cutoff. Row audit
timestamps remain the real database write time, never the historical cutoff.
The regular simulate_operations.py command remains tied to PostgreSQL's
current clock and does not expose a simulated timestamp option.
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import secrets
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo


SIMULATOR_PATH = Path(__file__).with_name("simulate_operations.py")


def load_simulator():
    spec = importlib.util.spec_from_file_location("bakery_daily_simulator", SIMULATOR_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Không nạp được simulator: {SIMULATOR_PATH}")
    simulator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(simulator)
    return simulator


def parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Ngày phải theo định dạng YYYY-MM-DD.") from exc


def parse_time(value: str) -> time:
    try:
        parsed = time.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Giờ phải theo định dạng HH:MM.") from exc
    if parsed.tzinfo is not None or parsed.second or parsed.microsecond:
        raise argparse.ArgumentTypeError("Chỉ nhập giờ địa phương theo định dạng HH:MM.")
    return parsed


def parse_args():
    parser = argparse.ArgumentParser(
        description="Tạo lịch sử vận hành theo ngày trước khi chuyển sang simulator hằng ngày."
    )
    parser.add_argument(
        "--dsn", help="PostgreSQL DSN tùy chọn; ưu tiên hơn DATABASE_URL trong .env."
    )
    parser.add_argument("--branch", default="MAIN", help="Mã chi nhánh (mặc định: MAIN).")
    parser.add_argument("--days", type=int, default=30, help="Số ngày lịch sử muốn tạo (mặc định: 30).")
    parser.add_argument(
        "--end-date", type=parse_date,
        help="Ngày cuối trong khoảng backfill; mặc định là hôm qua theo giờ chi nhánh.",
    )
    parser.add_argument(
        "--run-time", type=parse_time, default=time(11, 0),
        help="Giờ chốt mô phỏng; giao dịch được rải trước giờ này (mặc định: 11:00 giờ địa phương).",
    )
    parser.add_argument(
        "--max-orders", type=int, default=3,
        help="Mức đơn nền tối đa ngày thường cho mỗi lượt (mặc định: 3).",
    )
    parser.add_argument("--seed", type=int, help="Seed nền để có thể tái lập chuỗi lựa chọn ngẫu nhiên.")
    return parser.parse_args()


def get_backfill_context(simulator, dsn: str, branch_code: str):
    conn = simulator.db_connect(dsn)
    try:
        with conn.cursor() as cur:
            simulator.require_row_audit(cur)
            cur.execute(
                """SELECT branch_id,branch_code,branch_name,timezone,opening_date
                   FROM branches WHERE branch_code=%s AND is_active=TRUE AND NOT _is_deleted""",
                (branch_code,),
            )
            branch = cur.fetchone()
            if not branch:
                raise RuntimeError(f"Không tìm thấy chi nhánh đang hoạt động: {branch_code}")
            if branch["opening_date"] is None:
                raise RuntimeError("Chi nhánh chưa có opening_date trong bảng branches.")
            cur.execute("SELECT clock_timestamp() AS now_at")
            now_at = cur.fetchone()["now_at"]
            cur.execute(
                """SELECT business_date
                   FROM simulation_runs
                   WHERE status='COMPLETED'
                   ORDER BY business_date"""
            )
            completed_dates = {row["business_date"] for row in cur.fetchall()}
            cur.execute(
                "SELECT MAX(occurred_at) AS latest_stock_movement "
                "FROM stock_movements WHERE branch_id=%s AND NOT _is_deleted",
                (branch["branch_id"],),
            )
            latest_stock_movement = cur.fetchone()["latest_stock_movement"]
            return branch, now_at, completed_dates, latest_stock_movement
    finally:
        conn.close()


def run_backfill(args):
    if args.days < 1:
        raise RuntimeError("--days phải lớn hơn hoặc bằng 1.")
    if args.max_orders < 1:
        raise RuntimeError("--max-orders phải lớn hơn hoặc bằng 1.")
    if not (time(7, 0) <= args.run_time < time(22, 0)):
        raise RuntimeError("--run-time phải nằm trong giờ hoạt động 07:00–22:00.")

    simulator = load_simulator()
    dsn = args.dsn or simulator.project_database_url()
    if not dsn:
        raise RuntimeError("Chưa có DATABASE_URL trong .env hoặc môi trường; hoặc truyền --dsn.")
    if simulator.holiday_calendar is None:
        raise RuntimeError("Thiếu lịch ngày lễ Việt Nam. Cài bằng: pip install holidays")

    branch, now_at, completed_dates, latest_stock_movement = get_backfill_context(
        simulator, dsn, args.branch
    )
    timezone = ZoneInfo(branch["timezone"] or "Asia/Ho_Chi_Minh")
    today = now_at.astimezone(timezone).date()
    end_date = args.end_date or (today - timedelta(days=1))
    if end_date >= today:
        raise RuntimeError(
            f"Ngày kết thúc phải trước hôm nay ({today}) để không tạo dữ liệu cho ngày hiện tại hoặc tương lai."
        )
    start_date = end_date - timedelta(days=args.days - 1)
    if start_date < branch["opening_date"]:
        raise RuntimeError(
            f"Khoảng yêu cầu {start_date}–{end_date} bắt đầu trước ngày mở bán "
            f"{branch['opening_date']}. Không ghi dữ liệu. Hãy đồng bộ opening_date và tồn kho khai trương "
            "trước ngày bắt đầu backfill."
        )
    dates = [start_date + timedelta(days=offset) for offset in range(args.days)]
    pending_dates = [day for day in dates if day not in completed_dates]
    skipped_dates = len(dates) - len(pending_dates)
    if not pending_dates:
        print(
            f"Backfill {start_date}–{end_date}: đủ {args.days} ngày đã có run COMPLETED; "
            "không phát sinh thêm dữ liệu."
        )
        return 0

    first_pending_run_at = datetime.combine(pending_dates[0], args.run_time).replace(tzinfo=timezone)
    if latest_stock_movement is not None and latest_stock_movement > first_pending_run_at:
        raise RuntimeError(
            f"Kho đã có biến động tới {latest_stock_movement.isoformat()}, sau ngày backfill còn thiếu đầu tiên "
            f"({first_pending_run_at.isoformat()}). Không ghi dữ liệu vì các lượt cũ có thể dùng nhầm tồn kho tương lai. "
            "Hãy bắt đầu từ ngày có snapshot tồn kho hợp lệ hoặc chuẩn bị lại baseline tồn kho."
        )

    base_seed = args.seed if args.seed is not None else secrets.randbits(32)

    print(
        f"Backfill chi nhánh {branch['branch_name']} ({branch['branch_code']}): "
        f"{start_date}–{end_date}, giờ chạy {args.run_time.strftime('%H:%M')} {timezone.key}."
    )
    print(f"Seed nền: {base_seed}; ngày đã có run COMPLETED sẽ được bỏ qua: {skipped_dates}.")

    completed_count = 0
    for offset, business_date in enumerate(dates):
        if business_date in completed_dates:
            print(f"[{business_date}] Đã có run COMPLETED, bỏ qua để tránh tạo trùng.")
            continue
        run_at = datetime.combine(business_date, args.run_time).replace(tzinfo=timezone)
        day_seed = base_seed + offset
        sim_args = argparse.Namespace(
            dsn=dsn,
            branch=args.branch,
            max_orders=args.max_orders,
            seed=day_seed,
        )
        print(f"[{business_date}] Bắt đầu backfill, seed={day_seed}.")
        result = simulator.simulate(
            sim_args,
            run_at_override=run_at,
            run_label=f"BACKFILL-{args.branch}-{business_date:%Y%m%d}",
        )
        if result != 0:
            raise RuntimeError(f"Backfill ngày {business_date} kết thúc với mã {result}.")
        completed_count += 1

    print(
        f"Hoàn tất backfill: {completed_count} ngày mới, {skipped_dates} ngày đã có dữ liệu được bỏ qua. "
        "Sau đó có thể dùng simulate_operations.py cho lượt chạy hằng ngày."
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(run_backfill(parse_args()))
    except Exception as error:
        print(f"Lỗi backfill: {error}", file=sys.stderr)
        raise SystemExit(1)
