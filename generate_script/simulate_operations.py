#!/usr/bin/env python3
"""Run one realistic bakery-operation tick using the database's current time.

The daily command-line entry point never accepts a simulated business
timestamp. Only the separate historical backfill runner calls the internal
timestamp override. Business events are scheduled before that cutoff; live
run completion is captured from PostgreSQL after processing.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import secrets
import ssl
import sys
import uuid
from datetime import date, datetime, time, timedelta
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

try:
    import holidays as holiday_calendar
except ImportError:
    holiday_calendar = None

try:
    import certifi
except ImportError:
    certifi = None


OPEN_TIME = time(7, 0)
CLOSE_TIME = time(22, 0)
OPENING_CASH = Decimal("1000000")
LOYALTY_POINTS_PER_VND = Decimal("10000")
LOYALTY_REDEMPTION_POINTS = 100
LOYALTY_REDEMPTION_VND = Decimal("10000")
MAX_CART_LINES = 4
WEATHER_LATITUDE = 10.8231
WEATHER_LONGITUDE = 106.6297
WEATHER_LOCATION_NAME = "TP. Hồ Chí Minh"
WEATHER_ENDPOINT = "https://archive-api.open-meteo.com/v1/archive"
HEAVY_RAIN_MM_PER_HOUR = 5.0
MODERATE_RAIN_MM_PER_HOUR = 1.0
SUNNY_SHORTWAVE_THRESHOLD_W_M2 = 150.0
HEAVY_RAIN_WEATHER_CODES = {65, 67, 82}
STORM_WEATHER_CODES = {95, 96, 97, 99}
MODERATE_RAIN_WEATHER_CODES = {53, 55, 57, 63, 81}
LIGHT_RAIN_WEATHER_CODES = {51, 56, 61, 66, 80}

SHELF_LIFE_DAYS = {
    "MILK_FRESH": 14,
    "CREAM_ANCHOR": 14,
    "LEMON": 5,
    "EGGS": 30,
    "BUTTER_PRESIDENT": 30,
    "BUTTER_ANCHOR": 30,
    "TRUFFLE_PASTE": 30,
    "FRUIT_PUREE": 14,
    "BLUEBERRY_PUREE": 14,
    "ICE": 2,
    "YEAST": 90,
    "FG_CROISSANT": 1,
    "FG_PAIN_CHOC": 1,
    "FG_PAIN_RAisin": 1,
    "FG_CASHEW_CROISSANT": 1,
    "FG_CASHEW_PAIN_CHOC": 1,
    "FG_MAC_HOUJICHA": 4,
    "FG_MAC_OOLONG": 4,
    "FG_MAC_IRON_GODDESS": 4,
    "FG_MAC_TRUFFLE": 4,
    "FG_MAC_LONGJING": 4,
    "FG_ENT_CAPUCINE": 3,
    "FG_ENT_APOLLINE": 3,
    "FG_ENT_LEONIE": 3,
    "FG_ENT_SOLENE": 3,
    "FG_ANTONIO_BLUEBERRY": 1,
    "RT_MAC_BOX6": 4,
    "RT_MAC_BOX12": 4,
    "RT_MINI_CROISSANT8": 1,
    "RT_MINI_RAisin8": 1,
    "RT_CHOC_BAR": 180,
    "RT_JAM220": 180,
}


def db_connect(dsn: str):
    """Connect to the bakery schema using psycopg 3 or psycopg2."""
    connection_options = {"options": "-c search_path=bakery"}
    try:
        import psycopg
        from psycopg.rows import dict_row

        return psycopg.connect(dsn, row_factory=dict_row, **connection_options)
    except ImportError:
        try:
            import psycopg2
            from psycopg2.extras import RealDictCursor

            return psycopg2.connect(
                dsn, cursor_factory=RealDictCursor, **connection_options
            )
        except ImportError as exc:
            raise RuntimeError(
                'Thiếu driver PostgreSQL. Cài bằng: pip install "psycopg[binary]" Faker holidays certifi'
            ) from exc


def require_row_audit(cur):
    """Fail before generating records if the database was not initialized correctly."""
    cur.execute(
        """SELECT t.table_name
           FROM information_schema.tables t
           WHERE t.table_schema='bakery' AND t.table_type='BASE TABLE'
             AND t.table_name <> 'simulation_runs'
             AND ((SELECT COUNT(*) FROM information_schema.columns c
                   WHERE c.table_schema=t.table_schema AND c.table_name=t.table_name
                     AND c.column_name IN ('_created_at','_last_updated_at','_is_deleted','_deleted_at')) <> 4
                  OR NOT EXISTS (
                     SELECT 1 FROM pg_catalog.pg_trigger tr
                     WHERE tr.tgrelid=to_regclass(format('bakery.%I',t.table_name))
                       AND tr.tgname='bakery_row_audit' AND NOT tr.tgisinternal
                       AND tr.tgenabled IN ('O','A')))
           ORDER BY t.table_name"""
    )
    missing = [row["table_name"] for row in cur.fetchall()]
    if missing:
        raise RuntimeError(
            "Các bảng chưa có đủ audit columns/trigger: " + ", ".join(missing)
            + ". Hãy tạo lại PostgreSQL volume và chạy bootstrap_bakery.sh; "
              "không ghi dữ liệu mô phỏng."
        )


def project_database_url():
    """Read DATABASE_URL from the process environment or project-root .env."""
    dsn = os.environ.get("DATABASE_URL")
    if dsn:
        return dsn

    env_path = Path(__file__).resolve().parents[1] / ".env"
    try:
        lines = env_path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return None

    env_values = {}
    for line in lines:
        entry = line.strip()
        if not entry or entry.startswith("#"):
            continue
        if entry.startswith("export "):
            entry = entry[7:].lstrip()
        key, separator, value = entry.partition("=")
        if not separator:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        env_values[key.strip()] = value

    dsn = env_values.get("DATABASE_URL")
    if not dsn:
        return None

    def substitute(match):
        variable = match.group(1)
        return os.environ.get(variable, env_values.get(variable, match.group(0)))

    return re.sub(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}", substitute, dsn)


def make_faker():
    try:
        from faker import Faker

        return Faker("vi_VN")
    except ImportError:
        return None


def vietnam_holiday_name(business_date: date):
    if holiday_calendar is None:
        raise RuntimeError('Thiếu thư viện lịch ngày lễ Việt Nam. Cài bằng: pip install holidays')
    calendar = holiday_calendar.country_holidays(
        "VN", years=[business_date.year], language="vi", observed=True
    )
    return calendar.get(business_date)


def calendar_context(business_date: date):
    holiday_name = vietnam_holiday_name(business_date)
    is_weekend = business_date.weekday() >= 5
    is_holiday = holiday_name is not None
    if is_holiday and is_weekend:
        day_type = "VIETNAM_HOLIDAY_WEEKEND"
    elif is_holiday:
        day_type = "VIETNAM_HOLIDAY"
    elif is_weekend:
        day_type = "WEEKEND"
    else:
        day_type = "WEEKDAY"
    return {
        "is_weekend": is_weekend,
        "is_holiday": is_holiday,
        "holiday_name": str(holiday_name) if holiday_name else None,
        "day_type": day_type,
    }


def weather_context_from_values(values: dict, status="OPEN_METEO"):
    temperature = values.get("temperature_2m_c")
    rain = values.get("rain_mm")
    precipitation = values.get("precipitation_mm")
    shortwave = values.get("shortwave_radiation_w_m2")
    humidity = values.get("relative_humidity_pct")
    cloud_cover = values.get("cloud_cover_pct")
    code = values.get("weather_code")
    rain_amount = rain if rain is not None else precipitation
    rain_amount = float(rain_amount) if rain_amount is not None else None
    code = int(code) if code is not None else None

    if (rain_amount is not None and rain_amount >= HEAVY_RAIN_MM_PER_HOUR) or code in HEAVY_RAIN_WEATHER_CODES:
        rain_level = "HEAVY_RAIN"
        order_factor = Decimal("0.35")
    elif code in STORM_WEATHER_CODES:
        rain_level = "THUNDERSTORM"
        order_factor = Decimal("0.40")
    elif (rain_amount is not None and rain_amount >= MODERATE_RAIN_MM_PER_HOUR) or code in MODERATE_RAIN_WEATHER_CODES:
        rain_level = "MODERATE_RAIN"
        order_factor = Decimal("0.65")
    elif (rain_amount is not None and rain_amount > 0) or code in LIGHT_RAIN_WEATHER_CODES:
        rain_level = "LIGHT_RAIN"
        order_factor = Decimal("0.85")
    else:
        rain_level = "DRY"
        order_factor = Decimal("1.00")

    rainy = rain_level != "DRY"
    sunny = not rainy and (
        (shortwave is not None and float(shortwave) >= SUNNY_SHORTWAVE_THRESHOLD_W_M2)
        or code in {0, 1}
    )
    if sunny:
        order_factor = Decimal("1.15")

    if rain_level == "HEAVY_RAIN":
        drink_probability = 0.28
    elif rain_level == "THUNDERSTORM":
        drink_probability = 0.32
    elif rain_level == "MODERATE_RAIN":
        drink_probability = 0.38
    elif rain_level == "LIGHT_RAIN":
        drink_probability = 0.42
    elif temperature is None:
        drink_probability = 0.45
    elif float(temperature) >= 32:
        drink_probability = 0.78
    elif float(temperature) < 30:
        drink_probability = 0.30
    else:
        drink_probability = 0.52
    if rainy and temperature is not None and float(temperature) >= 32:
        drink_probability = min(drink_probability + 0.20, 0.68)

    if rainy:
        condition = rain_level
    elif temperature is None:
        condition = "SUNNY" if sunny else "UNKNOWN"
    elif float(temperature) >= 32:
        condition = "HOT"
    elif float(temperature) < 30:
        condition = "COOL"
    else:
        condition = "MILD"

    return {
        "temperature_2m_c": float(temperature) if temperature is not None else None,
        "precipitation_mm": float(precipitation) if precipitation is not None else None,
        "rain_mm": float(rain) if rain is not None else None,
        "shortwave_radiation_w_m2": float(shortwave) if shortwave is not None else None,
        "relative_humidity_pct": float(humidity) if humidity is not None else None,
        "cloud_cover_pct": float(cloud_cover) if cloud_cover is not None else None,
        "weather_code": code,
        "observation_time": values.get("observation_time"),
        "rain_level": rain_level,
        "order_factor": order_factor,
        "is_rainy": bool(rainy),
        "is_sunny": bool(sunny),
        "condition": condition,
        "drink_probability": drink_probability,
        "status": status,
    }


def read_open_meteo_hour(business_date: date, timezone_name: str, local_now: datetime):
    params = {
        "latitude": WEATHER_LATITUDE,
        "longitude": WEATHER_LONGITUDE,
        "start_date": business_date.isoformat(),
        "end_date": business_date.isoformat(),
        "hourly": "temperature_2m,relative_humidity_2m,precipitation,rain,weather_code,cloud_cover,shortwave_radiation",
        "timezone": timezone_name,
        "temperature_unit": "celsius",
        "precipitation_unit": "mm",
    }
    url = WEATHER_ENDPOINT + "?" + urlencode(params)
    request = Request(url, headers={"User-Agent": "MaisonDouceBakerySimulator/1.0"})
    ssl_context = ssl.create_default_context(cafile=certifi.where()) if certifi else None
    with urlopen(request, timeout=8, context=ssl_context) as response:
        payload = json.loads(response.read().decode("utf-8"))
    hourly = payload.get("hourly") or {}
    times = hourly.get("time") or []
    target_hour = local_now.replace(minute=0, second=0, microsecond=0).strftime("%Y-%m-%dT%H:%M")
    eligible = [(index, value) for index, value in enumerate(times) if value <= target_hour]
    if not eligible:
        raise RuntimeError(f"Open-Meteo không trả dữ liệu theo giờ đến {target_hour}.")
    index, observation_time = eligible[-1]

    def value(name):
        values = hourly.get(name) or []
        return values[index] if index < len(values) else None

    values = {
        "temperature_2m_c": value("temperature_2m"),
        "precipitation_mm": value("precipitation"),
        "rain_mm": value("rain"),
        "shortwave_radiation_w_m2": value("shortwave_radiation"),
        "relative_humidity_pct": value("relative_humidity_2m"),
        "cloud_cover_pct": value("cloud_cover"),
        "weather_code": value("weather_code"),
        "observation_time": observation_time,
    }
    if all(values[key] is None for key in values if key != "observation_time"):
        raise RuntimeError(f"Open-Meteo chưa có chỉ số thời tiết tại {observation_time}.")
    return values, url


def get_weather_context(business_date: date, timezone_name: str, local_now: datetime):
    """Fetch weather for the current local hour; store metadata in existing run notes only."""
    try:
        values, source_url = read_open_meteo_hour(business_date, timezone_name, local_now)
    except Exception as error:
        return {
            **weather_context_from_values({}, "UNAVAILABLE"),
            "warning": f"Không lấy được thời tiết Open-Meteo; dùng nhu cầu trung tính ({error}).",
            "source_url": None,
        }

    context = weather_context_from_values(values)
    context["source_url"] = source_url
    return context


def simulated_order_count(max_orders: int, weather: dict, calendar: dict) -> int:
    baseline = random.randint(1, max_orders)
    weather_factor = weather["order_factor"]

    if calendar["is_holiday"] and calendar["is_weekend"]:
        calendar_factor = Decimal("1.80")
    elif calendar["is_holiday"]:
        calendar_factor = Decimal("1.50")
    elif calendar["is_weekend"]:
        calendar_factor = Decimal("1.30")
    else:
        calendar_factor = Decimal("1.00")

    expected = Decimal(baseline) * weather_factor * calendar_factor
    order_count = int(expected)
    if random.random() < expected - order_count:
        order_count += 1
    return order_count


def build_event_timeline(run_at: datetime, timezone: ZoneInfo, order_count: int):
    """Schedule operational events before this invocation's cutoff, in local time."""
    business_date = run_at.astimezone(timezone).date()
    opening_at = datetime.combine(business_date, OPEN_TIME, tzinfo=timezone)
    elapsed = run_at - opening_at
    if elapsed < timedelta(minutes=5):
        return opening_at, run_at, run_at, run_at, []

    window = min(elapsed, timedelta(minutes=90))
    activity_start = run_at - window
    production_start = activity_start + window * 0.05
    production_end = activity_start + window * 0.30
    sale_span = max(timedelta(0), run_at - production_end - timedelta(seconds=1))
    sale_events = []
    if order_count > 0 and sale_span > timedelta(0):
        slot = sale_span / order_count
        for index in range(order_count):
            slot_end = production_end + slot * (index + 1)
            max_duration = slot / 2
            duration = min(timedelta(minutes=random.randint(2, 6)), max_duration)
            opened_at = max(opening_at, slot_end - duration)
            completed_at = slot_end
            if completed_at > opened_at:
                sale_events.append((opened_at, completed_at))
    return opening_at, activity_start, production_start, production_end, sale_events


