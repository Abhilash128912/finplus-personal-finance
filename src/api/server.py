"""
FinPlus+ Wealth & Double-Entry Accounting Engine - FastAPI Server
App #5
Port: 8004
"""

import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from contextlib import asynccontextmanager
import asyncio
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
from typing import Dict, Any, List, Optional

from config.settings import APP_NAME, APP_CODE, SERVER_PORT, NTFY_TOPIC
from src.db.database import init_database
from src.accounting.double_entry_engine import DoubleEntryEngine
from src.integrations.journal_bridge import JournalBridge
from src.integrations.mf_tracker import MutualFundsTracker
from src.integrations.gold_engine import GoldEngine
from src.integrations.loan_engine import LoanEngine
from src.notifications.finance_ntfy import FinanceNTFYDispatcher
from src.utils.time_and_logger import setup_logger, get_utc_iso, get_ist_now, get_ist_time_str

logger = setup_logger("App05Server")

# Pydantic Input Schemas
class VoucherEntryInput(BaseModel):
    account_code: str
    debit: float = 0.0
    credit: float = 0.0

class VoucherInput(BaseModel):
    voucher_date: str
    narration: str
    entries: List[VoucherEntryInput]
    source: Optional[str] = "MANUAL"

class MutualFundInput(BaseModel):
    scheme_code: str
    scheme_name: str
    category: str = "Flexi Cap"
    units: float
    avg_buy_nav: float
    sip_day: int = 10

class GoldUpdateInput(BaseModel):
    grams: float
    market_rate_per_gram: float

class LoanUpdateInput(BaseModel):
    principal: float
    start_date: str
    annual_rate_pct: float
    mode: str = "AUTO"
    manual_realized_interest: float = 0.0

class AccountInput(BaseModel):
    code: str
    name: str
    type: str
    sub_type: str
    opening_balance: float = 0.0
    description: Optional[str] = ""

class AccountUpdateInput(BaseModel):
    name: str
    sub_type: str
    description: Optional[str] = ""

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(f"Starting {APP_NAME} ({APP_CODE}) on port {SERVER_PORT}...")
    init_database()
    # Trigger initial sync from App #4 journal.db (REAL trades only)
    try:
        JournalBridge.sync_real_trading_results()
    except Exception as e:
        logger.warning(f"Could not auto-sync trading journal: {e}")
    yield
    logger.info(f"Shutting down {APP_NAME}...")

