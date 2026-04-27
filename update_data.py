"""
Update FinMind data by category, using the latest date already stored in the DB.

Categories:
  stock     TaiwanStockPrice
  stock_adj TaiwanStockPriceAdj
  cb_daily  TaiwanStockConvertibleBondDaily
  cb_basic  TaiwanStockConvertibleBondDailyOverview
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DBDOWNLOADER_DIR = ROOT.parent / "dbdownloader"

if not DBDOWNLOADER_DIR.exists():
    raise SystemExit(f"Cannot find dbdownloader folder: {DBDOWNLOADER_DIR}")

sys.path.insert(0, str(DBDOWNLOADER_DIR))

from config import FINMIND_TOKEN  # noqa: E402
from db import get_conn, init_tables, set_last_date  # noqa: E402
from downloader import (  # noqa: E402
    download_convertible_bond,
    download_convertible_bond_daily,
    download_stock_info,
    download_stock_price,
    download_stock_price_adj,
    get_all_stock_ids,
)


CATEGORIES = {
    "stock": {
        "title": "個股",
        "dataset": "TaiwanStockPrice",
        "table": "taiwan_stock_price",
        "id_col": "stock_id",
        "runner": download_stock_price,
    },
    "stock_adj": {
        "title": "個股還原",
        "dataset": "TaiwanStockPriceAdj",
        "table": "taiwan_stock_price_adj",
        "id_col": "stock_id",
        "runner": download_stock_price_adj,
    },
    "cb_daily": {
        "title": "CB 股價",
        "dataset": "TaiwanStockConvertibleBondDaily",
        "table": "taiwan_stock_convertible_bond_daily",
        "id_col": None,
        "runner": download_convertible_bond_daily,
    },
    "cb_basic": {
        "title": "CB 資料庫",
        "dataset": "TaiwanStockConvertibleBondDailyOverview",
        "table": "taiwan_stock_convertible_bond",
        "id_col": None,
        "runner": download_convertible_bond,
    },
}


def check_token() -> None:
    if not FINMIND_TOKEN or FINMIND_TOKEN == "your_token_here":
        raise SystemExit("請先在 dbdownloader\\.env 設定 FINMIND_TOKEN")


def table_exists(table: str) -> bool:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone()
    return row is not None


def sync_progress_from_table(category: dict) -> str | None:
    dataset = category["dataset"]
    table = category["table"]
    id_col = category["id_col"]

    if not table_exists(table):
        return None

    with get_conn() as conn:
        if id_col:
            rows = conn.execute(
                f"SELECT {id_col}, MAX(date) FROM {table} GROUP BY {id_col}"
            ).fetchall()
            for data_id, last_date in rows:
                if data_id and last_date:
                    set_last_date(dataset, str(data_id), str(last_date))

            latest = conn.execute(f"SELECT MAX(date) FROM {table}").fetchone()[0]
            return latest

        latest = conn.execute(f"SELECT MAX(date) FROM {table}").fetchone()[0]
        if latest:
            set_last_date(dataset, "__daily__", str(latest))
        return latest


def ensure_stock_ids() -> list[str]:
    ids = get_all_stock_ids()
    if ids:
        return ids

    print("[個股清單] 資料庫沒有股票清單，先更新 TaiwanStockInfo...")
    download_stock_info()
    return get_all_stock_ids()


def update_category(key: str) -> None:
    category = CATEGORIES[key]
    title = category["title"]

    print()
    print(f"=== {title}：校準資料庫最新日期 ===")
    latest = sync_progress_from_table(category)
    print(f"[{title}] DB 最新日期：{latest or '無資料，將從預設起始日下載'}")

    print(f"=== {title}：開始補資料至今天 ===")
    if category["id_col"]:
        ids = ensure_stock_ids()
        category["runner"](ids)
    else:
        category["runner"]()
    print(f"=== {title}：完成 ===")


def print_status() -> None:
    print()
    print("=== 目前資料庫日期 ===")
    with get_conn() as conn:
        for key, category in CATEGORIES.items():
            table = category["table"]
            title = category["title"]
            if not table_exists(table):
                print(f"{key:10s} {title:8s} 無資料表")
                continue

            row = conn.execute(
                f"SELECT MIN(date), MAX(date), COUNT(*) FROM {table}"
            ).fetchone()
            print(
                f"{key:10s} {title:8s} "
                f"{row[0] or '-'} ~ {row[1] or '-'}，{row[2]:,} 筆"
            )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Update FinMind data by category.")
    parser.add_argument(
        "category",
        nargs="?",
        default="all",
        choices=["all", "status", *CATEGORIES.keys()],
        help="資料分類：stock, stock_adj, cb_daily, cb_basic, all, status",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    check_token()
    init_tables()

    if args.category == "status":
        print_status()
        return

    if args.category == "all":
        for key in ["stock", "stock_adj", "cb_daily", "cb_basic"]:
            update_category(key)
    else:
        update_category(args.category)

    print_status()


if __name__ == "__main__":
    main()