def money(value: Any) -> Decimal:
    return Decimal(str(value or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def qty(value: Any) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)


def insert(cur, stats: dict, statement: str, params: tuple = ()):
    # Audit columns are owned by PostgreSQL triggers, not business/backfill timestamps.
    cur.execute(statement, params)
    stats["records_created"] += 1
    if "RETURNING" in statement.upper():
        return cur.fetchone()
    return None


def get_employee(cur, branch_id: int, employee_code: str):
    cur.execute(
        "SELECT employee_id, employee_code, full_name FROM employees "
        "WHERE branch_id=%s AND employee_code=%s AND is_active=TRUE AND NOT _is_deleted",
        (branch_id, employee_code),
    )
    return cur.fetchone()


def choose_employee(cur, branch_id: int, preferred_code: str):
    employee = get_employee(cur, branch_id, preferred_code)
    if employee:
        return employee
    cur.execute(
        "SELECT employee_id, employee_code, full_name FROM employees "
        "WHERE branch_id=%s AND is_active=TRUE AND NOT _is_deleted ORDER BY employee_id LIMIT 1",
        (branch_id,),
    )
    employee = cur.fetchone()
    if not employee:
        raise RuntimeError("Chi nhánh chưa có nhân viên đang làm việc để ghi nhận hoạt động.")
    return employee


def random_customer(cur, stats: dict, faker, joined_at: datetime):
    cur.execute("SELECT customer_id FROM customers WHERE is_active=TRUE AND NOT _is_deleted ORDER BY random() LIMIT 1")
    existing = cur.fetchone()
    if existing and random.random() < 0.35:
        return existing["customer_id"]
    if random.random() >= 0.55:
        return None

    fallback_names = ["Nguyễn Hà My", "Trần Minh Khang", "Lê Ngọc Anh", "Phạm Gia Linh", "Võ Quốc Bảo"]
    name = faker.name() if faker else random.choice(fallback_names)
    for _ in range(10):
        phone = "09" + "".join(str(random.randrange(10)) for _ in range(8))
        cur.execute("SELECT 1 FROM customers WHERE phone=%s", (phone,))
        if not cur.fetchone():
            break
    else:
        phone = None
    email = faker.email() if faker else None
    birth_date = faker.date_of_birth(minimum_age=18, maximum_age=65) if faker else None
    row = insert(
        cur,
        stats,
        """INSERT INTO customers
           (customer_code, full_name, phone, email, date_of_birth, joined_at,
            marketing_consent, is_active, notes)
           VALUES (%s,%s,%s,%s,%s,%s,%s,TRUE,%s)
           RETURNING customer_id""",
        (
            "CUST-" + uuid.uuid4().hex[:12].upper(),
            name,
            phone,
            email,
            birth_date,
            joined_at,
            random.random() < 0.25,
            "Khách tạo tự động khi phát sinh giao dịch mô phỏng.",
        ),
    )
    stats["customers"] += 1
    return row["customer_id"]


class Inventory:
    """In-memory FEFO reservation view backed by stock_movements."""

    def __init__(self, cur, branch_id: int, business_date: date):
        cur.execute(
            """SELECT si.stock_item_id, si.stock_item_code, si.stock_item_name,
                      si.item_type, si.base_uom_id, si.reorder_level,
                      il.inventory_lot_id, il.lot_code, il.expires_at,
                      il.received_at, il.unit_cost,
                      COALESCE(SUM(sm.quantity_delta),0) AS balance
               FROM stock_items si
               LEFT JOIN inventory_lots il ON il.stock_item_id=si.stock_item_id AND NOT il._is_deleted
               LEFT JOIN stock_movements sm
                 ON sm.inventory_lot_id=il.inventory_lot_id AND sm.branch_id=%s AND NOT sm._is_deleted
               WHERE si.is_active=TRUE AND NOT si._is_deleted
                 AND EXISTS (SELECT 1 FROM units_of_measure u WHERE u.uom_id=si.base_uom_id AND NOT u._is_deleted)
               GROUP BY si.stock_item_id, si.stock_item_code, si.stock_item_name,
                        si.item_type, si.base_uom_id, si.reorder_level,
                        il.inventory_lot_id, il.lot_code, il.expires_at,
                        il.received_at, il.unit_cost
               ORDER BY il.expires_at NULLS LAST, il.received_at NULLS LAST,
                        il.inventory_lot_id""",
            (branch_id,),
        )
        self.lots: dict[int, list[dict]] = {}
        self.items: dict[int, dict] = {}
        for row in cur.fetchall():
            item_id = row["stock_item_id"]
            self.items[item_id] = {
                "stock_item_id": item_id,
                "stock_item_code": row["stock_item_code"],
                "stock_item_name": row["stock_item_name"],
                "item_type": row["item_type"],
                "base_uom_id": row["base_uom_id"],
                "reorder_level": Decimal(str(row["reorder_level"])) if row["reorder_level"] is not None else None,
            }
            if row["inventory_lot_id"] is None:
                continue
            balance = Decimal(str(row["balance"]))
            lot = {
                "inventory_lot_id": row["inventory_lot_id"],
                "lot_code": row["lot_code"],
                "expires_at": row["expires_at"],
                "received_at": row["received_at"],
                "unit_cost": Decimal(str(row["unit_cost"])) if row["unit_cost"] is not None else None,
                "balance": balance if row["expires_at"] is None or row["expires_at"] >= business_date else Decimal("0"),
            }
            self.lots.setdefault(item_id, []).append(lot)

    def balance(self, stock_item_id: int) -> Decimal:
        return sum((lot["balance"] for lot in self.lots.get(stock_item_id, [])), Decimal("0"))

    def reserve(self, needs: list[tuple[int, Decimal]]):
        """Reserve all requirements atomically; return FEFO allocations or None."""
        shadow = {
            item_id: [dict(lot) for lot in lots]
            for item_id, lots in self.lots.items()
        }
        allocations = []
        for stock_item_id, required in needs:
            remaining = Decimal(str(required))
            item_lots = shadow.get(stock_item_id, [])
            for lot in item_lots:
                if remaining <= 0:
                    break
                available = lot["balance"]
                if available <= 0:
                    continue
                taken = min(available, remaining)
                lot["balance"] -= taken
                remaining -= taken
                item = self.items[stock_item_id]
                allocations.append(
                    {
                        "stock_item_id": stock_item_id,
                        "stock_item_code": item["stock_item_code"],
                        "inventory_lot_id": lot["inventory_lot_id"],
                        "quantity": taken,
                        "uom_id": item["base_uom_id"],
                        "unit_cost": lot["unit_cost"],
                    }
                )
            if remaining > Decimal("0.0000001"):
                return None
        self.lots = shadow
        return allocations

    def add_lot(self, stock_item_id: int, lot: dict):
        self.lots.setdefault(stock_item_id, []).append(lot)
        self.lots[stock_item_id].sort(
            key=lambda x: (x["expires_at"] is None, x["expires_at"] or date.max, x["received_at"] or date.max)
        )


def process_due_purchase_orders(cur, stats: dict, branch_id: int, run_at: datetime,
                                business_date: date, receiver_id: int,
                                received_at: datetime | None = None):
    received_at = received_at or run_at
    cur.execute(
        """SELECT purchase_order_id, po_number, supplier_id, branch_id, ordered_at
           FROM purchase_orders
           WHERE branch_id=%s AND NOT _is_deleted AND status IN ('SENT','PARTIALLY_RECEIVED')
             AND ordered_at <= %s
           ORDER BY ordered_at, purchase_order_id FOR UPDATE""",
        (branch_id, run_at - timedelta(hours=24)),
    )
    orders = cur.fetchall()
    for po in orders:
        cur.execute("SELECT goods_receipt_id FROM goods_receipts WHERE purchase_order_id=%s AND NOT _is_deleted", (po["purchase_order_id"],))
        if cur.fetchone():
            cur.execute("UPDATE purchase_orders SET status='RECEIVED' WHERE purchase_order_id=%s AND NOT _is_deleted", (po["purchase_order_id"],))
            continue
        cur.execute(
            """SELECT poi.purchase_order_item_id, poi.stock_item_id, poi.ordered_quantity,
                      poi.uom_id, poi.expected_unit_cost, si.stock_item_code,
                      si.track_expiry, si.base_uom_id
               FROM purchase_order_items poi
               JOIN stock_items si ON si.stock_item_id=poi.stock_item_id AND NOT si._is_deleted
               WHERE poi.purchase_order_id=%s AND NOT poi._is_deleted ORDER BY poi.purchase_order_item_id""",
            (po["purchase_order_id"],),
        )
        lines = cur.fetchall()
        if not lines:
            continue
        receipt_no = f"SIM-GR-{po['purchase_order_id']}-{received_at.strftime('%Y%m%d%H%M%S')}"
        receipt = insert(
            cur,
            stats,
            """INSERT INTO goods_receipts
               (receipt_number,purchase_order_id,supplier_id,branch_id,received_at,received_by,
                supplier_invoice_number,notes)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING goods_receipt_id""",
            (receipt_no, po["purchase_order_id"], po["supplier_id"], branch_id, received_at,
             receiver_id, "SIM-INV-" + receipt_no, "Nhận hàng tự động sau thời gian chờ mô phỏng 24 giờ."),
        )
        receipt_id = receipt["goods_receipt_id"]
        for line in lines:
            lot_code = f"SIM-RCV-{po['purchase_order_id']}-{line['stock_item_id']}-{run_at.strftime('%Y%m%d')}"
            expiry = business_date + timedelta(days=SHELF_LIFE_DAYS.get(line["stock_item_code"], 180)) if line["track_expiry"] else None
            lot = insert(
                cur,
                stats,
                """INSERT INTO inventory_lots
                   (stock_item_id,lot_code,goods_receipt_id,received_at,expires_at,unit_cost,notes)
                   VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING inventory_lot_id""",
                (line["stock_item_id"], lot_code, receipt_id, business_date, expiry,
                 line["expected_unit_cost"], "Lô nhận từ PO mô phỏng; hạn dùng là dữ liệu ước tính."),
            )
            insert(
                cur,
                stats,
                """INSERT INTO goods_receipt_items
                   (goods_receipt_id,purchase_order_item_id,stock_item_id,inventory_lot_id,
                    received_quantity,uom_id,actual_unit_cost,notes)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                (receipt_id, line["purchase_order_item_id"], line["stock_item_id"], lot["inventory_lot_id"],
                 line["ordered_quantity"], line["uom_id"], line["expected_unit_cost"], "Nhận đủ theo lượng đặt mô phỏng."),
            )
            insert(
                cur,
                stats,
                """INSERT INTO stock_movements
                   (branch_id,stock_item_id,inventory_lot_id,movement_type,quantity_delta,uom_id,
                    unit_cost,occurred_at,source_type,source_id,idempotency_key,created_by,notes)
                   VALUES (%s,%s,%s,'PURCHASE_RECEIPT',%s,%s,%s,%s,'GOODS_RECEIPT',%s,%s,%s,%s)""",
                (branch_id, line["stock_item_id"], lot["inventory_lot_id"], line["ordered_quantity"],
                 line["uom_id"], line["expected_unit_cost"], received_at, receipt_id,
                 f"SIM-GR:{receipt_no}:{line['stock_item_code']}", receiver_id, "Nhập kho từ đơn mua hàng."),
            )
            cur.execute(
                """UPDATE supplier_products SET last_known_unit_cost=%s
                   WHERE supplier_id=%s AND stock_item_id=%s AND NOT _is_deleted""",
                (line["expected_unit_cost"], po["supplier_id"], line["stock_item_id"]),
            )
        cur.execute("UPDATE purchase_orders SET status='RECEIVED' WHERE purchase_order_id=%s AND NOT _is_deleted", (po["purchase_order_id"],))
        stats["receipts"] += 1


def write_expired_stock(cur, stats: dict, branch_id: int, run_at: datetime,
                        business_date: date, employee_id: int):
    cur.execute(
        """SELECT si.stock_item_id,si.stock_item_code,si.base_uom_id,il.inventory_lot_id,
                  SUM(sm.quantity_delta) AS balance
           FROM stock_movements sm
           JOIN inventory_lots il ON il.inventory_lot_id=sm.inventory_lot_id AND NOT il._is_deleted
           JOIN stock_items si ON si.stock_item_id=sm.stock_item_id AND NOT si._is_deleted
           WHERE sm.branch_id=%s AND NOT sm._is_deleted AND il.expires_at < %s
           GROUP BY si.stock_item_id,si.stock_item_code,si.base_uom_id,il.inventory_lot_id
           HAVING SUM(sm.quantity_delta)>0""",
        (branch_id, business_date),
    )
    for row in cur.fetchall():
        quantity = qty(row["balance"])
        waste = insert(
            cur,
            stats,
            """INSERT INTO waste_records
               (branch_id,stock_item_id,inventory_lot_id,quantity,uom_id,reason_code,recorded_at,recorded_by,notes)
               VALUES (%s,%s,%s,%s,%s,'EXPIRED',%s,%s,%s) RETURNING waste_record_id""",
            (branch_id, row["stock_item_id"], row["inventory_lot_id"], quantity,
             row["base_uom_id"], run_at, employee_id, "Tự động loại khỏi tồn khả dụng khi lô đã quá hạn."),
        )
        insert(
            cur,
            stats,
            """INSERT INTO stock_movements
               (branch_id,stock_item_id,inventory_lot_id,movement_type,quantity_delta,uom_id,
                occurred_at,source_type,source_id,idempotency_key,created_by,notes)
               VALUES (%s,%s,%s,'WASTE',%s,%s,%s,'WASTE_RECORD',%s,%s,%s,%s)""",
            (branch_id, row["stock_item_id"], row["inventory_lot_id"], -quantity,
             row["base_uom_id"], run_at, waste["waste_record_id"],
             f"SIM-WASTE:{row['inventory_lot_id']}:{business_date.isoformat()}", employee_id,
             "Hạch toán giảm tồn lô hết hạn."),
        )
        stats["waste"] += 1


def close_shifts_if_needed(cur, stats: dict, branch_id: int, run_at: datetime,
                           local_now: datetime, is_open: bool, opening_at: datetime):
    cur.execute(
        "SELECT shift_id,shift_code,opened_at,opening_cash FROM shifts "
        "WHERE branch_id=%s AND NOT _is_deleted AND status='OPEN' ORDER BY opened_at FOR UPDATE",
        (branch_id,),
    )
    active = cur.fetchall()
    current_shift = None
    for shift in active:
        opened_local_date = shift["opened_at"].astimezone(local_now.tzinfo).date()
        stale = opened_local_date != local_now.date() or not is_open
        if stale:
            cur.execute(
                """SELECT COALESCE(SUM(CASE
                       WHEN movement_type IN ('SALE_CASH_IN','FLOAT_IN','OTHER_IN') THEN amount
                       WHEN movement_type IN ('CASH_OUT','REFUND_OUT','OTHER_OUT') THEN -amount
                       ELSE 0 END),0) AS net_movement
                   FROM cash_movements WHERE shift_id=%s AND NOT _is_deleted""",
                (shift["shift_id"],),
            )
            net = Decimal(str(cur.fetchone()["net_movement"]))
            counted = money(Decimal(str(shift["opening_cash"])) + net)
            scheduled_close = datetime.combine(
                opened_local_date, CLOSE_TIME, tzinfo=local_now.tzinfo
            )
            closed_at = max(shift["opened_at"], min(run_at, scheduled_close))
            cur.execute(
                "UPDATE shifts SET closed_at=%s,counted_cash=%s,status='CLOSED' WHERE shift_id=%s AND NOT _is_deleted",
                (closed_at, counted, shift["shift_id"]),
            )
            stats["shifts_closed"] += 1
        else:
            current_shift = shift

    if is_open and current_shift is None:
        cashier = choose_employee(cur, branch_id, "EMP-005")
        shift_code = f"SIM-SHIFT-{branch_id}-{local_now.strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"
        current_shift = insert(
            cur,
            stats,
            """INSERT INTO shifts
               (branch_id,employee_id,shift_code,opened_at,opening_cash,status,notes)
               VALUES (%s,%s,%s,%s,%s,'OPEN',%s) RETURNING shift_id,shift_code,opened_at,opening_cash""",
            (branch_id, cashier["employee_id"], shift_code, opening_at, OPENING_CASH,
             "Ca làm mô phỏng; tiền quỹ đầu ca được lưu tại opening_cash."),
        )
        stats["shifts_opened"] += 1
    return current_shift


def maybe_process_return(cur, stats: dict, branch_id: int, run_at: datetime,
                         returned_at: datetime,
                         shift, employee_id: int):
    if not shift or random.random() >= 0.015:
        return
    cur.execute(
        """SELECT s.sale_id,s.receipt_number,si.sale_item_id,si.quantity,si.line_total,
                  p.stock_item_id,si.product_name_snapshot,sm.inventory_lot_id,
                  sm.uom_id,sm.unit_cost,pay.payment_method
           FROM sales s
           JOIN sale_items si ON si.sale_id=s.sale_id AND NOT si._is_deleted
           JOIN products p ON p.product_id=si.product_id AND NOT p._is_deleted
           JOIN stock_movements sm ON sm.source_type='SALE' AND sm.source_id=s.sale_id
                AND sm.stock_item_id=p.stock_item_id AND NOT sm._is_deleted AND sm.movement_type='SALE' AND sm.quantity_delta<0
           JOIN inventory_lots il ON il.inventory_lot_id=sm.inventory_lot_id AND NOT il._is_deleted
           LEFT JOIN payments pay ON pay.sale_id=s.sale_id AND NOT pay._is_deleted AND pay.status='CAPTURED'
           WHERE s.branch_id=%s AND NOT s._is_deleted AND s.status IN ('COMPLETED','PARTIALLY_REFUNDED')
             AND s.completed_at <= %s - INTERVAL '24 hours'
             AND s.completed_at >= %s - INTERVAL '30 days'
             AND p.product_type='MERCH' AND si.quantity=1
             AND sm.quantity_delta <= -1 AND (il.expires_at IS NULL OR il.expires_at >= %s::date)
             AND NOT EXISTS (SELECT 1 FROM return_items ri JOIN returns r ON r.return_id=ri.return_id
                             WHERE ri.sale_item_id=si.sale_item_id AND NOT ri._is_deleted
                               AND NOT r._is_deleted AND r.status='COMPLETED')
           ORDER BY random() LIMIT 1""",
        (branch_id, run_at, run_at, run_at.date()),
    )
    item = cur.fetchone()
    if not item:
        return
    return_no = f"SIM-RET-{run_at.strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6].upper()}"
    employee = choose_employee(cur, branch_id, "EMP-005")
    returned = insert(
        cur,
        stats,
        """INSERT INTO returns
           (return_number,sale_id,processed_by,returned_at,reason,status,refund_total)
           VALUES (%s,%s,%s,%s,%s,'COMPLETED',%s) RETURNING return_id""",
        (return_no, item["sale_id"], employee["employee_id"], returned_at,
         "Khách trả lại vật phẩm chưa sử dụng; tình huống hiếm trong mô phỏng.", money(item["line_total"])),
    )
    insert(
        cur,
        stats,
        """INSERT INTO return_items
           (return_id,sale_item_id,quantity,restockable,refund_amount,notes)
           VALUES (%s,%s,1,TRUE,%s,%s)""",
        (returned["return_id"], item["sale_item_id"], money(item["line_total"]),
         "Chỉ hàng merchandise nguyên trạng được nhập lại."),
    )
    insert(
        cur,
        stats,
        """INSERT INTO stock_movements
           (branch_id,stock_item_id,inventory_lot_id,movement_type,quantity_delta,uom_id,
            unit_cost,occurred_at,source_type,source_id,idempotency_key,created_by,notes)
           VALUES (%s,%s,%s,'RETURN_IN',1,%s,%s,%s,'RETURN',%s,%s,%s,%s)""",
        (branch_id, item["stock_item_id"], item["inventory_lot_id"], item["uom_id"],
         item["unit_cost"], returned_at, returned["return_id"], f"SIM-RETURN:{return_no}",
         employee["employee_id"], "Nhập lại hàng merchandise nguyên trạng."),
    )
    cur.execute("SELECT payment_method FROM payments WHERE sale_id=%s AND NOT _is_deleted AND status='CAPTURED' LIMIT 1", (item["sale_id"],))
    payment = cur.fetchone()
    if payment and payment["payment_method"] == "CASH":
        insert(
            cur,
            stats,
            """INSERT INTO cash_movements
               (shift_id,movement_type,amount,occurred_at,sale_id,recorded_by,description)
               VALUES (%s,'REFUND_OUT',%s,%s,%s,%s,%s)""",
            (shift["shift_id"], money(item["line_total"]), returned_at, item["sale_id"],
             employee["employee_id"], "Hoàn tiền mặt cho đơn trả hàng."),
        )
    cur.execute(
        """SELECT COUNT(*) AS line_count,
                  COUNT(*) FILTER (WHERE si.quantity <= COALESCE(rq.returned_qty,0)) AS fully_returned
           FROM sale_items si
           LEFT JOIN (SELECT ri.sale_item_id,SUM(ri.quantity) AS returned_qty
                      FROM return_items ri JOIN returns r ON r.return_id=ri.return_id
                      WHERE NOT ri._is_deleted AND NOT r._is_deleted AND r.status='COMPLETED'
                      GROUP BY ri.sale_item_id) rq
             ON rq.sale_item_id=si.sale_item_id
           WHERE si.sale_id=%s AND NOT si._is_deleted""",
        (item["sale_id"],),
    )
    returned_state = cur.fetchone()
    sale_status = "REFUNDED" if returned_state["line_count"] == returned_state["fully_returned"] else "PARTIALLY_REFUNDED"
    cur.execute("UPDATE sales SET status=%s WHERE sale_id=%s AND NOT _is_deleted", (sale_status, item["sale_id"]))
    if sale_status == "REFUNDED":
        cur.execute("UPDATE payments SET status='REFUNDED' WHERE sale_id=%s AND NOT _is_deleted AND status='CAPTURED'", (item["sale_id"],))
    stats["returns"] += 1


def fetch_products(cur, business_date: date):
    cur.execute(
        """SELECT p.product_id,p.sku,p.product_name,p.product_type,p.sell_uom_id,
                  p.stock_item_id,p.unit_price,c.category_code
           FROM products p JOIN product_categories c ON c.category_id=p.category_id
           WHERE p.is_active=TRUE AND NOT p._is_deleted AND NOT c._is_deleted AND p.unit_price>0
             AND EXISTS (SELECT 1 FROM units_of_measure u WHERE u.uom_id=p.sell_uom_id AND NOT u._is_deleted)
             AND (p.stock_item_id IS NULL OR EXISTS (
                 SELECT 1 FROM stock_items st WHERE st.stock_item_id=p.stock_item_id AND NOT st._is_deleted AND st.is_active))
             AND (p.available_from IS NULL OR p.available_from<=%s)
             AND (p.available_to IS NULL OR p.available_to>=%s)
           ORDER BY p.product_id""",
        (business_date, business_date),
    )
    return cur.fetchall()


def recipe_needs(cur, product_id: int, quantity: Decimal, business_date: date):
    cur.execute(
        """SELECT ri.stock_item_id,ri.quantity,r.yield_quantity,ri.is_optional
           FROM recipes r JOIN recipe_items ri ON ri.recipe_id=r.recipe_id
           WHERE r.product_id=%s AND r.is_active=TRUE AND NOT r._is_deleted AND NOT ri._is_deleted AND r.effective_from<=%s
             AND (r.effective_to IS NULL OR r.effective_to>=%s)
           ORDER BY ri.recipe_item_id""",
        (product_id, business_date, business_date),
    )
    rows = cur.fetchall()
    if not rows:
        return None
    needs = []
    for row in rows:
        if row["is_optional"] and random.random() < 0.2:
            continue
        needs.append((row["stock_item_id"], Decimal(str(row["quantity"])) * quantity / Decimal(str(row["yield_quantity"]))))
    return needs or None


def produce_low_stock(cur, stats: dict, branch_id: int, run_at: datetime,
                      business_date: date, timezone: ZoneInfo, inventory: Inventory,
                      baker_id: int, production_start_at: datetime,
                      production_end_at: datetime):
    products = fetch_products(cur, business_date)
    production_window = production_end_at - production_start_at
    product_count = max(1, len(products))
    for product_index, product in enumerate(products):
        if product["product_type"] not in ("BAKERY", "RETAIL") or product["stock_item_id"] is None:
            continue
        par = Decimal("12")
        if product["category_code"] == "ENTREMET":
            par = Decimal("2")
        elif product["category_code"] == "MACARON":
            par = Decimal("12")
        elif product["product_type"] == "RETAIL":
            par = Decimal("2")
        if inventory.balance(product["stock_item_id"]) >= par:
            continue
        cur.execute(
            """SELECT 1 FROM production_batches
               WHERE branch_id=%s AND NOT _is_deleted AND product_id=%s AND batch_number LIKE 'SIM-PROD-%%'
                 AND completed_at >= %s AND completed_at <= %s LIMIT 1""",
            (branch_id, product["product_id"], run_at - timedelta(hours=4), run_at),
        )
        if cur.fetchone():
            continue
        cur.execute(
            """SELECT recipe_id,yield_quantity,yield_uom_id FROM recipes
               WHERE product_id=%s AND is_active=TRUE AND NOT _is_deleted AND effective_from<=%s
                 AND (effective_to IS NULL OR effective_to>=%s)
               ORDER BY effective_from DESC,recipe_id DESC LIMIT 1""",
            (product["product_id"], business_date, business_date),
        )
        recipe = cur.fetchone()
        if not recipe:
            continue
        produced = Decimal(str(recipe["yield_quantity"]))
        cur.execute(
            "SELECT stock_item_id,quantity,is_optional FROM recipe_items WHERE recipe_id=%s AND NOT _is_deleted ORDER BY recipe_item_id",
            (recipe["recipe_id"],),
        )
        recipe_lines = cur.fetchall()
        if not recipe_lines:
            continue  # A recipe with all components deleted must not produce free stock.
        needs = []
        for line in recipe_lines:
            if line["is_optional"] and random.random() < 0.2:
                continue
            needs.append((line["stock_item_id"], Decimal(str(line["quantity"]))))
        allocations = inventory.reserve(needs)
        if allocations is None:
            continue
        started_at = production_start_at + production_window * product_index / product_count
        completed_at = production_start_at + production_window * (product_index + 1) / product_count
        if completed_at <= started_at:
            completed_at = started_at + timedelta(microseconds=1)
        batch_no = f"SIM-PROD-{business_date.strftime('%Y%m%d')}-{product['sku']}-{uuid.uuid4().hex[:6].upper()}"
        batch = insert(
            cur,
            stats,
            """INSERT INTO production_batches
               (batch_number,branch_id,product_id,recipe_id,planned_quantity,produced_quantity,
                uom_id,status,started_at,completed_at,produced_by,notes)
               VALUES (%s,%s,%s,%s,%s,%s,%s,'COMPLETED',%s,%s,%s,%s)
               RETURNING production_batch_id""",
            (batch_no, branch_id, product["product_id"], recipe["recipe_id"], produced,
             produced, recipe["yield_uom_id"], started_at, completed_at, baker_id,
             "Mẻ bổ sung do tồn thành phẩm xuống dưới mức par mô phỏng."),
        )
        total_cost = Decimal("0")
        cost_known = True
        for allocation in allocations:
            if allocation["unit_cost"] is None:
                cost_known = False
            else:
                total_cost += allocation["quantity"] * allocation["unit_cost"]
            insert(
                cur,
                stats,
                """INSERT INTO production_consumptions
                   (production_batch_id,stock_item_id,inventory_lot_id,quantity_used,uom_id,unit_cost,notes)
                   VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                (batch["production_batch_id"], allocation["stock_item_id"], allocation["inventory_lot_id"],
                 allocation["quantity"], allocation["uom_id"], allocation["unit_cost"], "Tiêu hao theo recipe và phân bổ FEFO."),
            )
            insert(
                cur,
                stats,
                """INSERT INTO stock_movements
                   (branch_id,stock_item_id,inventory_lot_id,movement_type,quantity_delta,uom_id,
                    unit_cost,occurred_at,source_type,source_id,idempotency_key,created_by,notes)
                   VALUES (%s,%s,%s,'PRODUCTION_CONSUMPTION',%s,%s,%s,%s,'PRODUCTION_BATCH',%s,%s,%s,%s)""",
                (branch_id, allocation["stock_item_id"], allocation["inventory_lot_id"],
                 -qty(allocation["quantity"]), allocation["uom_id"], allocation["unit_cost"], started_at,
                 batch["production_batch_id"], f"SIM-PROD-CONSUME:{batch_no}:{allocation['stock_item_code']}:{allocation['inventory_lot_id']}",
                 baker_id, "Giảm nguyên liệu theo mẻ sản xuất."),
            )
            stats["stock_movements"] += 1
        cur.execute("SELECT stock_item_code,base_uom_id FROM stock_items WHERE stock_item_id=%s AND NOT _is_deleted", (product["stock_item_id"],))
        output_item = cur.fetchone()
        expiry_days = SHELF_LIFE_DAYS.get(output_item["stock_item_code"], 2)
        lot_code = f"SIM-PROD-LOT-{batch['production_batch_id']}-{product['sku']}"
        out_lot = insert(
            cur,
            stats,
            """INSERT INTO inventory_lots
               (stock_item_id,lot_code,manufactured_at,received_at,expires_at,unit_cost,notes)
               VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING inventory_lot_id""",
            (product["stock_item_id"], lot_code, business_date, business_date,
             business_date + timedelta(days=expiry_days),
             (total_cost / produced if cost_known and produced else None),
             "Lô thành phẩm tạo trong lượt vận hành này."),
        )
        unit_cost = total_cost / produced if cost_known and produced else None
        insert(
            cur,
            stats,
            """INSERT INTO stock_movements
               (branch_id,stock_item_id,inventory_lot_id,movement_type,quantity_delta,uom_id,
                unit_cost,occurred_at,source_type,source_id,idempotency_key,created_by,notes)
               VALUES (%s,%s,%s,'PRODUCTION_OUTPUT',%s,%s,%s,%s,'PRODUCTION_BATCH',%s,%s,%s,%s)""",
            (branch_id, product["stock_item_id"], out_lot["inventory_lot_id"], qty(produced),
             output_item["base_uom_id"], unit_cost, completed_at, batch["production_batch_id"],
             f"SIM-PROD-OUT:{batch_no}", baker_id, "Tăng tồn thành phẩm sau khi hoàn tất mẻ."),
        )
        inventory.add_lot(
            product["stock_item_id"],
            {"inventory_lot_id": out_lot["inventory_lot_id"], "lot_code": lot_code,
             "expires_at": business_date + timedelta(days=expiry_days), "received_at": business_date,
             "unit_cost": unit_cost, "balance": produced},
        )
        stats["stock_movements"] += 1
        stats["production_batches"] += 1


def promotion_for_sale(cur, run_at: datetime):
    cur.execute(
        """SELECT p.promotion_id,p.promotion_code,p.promotion_type,p.discount_value,
                  p.minimum_order_amount,p.max_uses,COUNT(sp.sale_promotion_id) AS used_count
           FROM promotions p LEFT JOIN sale_promotions sp ON sp.promotion_id=p.promotion_id
                AND NOT sp._is_deleted
                AND EXISTS (SELECT 1 FROM sales used_sale WHERE used_sale.sale_id=sp.sale_id AND NOT used_sale._is_deleted)
           WHERE p.is_active=TRUE AND NOT p._is_deleted AND p.starts_at<=%s AND (p.ends_at IS NULL OR p.ends_at>=%s)
           GROUP BY p.promotion_id
           HAVING p.max_uses IS NULL OR COUNT(sp.sale_promotion_id)<p.max_uses
           ORDER BY p.promotion_id LIMIT 1""",
        (run_at, run_at),
    )
    promotion = cur.fetchone()
    if not promotion:
        return None, set()
    cur.execute("SELECT product_id FROM promotion_products WHERE promotion_id=%s AND NOT _is_deleted", (promotion["promotion_id"],))
    return promotion, {row["product_id"] for row in cur.fetchall()}


def create_sale(cur, stats: dict, faker, branch_id: int,
                opened_at: datetime, completed_at: datetime, business_date: date,
                cashier_id: int, shift, inventory: Inventory,
                products: list[dict], weather: dict, calendar: dict):
    channel = random.choices(["IN_STORE", "TAKEAWAY", "DELIVERY"], weights=[55, 40, 5], k=1)[0]
    candidates = [product for product in products if product["product_type"] != "BEVERAGE"]
    random.shuffle(candidates)
    cart = []
    target_lines = random.randint(1, MAX_CART_LINES)
    for product in candidates:
        if len(cart) >= target_lines:
            break
        quantity = Decimal("1")
        if product["stock_item_id"] is None:
            continue
        needs = [(product["stock_item_id"], quantity)]
        if product["product_type"] == "BAKERY" and channel in ("TAKEAWAY", "DELIVERY"):
            cur.execute("SELECT stock_item_id FROM stock_items WHERE stock_item_code='PACK_BAKERY_BOX' AND NOT _is_deleted AND is_active")
            package = cur.fetchone()
            if package:
                needs.append((package["stock_item_id"], Decimal("1")))
        allocations = inventory.reserve(needs)
        if allocations is None:
            continue
        cart.append({"product": product, "quantity": quantity, "allocations": allocations})

    # A receipt represents one customer, so it can contain zero or one drink,
    # always as a single serving. Hot days make the optional drink more likely.
    if random.random() < weather["drink_probability"]:
        drinks = [product for product in products if product["product_type"] == "BEVERAGE"]
        random.shuffle(drinks)
        for drink in drinks:
            needs = recipe_needs(cur, drink["product_id"], Decimal("1"), business_date)
            if needs is None:
                continue
            if channel in ("TAKEAWAY", "DELIVERY"):
                cur.execute("SELECT stock_item_id FROM stock_items WHERE stock_item_code='PACK_CUP' AND NOT _is_deleted AND is_active")
                cup = cur.fetchone()
                if cup:
                    needs.append((cup["stock_item_id"], Decimal("1")))
            allocations = inventory.reserve(needs)
            if allocations is not None:
                cart.append({"product": drink, "quantity": Decimal("1"), "allocations": allocations})
                break
    if not cart:
        return False

    customer_id = random_customer(cur, stats, faker, opened_at)
    receipt = f"SIM-{completed_at.strftime('%Y%m%d%H%M%S%f')}-{uuid.uuid4().hex[:4].upper()}"
    subtotal = money(sum((money(line["product"]["unit_price"]) * line["quantity"] for line in cart), Decimal("0")))
    promotion, eligible = promotion_for_sale(cur, completed_at)
    promo_discount = Decimal("0.00")
    line_discounts = [Decimal("0.00") for _ in cart]
    if promotion and subtotal >= Decimal(str(promotion["minimum_order_amount"] or 0)):
        eligible_indexes = [i for i, line in enumerate(cart) if line["product"]["product_id"] in eligible]
        eligible_total = sum((money(cart[i]["product"]["unit_price"]) * cart[i]["quantity"] for i in eligible_indexes), Decimal("0"))
        if eligible_indexes and promotion["promotion_type"] == "PERCENT":
            pct = Decimal(str(promotion["discount_value"])) / Decimal("100")
            for i in eligible_indexes:
                line_discounts[i] = money(money(cart[i]["product"]["unit_price"]) * cart[i]["quantity"] * pct)
            promo_discount = sum(line_discounts, Decimal("0"))
        elif eligible_indexes and promotion["promotion_type"] == "FIXED_AMOUNT":
            promo_discount = min(money(promotion["discount_value"]), eligible_total)
            line_discounts[eligible_indexes[0]] = promo_discount

    after_promo = money(subtotal - promo_discount)
    loyalty_discount = Decimal("0.00")
    redeem_points = 0
    if customer_id is not None and random.random() < 0.08:
        cur.execute("SELECT COALESCE(SUM(points_delta),0) AS points FROM loyalty_transactions WHERE customer_id=%s AND NOT _is_deleted", (customer_id,))
        points = max(0, int(cur.fetchone()["points"]))
        eligible_points = int((after_promo * Decimal("0.5")) // LOYALTY_REDEMPTION_VND) * LOYALTY_REDEMPTION_POINTS
        redeem_points = min(points // LOYALTY_REDEMPTION_POINTS * LOYALTY_REDEMPTION_POINTS, eligible_points)
        if redeem_points >= LOYALTY_REDEMPTION_POINTS:
            loyalty_discount = money(Decimal(redeem_points // LOYALTY_REDEMPTION_POINTS) * LOYALTY_REDEMPTION_VND)
    total = money(subtotal - promo_discount - loyalty_discount)
    if total <= 0:
        return False

    # Spread loyalty redemption across sale lines so their net values reconcile
    # with the sale header even though the promotion itself remains separately tracked.
    final_line_discounts = list(line_discounts)
    if loyalty_discount > 0 and after_promo > 0:
        loyalty_left = loyalty_discount
        for index, line in enumerate(cart):
            net_line = money(line["product"]["unit_price"] * line["quantity"] - line_discounts[index])
            if index == len(cart) - 1:
                share = loyalty_left
            else:
                share = min(loyalty_left, money(loyalty_discount * net_line / after_promo))
            final_line_discounts[index] += share
            loyalty_left -= share

    sale = insert(
        cur,
        stats,
        """INSERT INTO sales
           (receipt_number,branch_id,customer_id,cashier_id,channel,status,opened_at,completed_at,
            subtotal,discount_total,tax_total,total_amount,idempotency_key,notes)
           VALUES (%s,%s,%s,%s,%s,'COMPLETED',%s,%s,%s,%s,0,%s,%s,%s)
           RETURNING sale_id""",
        (receipt, branch_id, customer_id, cashier_id, channel, opened_at, completed_at, subtotal,
         money(promo_discount + loyalty_discount), total, f"SIM:{receipt}",
         f"Đơn bán mô phỏng trước mốc chạy script; weather={weather['condition']}; "
         f"rain_level={weather['rain_level']}; weather_time={weather['observation_time']}; "
         f"day_type={calendar['day_type']}; holiday={calendar['holiday_name'] or 'none'}."),
    )
    sale_id = sale["sale_id"]
    stats["sales"] += 1
    for index, line in enumerate(cart, start=1):
        product = line["product"]
        unit_price = money(product["unit_price"])
        line_total = money(unit_price * line["quantity"] - final_line_discounts[index - 1])
        insert(
            cur,
            stats,
            """INSERT INTO sale_items
               (sale_id,product_id,quantity,uom_id,product_name_snapshot,unit_price,discount_amount,line_total,notes)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (sale_id, product["product_id"], line["quantity"], product["sell_uom_id"],
             product["product_name"], unit_price, final_line_discounts[index - 1], line_total,
             "Đã trừ tồn kho theo lô FEFO."),
        )
        stats["sale_items"] += 1
        for allocation in line["allocations"]:
            insert(
                cur,
                stats,
                """INSERT INTO stock_movements
                   (branch_id,stock_item_id,inventory_lot_id,movement_type,quantity_delta,uom_id,
                    unit_cost,occurred_at,source_type,source_id,idempotency_key,created_by,notes)
                   VALUES (%s,%s,%s,'SALE',%s,%s,%s,%s,'SALE',%s,%s,%s,%s)""",
                (branch_id, allocation["stock_item_id"], allocation["inventory_lot_id"],
                 -qty(allocation["quantity"]), allocation["uom_id"], allocation["unit_cost"],
                 completed_at, sale_id,
                 f"SIM-SALE:{receipt}:{index}:{allocation['stock_item_code']}:{allocation['inventory_lot_id']}",
                 cashier_id, f"Xuất kho cho {product['product_name']} trong đơn {receipt}."),
            )
            stats["stock_movements"] += 1
    if promotion and promo_discount > 0:
        insert(
            cur,
            stats,
            """INSERT INTO sale_promotions (sale_id,promotion_id,discount_amount,coupon_code,applied_at)
               VALUES (%s,%s,%s,%s,%s)""",
            (sale_id, promotion["promotion_id"], money(promo_discount), promotion["promotion_code"], completed_at),
        )
    if customer_id is not None and redeem_points:
        insert(
            cur,
            stats,
            """INSERT INTO loyalty_transactions
               (customer_id,sale_id,transaction_type,points_delta,occurred_at,idempotency_key,notes)
               VALUES (%s,%s,'REDEEM',%s,%s,%s,%s)""",
            (customer_id, sale_id, -redeem_points, completed_at, f"LOYALTY:{receipt}:REDEEM",
             f"Đổi {redeem_points} điểm lấy {loyalty_discount} VND giảm giá."),
        )
    if customer_id is not None:
        earned = int(total // LOYALTY_POINTS_PER_VND)
        if earned > 0:
            insert(
                cur,
                stats,
                """INSERT INTO loyalty_transactions
                   (customer_id,sale_id,transaction_type,points_delta,occurred_at,idempotency_key,notes)
                   VALUES (%s,%s,'EARN',%s,%s,%s,%s)""",
                (customer_id, sale_id, earned, completed_at, f"LOYALTY:{receipt}:EARN",
                 "Tích 1 điểm cho mỗi 10.000 VND thực trả."),
            )
    payment_method = random.choices(
        ["CASH", "E_WALLET", "CARD", "BANK_TRANSFER"], weights=[35, 40, 20, 5], k=1
    )[0]
    provider_ref = None if payment_method == "CASH" else f"SIM-PAY-{uuid.uuid4().hex[:12].upper()}"
    insert(
        cur,
        stats,
        """INSERT INTO payments
           (sale_id,payment_method,amount,currency_code,status,paid_at,provider_reference,notes)
           VALUES (%s,%s,%s,'VND','CAPTURED',%s,%s,%s)""",
        (sale_id, payment_method, total, completed_at, provider_ref, "Thanh toán giả lập hoàn tất."),
    )
    if payment_method == "CASH":
        insert(
            cur,
            stats,
            """INSERT INTO cash_movements
               (shift_id,movement_type,amount,occurred_at,sale_id,recorded_by,description)
               VALUES (%s,'SALE_CASH_IN',%s,%s,%s,%s,%s)""",
            (shift["shift_id"], total, completed_at, sale_id, cashier_id, f"Thu tiền mặt đơn {receipt}."),
        )
    stats["orders"] += 1
    return True


def create_reorder_pos(cur, stats: dict, branch_id: int, run_at: datetime,
                       inventory: Inventory, manager_id: int):
    supplier_lines: dict[int, list[dict]] = {}
    for item_id, item in inventory.items.items():
        if item["item_type"] not in ("RAW_MATERIAL", "PACKAGING", "RETAIL_GOOD"):
            continue
        reorder_level = item["reorder_level"]
        if reorder_level is None or inventory.balance(item_id) > reorder_level:
            continue
        cur.execute(
            """SELECT 1 FROM purchase_order_items poi
               JOIN purchase_orders po ON po.purchase_order_id=poi.purchase_order_id
               WHERE poi.stock_item_id=%s AND po.branch_id=%s AND NOT poi._is_deleted AND NOT po._is_deleted
                 AND po.status IN ('SENT','PARTIALLY_RECEIVED') LIMIT 1""",
            (item_id, branch_id),
        )
        if cur.fetchone():
            continue
        cur.execute(
            """SELECT sp.supplier_id,sp.last_known_unit_cost
               FROM supplier_products sp JOIN suppliers s ON s.supplier_id=sp.supplier_id
               WHERE sp.stock_item_id=%s AND sp.is_active=TRUE AND s.is_active=TRUE AND NOT sp._is_deleted AND NOT s._is_deleted
               ORDER BY (sp.last_known_unit_cost IS NULL),sp.supplier_product_id LIMIT 1""",
            (item_id,),
        )
        supplier = cur.fetchone()
        if not supplier:
            continue
        expected_cost = supplier["last_known_unit_cost"]
        if expected_cost is None:
            known_lots = [lot for lot in inventory.lots.get(item_id, []) if lot["unit_cost"] is not None]
            if known_lots:
                latest_lot = max(known_lots, key=lambda lot: lot["received_at"] or date.min)
                expected_cost = latest_lot["unit_cost"]
        quantity = max(reorder_level * Decimal("2") - inventory.balance(item_id), reorder_level)
        supplier_lines.setdefault(supplier["supplier_id"], []).append(
            {"item": item, "quantity": qty(quantity), "cost": expected_cost}
        )

    for supplier_id, lines in supplier_lines.items():
        po_no = f"SIM-PO-{run_at.strftime('%Y%m%d%H%M%S')}-{supplier_id}-{uuid.uuid4().hex[:5].upper()}"
        po = insert(
            cur,
            stats,
            """INSERT INTO purchase_orders
               (po_number,supplier_id,branch_id,ordered_at,expected_at,status,currency_code,notes,created_by)
               VALUES (%s,%s,%s,%s,NULL,'SENT','VND',%s,%s) RETURNING purchase_order_id""",
            (po_no, supplier_id, branch_id, run_at,
             "Tự động đặt thêm khi tồn khả dụng bằng hoặc thấp hơn reorder_level; nhận sau tối thiểu 24 giờ.",
             manager_id),
        )
        for line in lines:
            insert(
                cur,
                stats,
                """INSERT INTO purchase_order_items
                   (purchase_order_id,stock_item_id,ordered_quantity,uom_id,expected_unit_cost,notes)
                   VALUES (%s,%s,%s,%s,%s,%s)""",
                (po["purchase_order_id"], line["item"]["stock_item_id"], line["quantity"],
                 line["item"]["base_uom_id"], line["cost"], "Đặt hàng theo đơn vị cơ sở của tồn kho."),
            )
        stats["purchase_orders"] += 1


def simulate(args, run_at_override=None, run_label=None):
    if holiday_calendar is None:
        raise RuntimeError("Thiếu lịch ngày lễ Việt Nam. Cài bằng: pip install holidays")
    dsn = args.dsn or project_database_url()
    if not dsn:
        raise RuntimeError("Chưa có DATABASE_URL trong .env hoặc môi trường; hoặc truyền --dsn.")
    if args.max_orders < 1:
        raise RuntimeError("--max-orders phải lớn hơn hoặc bằng 1.")

    seed = args.seed if args.seed is not None else secrets.randbits(32)
    random.seed(seed)
    faker = make_faker()
    if faker:
        faker.seed_instance(seed)
    run_key = f"SIM-{run_label + '-' if run_label else ''}{uuid.uuid4().hex}"
    stats = {
        "records_created": 0, "sales": 0, "orders": 0, "sale_items": 0,
        "customers": 0, "production_batches": 0, "stock_movements": 0,
        "purchase_orders": 0, "receipts": 0, "waste": 0, "returns": 0,
        "shifts_opened": 0, "shifts_closed": 0,
    }

    conn = db_connect(dsn)
    try:
        conn.autocommit = False
        with conn.cursor() as cur:
            require_row_audit(cur)
            cur.execute(
                """SELECT branch_id,branch_code,branch_name,timezone,opening_date
                   FROM branches WHERE branch_code=%s AND is_active=TRUE AND NOT _is_deleted FOR UPDATE""",
                (args.branch,),
            )
            branch = cur.fetchone()
            if not branch:
                raise RuntimeError(f"Không tìm thấy chi nhánh đang hoạt động: {args.branch}")
            if branch["opening_date"] is None:
                raise RuntimeError("Chi nhánh chưa có opening_date trong bảng branches.")
            tz = ZoneInfo(branch["timezone"] or "Asia/Ho_Chi_Minh")
            if run_at_override is None:
                # Capture only after the branch lock, so waiting for another run does not
                # cause this invocation to write timestamps from before it actually starts.
                cur.execute("SELECT clock_timestamp() AS run_at")
                run_at = cur.fetchone()["run_at"]
            else:
                if run_at_override.tzinfo is None:
                    raise RuntimeError("Thời điểm backfill phải có timezone.")
                run_at = run_at_override.astimezone(tz)
            local_now = run_at.astimezone(tz)
            business_date = local_now.date()
            if business_date < branch["opening_date"]:
                conn.rollback()
                print(
                    f"Chưa đến ngày mở bán ({branch['opening_date']}); không ghi dữ liệu vận hành. "
                    f"Database hiện tại: {local_now.isoformat()}"
                )
                return 0

            is_open = OPEN_TIME <= local_now.time().replace(tzinfo=None) < CLOSE_TIME
            run_description = (
                f"Backfill lịch sử {run_label}; "
                if run_label else "Một lượt mô phỏng tại thời điểm thực; "
            )
            run = insert(
                cur,
                stats,
                """INSERT INTO simulation_runs
                   (run_key,business_date,random_seed,status,started_at,notes)
                   VALUES (%s,%s,%s,'RUNNING',%s,%s) RETURNING simulation_run_id""",
                (run_key, business_date, seed, run_at,
                 f"{run_description}giờ hoạt động {OPEN_TIME.strftime('%H:%M')}-{CLOSE_TIME.strftime('%H:%M')} {branch['timezone']}."),
            )
            cur.execute("SAVEPOINT operations")
            try:
                weather = get_weather_context(business_date, branch["timezone"], local_now)
                calendar = calendar_context(business_date)
                manager = choose_employee(cur, branch["branch_id"], "EMP-001")
                baker = choose_employee(cur, branch["branch_id"], "EMP-002")
                order_count = simulated_order_count(args.max_orders, weather, calendar) if is_open else 0
                (
                    opening_at,
                    activity_start_at,
                    production_start_at,
                    production_end_at,
                    sale_events,
                ) = build_event_timeline(run_at, tz, order_count)
                process_due_purchase_orders(cur, stats, branch["branch_id"], run_at,
                                            business_date, manager["employee_id"], activity_start_at)
                write_expired_stock(cur, stats, branch["branch_id"], activity_start_at,
                                    business_date, manager["employee_id"])
                shift = close_shifts_if_needed(cur, stats, branch["branch_id"], run_at,
                                               local_now, is_open, opening_at)
                if is_open:
                    maybe_process_return(cur, stats, branch["branch_id"], run_at,
                                         activity_start_at,
                                         shift, manager["employee_id"])

                inventory = Inventory(cur, branch["branch_id"], business_date)
                if is_open and production_end_at > production_start_at:
                    produce_low_stock(cur, stats, branch["branch_id"], run_at,
                                      business_date, tz, inventory, baker["employee_id"],
                                      production_start_at, production_end_at)
                if is_open:
                    cashier = choose_employee(cur, branch["branch_id"], "EMP-005")
                    products = fetch_products(cur, business_date)
                    for opened_at, completed_at in sale_events:
                        create_sale(cur, stats, faker, branch["branch_id"],
                                    opened_at, completed_at, business_date,
                                    cashier["employee_id"], shift,
                                    inventory, products, weather, calendar)

                create_reorder_pos(cur, stats, branch["branch_id"], run_at,
                                   inventory, manager["employee_id"])
                run_notes = (
                    f" | {'ĐANG MỞ CỬA' if is_open else 'NGOÀI GIỜ BÁN'}; đơn tạo: {stats['orders']}; "
                    f"weather={weather['condition']}; rain_level={weather['rain_level']}; "
                    f"weather_time={weather['observation_time']}; temp_c={weather['temperature_2m_c']}; "
                    f"rain_mm_last_hour={weather['rain_mm']}; precipitation_mm_last_hour={weather['precipitation_mm']}; "
                    f"weather_code={weather['weather_code']}; cloud_cover_pct={weather['cloud_cover_pct']}; "
                    f"humidity_pct={weather['relative_humidity_pct']}; "
                    f"shortwave_w_m2={weather['shortwave_radiation_w_m2']}; "
                    f"order_factor={weather['order_factor']:.2f}; "
                    f"drink_probability={weather['drink_probability']:.2f}; "
                    f"day_type={calendar['day_type']}; holiday={calendar['holiday_name'] or 'none'}; "
                    f"weather_source={weather.get('source_url') or weather['status']}; "
                    "weather_attribution=Open-Meteo.com CC BY 4.0."
                )
                if run_at_override is None:
                    cur.execute(
                        """UPDATE simulation_runs
                           SET status='COMPLETED',finished_at=clock_timestamp(),records_created=%s,
                               notes=notes || %s
                           WHERE simulation_run_id=%s""",
                        (stats["records_created"], run_notes, run["simulation_run_id"]),
                    )
                else:
                    finished_at = run_at + timedelta(seconds=random.randint(30, 180))
                    cur.execute(
                        """UPDATE simulation_runs
                           SET status='COMPLETED',finished_at=%s,records_created=%s,
                               notes=notes || %s
                           WHERE simulation_run_id=%s""",
                        (finished_at, stats["records_created"], run_notes, run["simulation_run_id"]),
                    )
                conn.commit()
            except Exception as exc:
                cur.execute("ROLLBACK TO SAVEPOINT operations")
                if run_at_override is None:
                    cur.execute(
                        """UPDATE simulation_runs SET status='FAILED',finished_at=clock_timestamp(),
                           records_created=0,error_message=%s WHERE simulation_run_id=%s""",
                        (str(exc)[:2000], run["simulation_run_id"]),
                    )
                else:
                    failed_at = run_at + timedelta(seconds=random.randint(5, 30))
                    cur.execute(
                        """UPDATE simulation_runs SET status='FAILED',finished_at=%s,
                           records_created=0,error_message=%s WHERE simulation_run_id=%s""",
                        (failed_at, str(exc)[:2000], run["simulation_run_id"]),
                    )
                conn.commit()
                raise

        print(f"Chi nhánh: {branch['branch_name']} ({branch['branch_code']})")
        print(f"Thời điểm database: {local_now.isoformat()} | trạng thái: {'đang mở cửa' if is_open else 'ngoài giờ bán'}")
        temperature = weather["temperature_2m_c"]
        temperature_text = f"{temperature:.1f}°C" if temperature is not None else "không có dữ liệu"
        rain = weather["rain_mm"]
        rain_text = f"{rain:.1f} mm" if rain is not None else "không có dữ liệu"
        precipitation = weather["precipitation_mm"]
        precipitation_text = f"{precipitation:.1f} mm" if precipitation is not None else "không có dữ liệu"
        weather_time = weather["observation_time"] or "không rõ giờ"
        code_text = str(weather["weather_code"]) if weather["weather_code"] is not None else "không có"
        solar = weather["shortwave_radiation_w_m2"]
        solar_text = f"{solar:.0f} W/m²" if solar is not None else "không có dữ liệu"
        holiday_text = calendar["holiday_name"] or "không phải ngày lễ"
        print(
            f"Thời tiết {WEATHER_LOCATION_NAME} lúc {weather_time}: {weather['condition']} "
            f"(mức mưa {weather['rain_level']}) | nhiệt độ {temperature_text} | "
            f"mưa giờ trước {rain_text} | tổng giáng thủy giờ trước {precipitation_text} | "
            f"WMO {code_text} | bức xạ mặt trời giờ trước {solar_text} | "
            f"hệ số số đơn {weather['order_factor']:.2f} | "
            f"xác suất thêm 1 ly nước: {weather['drink_probability']:.0%}"
        )
        print(
            f"Lịch: {calendar['day_type']} | "
            f"{'cuối tuần' if calendar['is_weekend'] else 'ngày thường'} | {holiday_text}"
        )
        if weather.get("warning"):
            print(f"Cảnh báo thời tiết: {weather['warning']}")
        print(f"Simulation run: {run_key} | seed: {seed}")
        print(
            "Kết quả: "
            f"{stats['orders']} đơn / {stats['sale_items']} dòng hàng, "
            f"{stats['customers']} khách mới, {stats['production_batches']} mẻ sản xuất, "
            f"{stats['purchase_orders']} PO mới / {stats['receipts']} phiếu nhận, "
            f"{stats['waste']} dòng hủy hết hạn, {stats['returns']} lượt trả hàng, "
            f"{stats['stock_movements']} biến động kho."
        )
        if not is_open:
            print("Không tạo đơn bán hoặc mẻ sản xuất ngoài khung 07:00–22:00 giờ địa phương.")
        return 0
    finally:
        conn.close()


def parse_args():
    parser = argparse.ArgumentParser(description="Giả lập một lượt vận hành tiệm bánh tại thời điểm chạy.")
    parser.add_argument(
        "--dsn", help="PostgreSQL DSN tùy chọn; ưu tiên hơn DATABASE_URL trong .env."
    )
    parser.add_argument("--branch", default="MAIN", help="Mã chi nhánh (mặc định: MAIN).")
    parser.add_argument(
        "--max-orders", type=int, default=3,
        help="Mức đơn nền tối đa ngày thường; cuối tuần/ngày lễ có thể cao hơn (mặc định: 3).",
    )
    parser.add_argument("--seed", type=int, help="Seed để tái lập lựa chọn ngẫu nhiên; thời điểm vẫn lấy từ database.")
    return parser.parse_args()


if __name__ == "__main__":
    try:
        raise SystemExit(simulate(parse_args()))
    except Exception as error:
        print(f"Lỗi mô phỏng: {error}", file=sys.stderr)
        raise SystemExit(1)
