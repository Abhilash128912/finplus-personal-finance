"""
FinPlus+ Personal Finance & Accounting Engine: Dual Database Manager (Postgres / SQLite)
App #5 Storage Core
Seamlessly handles Supabase / Render PostgreSQL and local SQLite.
"""

import os
import sqlite3
from typing import List, Dict, Any, Optional, Union
from pathlib import Path
from config.settings import DB_PATH, DATABASE_URL
from src.utils.time_and_logger import setup_logger, get_utc_iso

logger = setup_logger("FinanceDatabase")

IS_POSTGRES = bool(DATABASE_URL and (DATABASE_URL.startswith("postgres://") or DATABASE_URL.startswith("postgresql://")))

if IS_POSTGRES:
    import psycopg2
    from psycopg2.extras import RealDictCursor
    logger.info("Database Mode: CLOUD POSTGRESQL (Supabase / Render)")
else:
    logger.info("Database Mode: LOCAL SQLITE")

def get_raw_connection():
    """Returns the raw DB connection."""
    if IS_POSTGRES:
        pg_url = DATABASE_URL
        if pg_url.startswith("postgres://"):
            pg_url = pg_url.replace("postgres://", "postgresql://", 1)
        conn = psycopg2.connect(pg_url, cursor_factory=RealDictCursor)
        conn.autocommit = False
        return conn
    else:
        conn = sqlite3.connect(str(DB_PATH), timeout=10.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

class RowWrapper:
    """Enables both dict row['col'] and index row[0] lookups uniformly."""
    def __init__(self, row_dict: dict):
        self._dict = dict(row_dict)
        self._values = list(row_dict.values())

    def __getitem__(self, key):
        if isinstance(key, int):
            return self._values[key]
        return self._dict[key]

    def __iter__(self):
        return iter(self._values)

    def get(self, key, default=None):
        return self._dict.get(key, default)

    def keys(self):
        return self._dict.keys()

    def values(self):
        return self._values

    def items(self):
        return self._dict.items()

class DBProxy:
    """
    Wrapper providing a uniform query interface supporting both
    '?' parameter syntax (SQLite / translated to '%s' for Postgres)
    and dict-like row indexing.
    """
    def __init__(self, conn):
        self.conn = conn
        self.is_pg = IS_POSTGRES
        self._cursor = None

    def cursor(self):
        """Allows calling `conn.cursor()` while returning self."""
        return self

    def _get_cursor(self):
        if self._cursor is None:
            self._cursor = self.conn.cursor()
        return self._cursor

    def execute(self, query: str, params: Union[tuple, list] = ()):
        cur = self._get_cursor()
        if self.is_pg:
            query_pg = query.replace("?", "%s")
            return cur.execute(query_pg, params)
        else:
            return cur.execute(query, params)

    def executemany(self, query: str, seq_of_params):
        cur = self._get_cursor()
        if self.is_pg:
            query_pg = query.replace("?", "%s")
            return cur.executemany(query_pg, seq_of_params)
        else:
            return cur.executemany(query, seq_of_params)

    def fetchone(self):
        cur = self._get_cursor()
        row = cur.fetchone()
        if row is None:
            return None
        if self.is_pg:
            return RowWrapper(row)
        return row

    def fetchall(self):
        cur = self._get_cursor()
        rows = cur.fetchall()
        if self.is_pg:
            return [RowWrapper(r) for r in rows]
        return rows

    def commit(self):
        self.conn.commit()

    def rollback(self):
        self.conn.rollback()

    def close(self):
        if self._cursor:
            try:
                self._cursor.close()
            except Exception:
                pass
        try:
            self.conn.close()
        except Exception:
            pass

def get_connection():
    """Returns a DBProxy wrapping database connection with uniform cursor & '?' param support."""
    return DBProxy(get_raw_connection())

def get_db():
    return get_connection()

def init_database():
    """Initializes schema and seeds standard Chart of Accounts if empty."""
    db = get_db()

    # 1. Accounts Table (Chart of Accounts)
    if IS_POSTGRES:
        db.execute("""
        CREATE TABLE IF NOT EXISTS accounts (
            code VARCHAR(20) PRIMARY KEY,
            name VARCHAR(150) NOT NULL,
            type VARCHAR(50) NOT NULL,
            sub_type VARCHAR(100) NOT NULL,
            balance DOUBLE PRECISION NOT NULL DEFAULT 0.0,
            description TEXT DEFAULT ''
        );
        """)
        db.execute("""
        CREATE TABLE IF NOT EXISTS journal_vouchers (
            voucher_id SERIAL PRIMARY KEY,
            voucher_no VARCHAR(100) UNIQUE NOT NULL,
            voucher_date VARCHAR(50) NOT NULL,
            narration TEXT NOT NULL,
            source VARCHAR(50) DEFAULT 'MANUAL',
            created_at VARCHAR(50) NOT NULL
        );
        """)
        db.execute("""
        CREATE TABLE IF NOT EXISTS journal_entries (
            entry_id SERIAL PRIMARY KEY,
            voucher_id INTEGER NOT NULL REFERENCES journal_vouchers(voucher_id) ON DELETE CASCADE,
            account_code VARCHAR(20) NOT NULL REFERENCES accounts(code),
            debit DOUBLE PRECISION NOT NULL DEFAULT 0.0,
            credit DOUBLE PRECISION NOT NULL DEFAULT 0.0
        );
        """)
        db.execute("""
        CREATE TABLE IF NOT EXISTS mutual_funds (
            id SERIAL PRIMARY KEY,
            scheme_code VARCHAR(50) UNIQUE NOT NULL,
            scheme_name VARCHAR(255) NOT NULL,
            category VARCHAR(100) NOT NULL,
            units DOUBLE PRECISION NOT NULL,
            avg_buy_nav DOUBLE PRECISION NOT NULL,
            latest_nav DOUBLE PRECISION NOT NULL,
            nav_date VARCHAR(50) NOT NULL,
            sip_day INTEGER DEFAULT 10,
            last_updated VARCHAR(50) NOT NULL
        );
        """)
        db.execute("""
        CREATE TABLE IF NOT EXISTS gold_holdings (
            id SERIAL PRIMARY KEY,
            asset_name VARCHAR(150) NOT NULL,
            grams DOUBLE PRECISION NOT NULL,
            purity VARCHAR(20) DEFAULT '22K',
            market_rate_per_gram DOUBLE PRECISION NOT NULL,
            haircut_pct DOUBLE PRECISION NOT NULL DEFAULT 23.0,
            last_updated VARCHAR(50) NOT NULL
        );
        """)
        db.execute("""
        CREATE TABLE IF NOT EXISTS loans (
            id SERIAL PRIMARY KEY,
            loan_name VARCHAR(150) NOT NULL,
            account_code VARCHAR(20) NOT NULL,
            principal DOUBLE PRECISION NOT NULL,
            start_date VARCHAR(50) NOT NULL,
            annual_rate_pct DOUBLE PRECISION NOT NULL,
            mode VARCHAR(20) DEFAULT 'AUTO',
            manual_realized_interest DOUBLE PRECISION DEFAULT 0.0,
            monthly_emi DOUBLE PRECISION DEFAULT 0.0
        );
        """)
        db.execute("""
        CREATE TABLE IF NOT EXISTS daily_alerts (
            id SERIAL PRIMARY KEY,
            title VARCHAR(200) NOT NULL,
            message TEXT NOT NULL,
            category VARCHAR(50) NOT NULL,
            dispatched_at VARCHAR(50) NOT NULL
        );
        """)
    else:
        # SQLite
        db.execute("""
        CREATE TABLE IF NOT EXISTS accounts (
            code TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            type TEXT NOT NULL,
            sub_type TEXT NOT NULL,
            balance REAL NOT NULL DEFAULT 0.0,
            description TEXT DEFAULT ''
        );
        """)
        db.execute("""
        CREATE TABLE IF NOT EXISTS journal_vouchers (
            voucher_id INTEGER PRIMARY KEY AUTOINCREMENT,
            voucher_no TEXT UNIQUE NOT NULL,
            voucher_date TEXT NOT NULL,
            narration TEXT NOT NULL,
            source TEXT DEFAULT 'MANUAL',
            created_at TEXT NOT NULL
        );
        """)
        db.execute("""
        CREATE TABLE IF NOT EXISTS journal_entries (
            entry_id INTEGER PRIMARY KEY AUTOINCREMENT,
            voucher_id INTEGER NOT NULL,
            account_code TEXT NOT NULL,
            debit REAL NOT NULL DEFAULT 0.0,
            credit REAL NOT NULL DEFAULT 0.0,
            FOREIGN KEY (voucher_id) REFERENCES journal_vouchers(voucher_id) ON DELETE CASCADE,
            FOREIGN KEY (account_code) REFERENCES accounts(code)
        );
        """)
        db.execute("""
        CREATE TABLE IF NOT EXISTS mutual_funds (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scheme_code TEXT UNIQUE NOT NULL,
            scheme_name TEXT NOT NULL,
            category TEXT NOT NULL,
            units REAL NOT NULL,
            avg_buy_nav REAL NOT NULL,
            latest_nav REAL NOT NULL,
            nav_date TEXT NOT NULL,
            sip_day INTEGER DEFAULT 10,
            last_updated TEXT NOT NULL
        );
        """)
        db.execute("""
        CREATE TABLE IF NOT EXISTS gold_holdings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            asset_name TEXT NOT NULL,
            grams REAL NOT NULL,
            purity TEXT DEFAULT '22K',
            market_rate_per_gram REAL NOT NULL,
            haircut_pct REAL NOT NULL DEFAULT 23.0,
            last_updated TEXT NOT NULL
        );
        """)
        db.execute("""
        CREATE TABLE IF NOT EXISTS loans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            loan_name TEXT NOT NULL,
            account_code TEXT NOT NULL,
            principal REAL NOT NULL,
            start_date TEXT NOT NULL,
            annual_rate_pct REAL NOT NULL,
            mode TEXT DEFAULT 'AUTO',
            manual_realized_interest REAL DEFAULT 0.0,
            monthly_emi REAL DEFAULT 0.0
        );
        """)
        db.execute("""
        CREATE TABLE IF NOT EXISTS daily_alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            message TEXT NOT NULL,
            category TEXT NOT NULL,
            dispatched_at TEXT NOT NULL
        );
        """)

    db.commit()

    # Seed initial Chart of Accounts if empty
    db.execute("SELECT COUNT(*) FROM accounts;")
    count_row = db.fetchone()
    count = count_row[0] if count_row else 0
    if count == 0:
        logger.info("Seeding initial Standard Chart of Accounts (Ind AS / GAAP) with zero balances...")
        initial_accounts = [
            # ASSETS (1000)
            ('1110', 'Bank Savings Account', 'ASSET', 'Current Asset', 0.0, 'Primary liquid bank account'),
            ('1120', 'Cash / Emergency Liquidity', 'ASSET', 'Current Asset', 0.0, 'Emergency cash liquidity'),
            ('1140', 'Trading Margin (Journal Bridge)', 'ASSET', 'Current Asset', 0.0, 'Capital in trading journal'),
            ('1210', 'Mutual Funds Portfolio (Live AMFI)', 'ASSET', 'Investments', 0.0, 'Equity SIPs and lumpsums'),
            ('1230', 'Physical 22K Gold (Goodreturns - 23%)', 'ASSET', 'Investments', 0.0, '22K physical gold holding minus 23% pledge haircut'),
            ('1310', 'Real Estate / Fixed Property', 'ASSET', 'Fixed Asset', 0.0, 'Real estate property equity'),
            ('1410', 'Provident Fund (EPF + PPF)', 'ASSET', 'Retirement', 0.0, 'Retirement corpus'),

            # LIABILITIES (2000)
            ('2110', 'Credit Card Current Dues', 'LIABILITY', 'Current Liability', 0.0, 'Revolving credit card dues'),
            ('2120', 'Accrued Unpaid Interest', 'LIABILITY', 'Current Liability', 0.0, 'Accrued interest liability'),
            ('2210', 'Home Loan Mortgage', 'LIABILITY', 'Long-Term Debt', 0.0, 'Secured home loan principal + accrued'),
            ('2230', 'Personal Loan / EMI Balance', 'LIABILITY', 'Short-Term Debt', 0.0, 'Personal loan / consumer EMI balance'),

            # EQUITY (3000)
            ('3100', "Owner's Capital (Opening Net Worth)", 'EQUITY', 'Capital', 0.0, 'Opening net wealth balance'),
            ('3200', 'Current Period Retained Surplus', 'EQUITY', 'Reserves', 0.0, 'P&L savings surplus transferred to equity'),

            # REVENUES / INCOME (4000)
            ('4110', 'Professional Salary Income', 'INCOME', 'Direct Income', 0.0, 'Monthly salary inflow'),
            ('4210', 'Realized Trading Gains (Other Income)', 'INCOME', 'Other Income', 0.0, 'Auto-synced from Journal Port 8003 REAL trades'),
            ('4220', 'Dividends & Interest Income', 'INCOME', 'Other Income', 0.0, 'Passive dividends and interest receipts'),

            # EXPENSES (5000)
            ('5110', 'Rent & Maintenance Expense', 'EXPENSE', 'Living Needs', 0.0, 'Home rent and society charges'),
            ('5120', 'Groceries & Provisions Expense', 'EXPENSE', 'Living Needs', 0.0, 'Food, kitchen and supermarket'),
            ('5210', 'Loan Interest Paid / Accrued', 'EXPENSE', 'Finance Cost', 0.0, 'Loan interest charge'),
            ('5310', 'Subscriptions & Software', 'EXPENSE', 'Subscriptions', 0.0, 'Monthly recurring software/OTT plans'),
            ('5410', 'Discretionary Outflows', 'EXPENSE', 'Discretionary', 0.0, 'Dining out and leisure expenses')
        ]
        db.executemany("INSERT INTO accounts (code, name, type, sub_type, balance, description) VALUES (?, ?, ?, ?, ?, ?);", initial_accounts)

        # Seed Gold Holding with 0 grams
        db.execute("""
        INSERT INTO gold_holdings (asset_name, grams, purity, market_rate_per_gram, haircut_pct, last_updated)
        VALUES ('22 Karat Gold Jewellery & Sovereign Bars', 0.0, '22K', 13256.0, 23.0, ?);
        """, (get_utc_iso(),))

        db.commit()
        logger.info("Database initialized with pristine Chart of Accounts.")

    db.close()
