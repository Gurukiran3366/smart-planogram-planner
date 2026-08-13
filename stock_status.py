# stock_status.py
"""
Manages daily out-of-stock (OOS) product status.
Allows staff to mark products as OOS before audit,
so the system doesn't tell them to 'add missing' products they don't have.
"""

import json
from pathlib import Path
from datetime import datetime, date

STOCK_STATUS_FILE = Path("data/stock_status.json")


def load_today_oos():
    """Load today's out-of-stock list. Returns set of product_ids."""
    if not STOCK_STATUS_FILE.exists():
        return set()
    
    try:
        with open(STOCK_STATUS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        today = str(date.today())
        today_data = data.get(today, {})
        return set(today_data.get("out_of_stock", []))
    except Exception:
        return set()


def save_today_oos(oos_product_ids):
    """Save today's out-of-stock list."""
    STOCK_STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
    
    if STOCK_STATUS_FILE.exists():
        with open(STOCK_STATUS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    else:
        data = {}
    
    today = str(date.today())
    data[today] = {
        "out_of_stock": list(oos_product_ids),
        "updated_at": datetime.now().isoformat()
    }
    
    # Keep only last 30 days of history
    all_dates = sorted(data.keys(), reverse=True)[:30]
    data = {d: data[d] for d in all_dates}
    
    with open(STOCK_STATUS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def get_today_oos_count():
    """Return count of items marked OOS today."""
    return len(load_today_oos())


def clear_today_oos():
    """Clear today's OOS list (useful for testing)."""
    save_today_oos(set())