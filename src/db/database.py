"""
FinPlus+ Personal Finance & Accounting Engine: SQLite Database Manager
App #5 Storage Core
"""

import sqlite3
from typing import List, Dict, Any, Optional
from pathlib import Path
from config.settings import DB_PATH
from src.utils.time_and_logger import setup_logger, get_utc_iso

logger = setup_logger("FinanceDatabase")

def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH), timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn

def init_database():
    """Initializes schema and seeds standard Chart of Accounts if empty."""
    conn = get_connection()
    cursor = conn.cursor()

    # 1. Accounts Table (Chart of Accounts)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS accounts (
        code TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        type TEXT NOT NULL,      -- ASSET, LIABILITY, EQUITY, INCOME, EXPENSE
        sub_type TEXT NOT NULL,  -- Current Asset, Investment, Long-Term Debt, etc.
        balance REAL NOT NULL DEFAULT 0.0,
        description TEXT DEFAULT ''
    );
    """)

    # 2. Journal Vouchers (Double-entry transaction headers)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS journal_vouchers (
        voucher_id INTEGER PRIMARY KEY AUTOINCREMENT,
        voucher_no TEXT UNIQUE NOT NULL,
        voucher_date TEXT NOT NULL,
        narration TEXT NOT NULL,
        source TEXT DEFAULT 'MANUAL',  -- MANUAL, JOURNAL_SYNC, ACCRUAL, SIP_AUTO
        created_at TEXT NOT NULL
    );
    """)

    # 3. Journal Entries (Individual Dr / Cr lines)
    cursor.execute("""
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

    # 4. Mutual Fund Portfolio
    cursor.execute("""
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

    # 5. Physical Gold Holding
    cursor.execute("""
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

    # 6. Loans & Liabilities
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS loans (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        loan_name TEXT NOT NULL,
        account_code TEXT NOT NULL,
        principal REAL NOT NULL,
        start_date TEXT NOT NULL,
        annual_rate_pct REAL NOT NULL,
        mode TEXT DEFAULT 'AUTO', -- AUTO or MANUAL
        manual_realized_interest REAL DEFAULT 0.0,
        monthly_emi REAL DEFAULT 0.0
    );
    """)

    # 7. Dispatched Alerts Log
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS daily_alerts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        message TEXT NOT NULL,
        category TEXT NOT NULL,
        dispatched_at TEXT NOT NULL
    );
    """)

    conn.commit()

    # Seed initial Chart of Accounts if empty
    cursor.execute("SELECT COUNT(*) FROM accounts;")
    count = cursor.fetchone()[0]
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
        cursor.executemany("INSERT INTO accounts (code, name, type, sub_type, balance, description) VALUES (?, ?, ?, ?, ?, ?);", initial_accounts)

        # Seed Gold Holding with 0 grams
        cursor.execute("""
        INSERT INTO gold_holdings (asset_name, grams, purity, market_rate_per_gram, haircut_pct, last_updated)
        VALUES ('22 Karat Gold Jewellery & Sovereign Bars', 0.0, '22K', 13256.0, 23.0, ?);
        """, (get_utc_iso(),))

        conn.commit()
        logger.info("Database initialized with pristine Chart of Accounts.")

    conn.close()