app = FastAPI(title=APP_NAME, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

FRONTEND_DIR = BASE_DIR / "frontend"
FRONTEND_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")

@app.api_route("/", methods=["GET", "HEAD"])
def serve_dashboard():
    index_path = FRONTEND_DIR / "index.html"
    if index_path.exists():
        return FileResponse(index_path)
    return JSONResponse({"status": "ready", "message": "App #5 frontend initializing..."})

@app.api_route("/health", methods=["GET", "HEAD"])
def health_check():
    return {"status": "ok", "app": APP_NAME, "app_code": APP_CODE, "port": SERVER_PORT}

@app.get("/api/status")
def get_system_status():
    tb = DoubleEntryEngine.get_trial_balance()
    bs = DoubleEntryEngine.get_balance_sheet()
    pnl = DoubleEntryEngine.get_income_statement()
    return {
        "app_name": APP_NAME,
        "app_code": APP_CODE,
        "port": SERVER_PORT,
        "trial_balance_balanced": tb["is_balanced"],
        "net_worth": bs["net_worth"],
        "total_assets": bs["assets"]["total_assets"],
        "total_liabilities": bs["liabilities"]["total_liabilities"],
        "net_surplus": pnl["net_surplus"],
        "savings_rate_pct": pnl["savings_rate_pct"],
        "utc_time": get_utc_iso(),
        "ist_time": get_ist_time_str()
    }

# ==================== ACCOUNTING ROUTES ====================

@app.get("/api/accounts")
def get_all_accounts():
    """Returns complete Chart of Accounts ordered by standard numeric codes."""
    from src.db.database import get_connection
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT code, name, type, sub_type, balance, description FROM accounts ORDER BY code ASC;")
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

@app.post("/api/accounts")
def create_account(acc: AccountInput):
    """Creates a new customized account in the Chart of Accounts."""
    from src.db.database import get_connection
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT code FROM accounts WHERE code = ?;", (acc.code,))
        if cursor.fetchone():
            raise HTTPException(status_code=400, detail=f"Account code {acc.code} already exists.")
        
        acc_type = acc.type.upper()
        if acc_type in ("REVENUE", "INCOME"):
            acc_type = "INCOME"

        cursor.execute("""
        INSERT INTO accounts (code, name, type, sub_type, balance, description)
        VALUES (?, ?, ?, ?, ?, ?);
        """, (acc.code, acc.name, acc_type, acc.sub_type, acc.opening_balance, acc.description or ''))
        conn.commit()
        return {"status": "SUCCESS", "code": acc.code, "name": acc.name}
    finally:
        conn.close()

@app.put("/api/accounts/{code}")
def update_account(code: str, acc: AccountUpdateInput):
    """Updates an existing account's name, sub_type, or description."""
    from src.db.database import get_connection
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
        UPDATE accounts
        SET name = ?, sub_type = ?, description = ?
        WHERE code = ?;
        """, (acc.name, acc.sub_type, acc.description or '', code))
        conn.commit()
        return {"status": "SUCCESS", "code": code, "name": acc.name}
    finally:
        conn.close()

@app.delete("/api/accounts/{code}")
def delete_account(code: str):
    """Deletes an account if no journal vouchers are referencing it."""
    from src.db.database import get_connection
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT COUNT(*) FROM journal_entries WHERE account_code = ?;", (code,))
        count = cursor.fetchone()[0]
        if count > 0:
            raise HTTPException(status_code=400, detail=f"Cannot delete account {code} because it has {count} active journal entries. Set balance to 0 instead.")
        
        cursor.execute("DELETE FROM accounts WHERE code = ?;", (code,))
        conn.commit()
        return {"status": "DELETED", "code": code}
    finally:
        conn.close()

@app.get("/api/balance-sheet")
def get_balance_sheet():
    """Returns classified Balance Sheet (Assets = Liabilities + Equity)."""
    return DoubleEntryEngine.get_balance_sheet()

@app.get("/api/income-statement")
def get_income_statement():
    """Returns Income & Expense Statement (P&L) with net period savings."""
    return DoubleEntryEngine.get_income_statement()

@app.get("/api/trial-balance")
def get_trial_balance():
    """Returns Trial Balance proving debit-credit equality."""
    return DoubleEntryEngine.get_trial_balance()

@app.get("/api/journal")
def get_journal(limit: int = 100):
    """Returns chronological General Journal audit vouchers."""
    return DoubleEntryEngine.get_journal(limit=limit)

@app.post("/api/journal/vouchers")
def post_voucher(voucher: VoucherInput):
    """Posts a new balanced double-entry journal voucher."""
    try:
        entries_dict = [e.dict() for e in voucher.entries]
        result = DoubleEntryEngine.post_voucher(
            voucher_date=voucher.voucher_date,
            narration=voucher.narration,
            entries=entries_dict,
            source=voucher.source or "MANUAL"
        )
        return result
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        logger.error(f"Error posting voucher: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/ledger/{account_code}")
def get_ledger(account_code: str):
    """Returns T-Account transaction history and running balance for any account."""
    try:
        return DoubleEntryEngine.get_ledger(account_code)
    except ValueError as ve:
        raise HTTPException(status_code=404, detail=str(ve))

# ==================== MUTUAL FUNDS ROUTES ====================

@app.get("/api/mutual-funds")
def get_mutual_funds():
    """Returns Mutual Fund portfolio, invested amount, and live AMFI NAVs."""
    return MutualFundsTracker.get_portfolio()

@app.post("/api/mutual-funds")
def add_mutual_fund(fund: MutualFundInput):
    """Adds a new mutual fund scheme with live AMFI sync."""
    return MutualFundsTracker.add_fund(
        scheme_code=fund.scheme_code,
        scheme_name=fund.scheme_name,
        category=fund.category,
        units=fund.units,
        avg_buy_nav=fund.avg_buy_nav,
        sip_day=fund.sip_day
    )

@app.post("/api/mutual-funds/sync")
def sync_mutual_funds():
    """Forces an immediate live NAV refresh across all schemes from AMFI."""
    return MutualFundsTracker.sync_all_amfi_navs()

# ==================== GOLD & LOAN SUB-LEDGERS ====================

@app.get("/api/gold")
def get_gold_valuation():
    """Returns physical 22K gold valuation with 23% pledge haircut."""
    return GoldEngine.get_gold_valuation()

@app.post("/api/gold")
def update_gold(gold: GoldUpdateInput):
    """Updates physical gold holding weight or market rate."""
    return GoldEngine.update_gold_holding(gold.grams, gold.market_rate_per_gram)

@app.get("/api/loans")
def get_loans():
    """Returns two-way loan schedules and accrued liabilities."""
    return LoanEngine.get_loans()

@app.post("/api/loans/{loan_id}")
def update_loan(loan_id: int, loan: LoanUpdateInput):
    """Updates a loan's principal, interest rate, or accounting mode."""
    LoanEngine.update_loan(
        loan_id=loan_id,
        principal=loan.principal,
        start_date=loan.start_date,
        rate=loan.annual_rate_pct,
        mode=loan.mode,
        manual_interest=loan.manual_realized_interest
    )
    return {"status": "SUCCESS", "loan_id": loan_id}

# ==================== TRADING JOURNAL BRIDGE & ALERTS ====================

@app.post("/api/journal-bridge/sync")
def sync_trading_journal():
    """Reconciles actual REAL trades from App #4 journal.db into App #5 accounts 1140 & 4210."""
    return JournalBridge.sync_real_trading_results()

@app.post("/api/alerts/test")
def test_ntfy_alert():
    """Dispatches a test push notification to the user's phone."""
    delivered = FinanceNTFYDispatcher.send_notification(
        title="📈 FinPlus MF Daily Briefing",
        message="Portfolio: ₹18.20L (+0.47% today). Parag Parikh NAV: ₹93.988. Next SIP: Quant Mid Cap ₹5,000 on 15-Nov.",
        category="TEST_ALERT",
        priority="4"
    )
    return {"status": "DELIVERED" if delivered else "FAILED"}

