"""
FinPlus+ Two-Way Loan & Liability Accounting Engine
App #5
Supports:
Option A: Auto-Accrue from start date & annual rate (%)
Option B: Manual Realized Interest
Updates account 2210 in SQLite.
"""

from datetime import datetime
from typing import Dict, Any, List
from src.db.database import get_connection
from src.utils.time_and_logger import setup_logger, get_ist_now

logger = setup_logger("LoanEngine")

class LoanEngine:
    @staticmethod
    def get_loans() -> List[Dict[str, Any]]:
        """Returns all loans with active accrued or manual liabilities."""
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id, loan_name, account_code, principal, start_date, annual_rate_pct, mode, manual_realized_interest, monthly_emi FROM loans;")
        rows = cursor.fetchall()
        conn.close()

        results = []
        today = datetime.now()

        for r in rows:
            p = float(r["principal"])
            rate = float(r["annual_rate_pct"])
            mode = r["mode"]
            start_str = r["start_date"]

            accrued = 0.0
            days = 0
            years = 0.0

            if mode == "AUTO":
                try:
                    s_date = datetime.strptime(start_str, "%Y-%m-%d")
                    days = max(1, (today - s_date).days)
                    years = round(days / 365.25, 2)
                    accrued = round(p * (rate / 100.0) * (days / 365.25), 2)
                except Exception:
                    accrued = 0.0
            else:
                accrued = float(r["manual_realized_interest"])

            total_liability = round(p + accrued, 2)

            results.append({
                "id": r["id"],
                "loan_name": r["loan_name"],
                "account_code": r["account_code"],
                "principal": p,
                "start_date": start_str,
                "annual_rate_pct": rate,
                "mode": mode,
                "accrued_days": days,
                "accrued_years": years,
                "accrued_interest": accrued,
                "total_liability": total_liability,
                "monthly_emi": float(r["monthly_emi"])
            })

        return results

    @staticmethod
    def update_loan(loan_id: int, principal: float, start_date: str, rate: float, mode: str, manual_interest: float = 0.0):
        """Updates a loan and reconciles account 2210 on the Balance Sheet."""
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
        UPDATE loans
        SET principal = ?, start_date = ?, annual_rate_pct = ?, mode = ?, manual_realized_interest = ?
        WHERE id = ?;
        """, (principal, start_date, rate, mode, manual_interest, loan_id))

        # Compute total
        today = datetime.now()
        accrued = 0.0
        if mode == "AUTO":
            s_date = datetime.strptime(start_date, "%Y-%m-%d")
            days = max(1, (today - s_date).days)
            accrued = principal * (rate / 100.0) * (days / 365.25)
        else:
            accrued = manual_interest

        total_liability = round(principal + accrued, 2)
        cursor.execute("UPDATE accounts SET balance = ? WHERE code = '2210';", (total_liability,))
        conn.commit()
        conn.close()

        logger.info(f"Loan #{loan_id} updated: Principal ₹{principal}, Liability ₹{total_liability}.")

