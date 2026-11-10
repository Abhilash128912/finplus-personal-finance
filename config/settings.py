"""
FinPlus+ Personal Finance & Double-Entry Accounting Engine
App #5 Settings & Configuration
Port: 8004
"""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "personal_finance.db"
BACKUPS_DIR = BASE_DIR / "backups"

APP_NAME = "FinPlus+ Wealth & Double-Entry Accounting Engine"
APP_CODE = "APP_05_PERSONAL_FINANCE"
SERVER_PORT = int(os.getenv("PORT", 8004))
SERVER_HOST = "127.0.0.1"

# Trading Journal (App #4) SQLite path for local real-trade bridge
JOURNAL_DB_PATH = Path(r"D:\AI_APPS\finplus_trading_journal\data\journal.db")

# NTFY configuration
NTFY_TOPIC = os.getenv("FINPLUS_NTFY_TOPIC", "finplus_wealth_alerts_2026")
NTFY_SERVER = "https://ntfy.sh"
