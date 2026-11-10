"""
FinPlus+ Double-Entry Accounting Core Engine
App #5
Enforces strict mathematical Ind AS / GAAP debit-credit equality and financial statement generation.
"""

from typing import List, Dict, Any, Optional
from src.db.database import get_connection
from src.utils.time_and_logger import setup_logger, get_utc_iso

logger = setup_logger("AccountingEngine")

class DoubleEntryEngine:
    """
    Handles journal vouchers, T-account ledger generation, trial balance verification,
    and classified balance sheet / P&L reporting.
    """

    @staticmethod
    def post_voucher(
        voucher_date: str,
        narration: str,
        entries: List[Dict[str, Any]], # [{'account_code': '1110', 'debit': 1000.0, 'credit': 0.0}, ...]
        source: str = "MANUAL"
    ) -> Dict[str, Any]:
        """
        Validates double-entry balance (Dr == Cr) and writes atomically to SQLite.
        """
        if not entries or len(entries) < 2:
            raise ValueError("A double-entry voucher must contain at least two entries (one debit and one credit).")

        total_debit = round(sum(float(e.get("debit", 0.0)) for e in entries), 2)
        total_credit = round(sum(float(e.get("credit", 0.0)) for e in entries), 2)

        if abs(total_debit - total_credit) > 0.01:
            raise ValueError(f"Double-entry violation! Total Debit (₹{total_debit}) must equal Total Credit (₹{total_credit}).")

        conn = get_connection()
        cursor = conn.cursor()

        try:
            # Generate next voucher number
            cursor.execute("SELECT COUNT(*) FROM journal_vouchers;")
            count = cursor.fetchone()[0]
            voucher_no = f"JV-2026-{String_pad(count + 1)}"

            # Insert voucher header
            cursor.execute("""
            INSERT INTO journal_vouchers (voucher_no, voucher_date, narration, source, created_at)
            VALUES (?, ?, ?, ?, ?);
            """, (voucher_no, voucher_date, narration, source, get_utc_iso()))
            voucher_id = cursor.lastrowid

            # Insert entries and update account balances
            for e in entries:
                acc_code = str(e["account_code"])
                dr = round(float(e.get("debit", 0.0)), 2)
                cr = round(float(e.get("credit", 0.0)), 2)

                cursor.execute("""
                INSERT INTO journal_entries (voucher_id, account_code, debit, credit)
                VALUES (?, ?, ?, ?);
                """, (voucher_id, acc_code, dr, cr))

                # Update account balance based on normal balance rule
                cursor.execute("SELECT type, balance FROM accounts WHERE code = ?;", (acc_code,))
                acc = cursor.fetchone()
                if acc:
                    acc_type = acc["type"]
                    current_bal = acc["balance"]
                    if acc_type in ("ASSET", "EXPENSE"):
                        new_bal = current_bal + dr - cr
                    else: # LIABILITY, EQUITY, INCOME
                        new_bal = current_bal + cr - dr
                    cursor.execute("UPDATE accounts SET balance = ? WHERE code = ?;", (new_bal, acc_code))

            conn.commit()
            logger.info(f"Successfully posted {voucher_no}: ₹{total_debit} balanced.")
            return {
                "status": "SUCCESS",
                "voucher_no": voucher_no,
                "voucher_id": voucher_id,
                "total_amount": total_debit,
                "narration": narration
            }
        except Exception as e:
            conn.rollback()
            logger.error(f"Failed posting voucher: {e}")
            raise e
        finally:
            conn.close()

    @staticmethod
    def get_journal(limit: int = 100) -> List[Dict[str, Any]]:
        """Returns all vouchers with itemized entries."""
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
        SELECT v.voucher_id, v.voucher_no, v.voucher_date, v.narration, v.source, v.created_at,
               e.account_code, a.name AS account_name, a.type AS account_type, e.debit, e.credit
        FROM journal_vouchers v
        JOIN journal_entries e ON v.voucher_id = e.voucher_id
        JOIN accounts a ON e.account_code = a.code
        ORDER BY v.voucher_id DESC, e.entry_id ASC
        LIMIT ?;
        """, (limit * 5,))
        rows = cursor.fetchall()
        conn.close()

        vouchers_map: Dict[str, Dict[str, Any]] = {}
        for r in rows:
            v_no = r["voucher_no"]
            if v_no not in vouchers_map:
                vouchers_map[v_no] = {
                    "voucher_id": r["voucher_id"],
                    "voucher_no": v_no,
                    "voucher_date": r["voucher_date"],
                    "narration": r["narration"],
                    "source": r["source"],
                    "created_at": r["created_at"],
                    "entries": []
                }
            vouchers_map[v_no]["entries"].append({
                "account_code": r["account_code"],
                "account_name": r["account_name"],
                "account_type": r["account_type"],
                "debit": r["debit"],
                "credit": r["credit"]
            })
        return list(vouchers_map.values())[:limit]

    @staticmethod
    def get_ledger(account_code: str) -> Dict[str, Any]:
        """Returns T-Account transaction history and running balance for a given account."""
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT code, name, type, sub_type, balance, description FROM accounts WHERE code = ?;", (account_code,))
        acc = cursor.fetchone()
        if not acc:
            conn.close()
            raise ValueError(f"Account code {account_code} does not exist.")

        cursor.execute("""
        SELECT v.voucher_no, v.voucher_date, v.narration, e.debit, e.credit
        FROM journal_entries e
        JOIN journal_vouchers v ON e.voucher_id = v.voucher_id
        WHERE e.account_code = ?
        ORDER BY v.voucher_date ASC, v.voucher_id ASC;
        """, (account_code,))
        txns = cursor.fetchall()
        conn.close()

        entries = []
        running = 0.0
        acc_type = acc["type"]
        is_dr_normal = acc_type in ("ASSET", "EXPENSE")

        for t in txns:
            dr = t["debit"]
            cr = t["credit"]
            if is_dr_normal:
                running += (dr - cr)
            else:
                running += (cr - dr)
            entries.append({
                "voucher_no": t["voucher_no"],
                "voucher_date": t["voucher_date"],
                "narration": t["narration"],
                "debit": dr,
                "credit": cr,
                "running_balance": round(abs(running), 2)
            })

        return {
            "code": acc["code"],
            "name": acc["name"],
            "type": acc["type"],
            "sub_type": acc["sub_type"],
            "closing_balance": round(abs(acc["balance"]), 2),
            "normal_balance": "Dr" if is_dr_normal else "Cr",
            "entries": entries
        }

    @staticmethod
    def get_trial_balance() -> Dict[str, Any]:
        """Calculates Trial Balance and checks mathematical balance."""
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT code, name, type, sub_type, balance FROM accounts WHERE code != '3200' ORDER BY code ASC;")
        accounts = cursor.fetchall()
        conn.close()

        rows = []
        total_dr = 0.0
        total_cr = 0.0

        for a in accounts:
            bal = round(a["balance"], 2)
            acc_type = a["type"]
            is_dr = acc_type in ("ASSET", "EXPENSE")

            dr_val = bal if is_dr else 0.0
            cr_val = bal if not is_dr else 0.0

            total_dr += dr_val
            total_cr += cr_val

            rows.append({
                "code": a["code"],
                "name": a["name"],
                "type": a["type"],
                "sub_type": a["sub_type"],
                "debit": dr_val,
                "credit": cr_val
            })

        total_dr = round(total_dr, 2)
        total_cr = round(total_cr, 2)
        is_balanced = abs(total_dr - total_cr) < 0.05

        return {
            "accounts": rows,
            "total_debit": total_dr,
            "total_credit": total_cr,
            "is_balanced": is_balanced,
            "discrepancy": round(abs(total_dr - total_cr), 2)
        }

    @staticmethod
    def get_balance_sheet() -> Dict[str, Any]:
        """Generates classified Balance Sheet: Assets = Liabilities + Equity."""
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT code, name, type, sub_type, balance FROM accounts ORDER BY code ASC;")
        accounts = cursor.fetchall()
        conn.close()

        # Calculate live P&L surplus
        pnl = DoubleEntryEngine.get_income_statement()
        net_surplus = pnl["net_surplus"]

        current_assets = []
        investments = []
        fixed_assets = []
        retirement_assets = []

        current_liabilities = []
        long_term_debt = []

        equity = []

        for a in accounts:
            acc_dict = dict(a)
            a_type = a["type"]
            sub = a["sub_type"]
            code = a["code"]

            if a_type == "ASSET":
                if "Current" in sub:
                    current_assets.append(acc_dict)
                elif "Invest" in sub:
                    investments.append(acc_dict)
                elif "Fixed" in sub:
                    fixed_assets.append(acc_dict)
                else:
                    retirement_assets.append(acc_dict)
            elif a_type == "LIABILITY":
                if "Current" in sub:
                    current_liabilities.append(acc_dict)
                else:
                    long_term_debt.append(acc_dict)
            elif a_type == "EQUITY":
                if code == "3200":
                    acc_dict["balance"] = net_surplus
                equity.append(acc_dict)

        total_current_assets = sum(a["balance"] for a in current_assets)
        total_investments = sum(a["balance"] for a in investments)
        total_fixed_assets = sum(a["balance"] for a in fixed_assets)
        total_retirement = sum(a["balance"] for a in retirement_assets)
        total_assets = round(total_current_assets + total_investments + total_fixed_assets + total_retirement, 2)

        total_current_liab = sum(a["balance"] for a in current_liabilities)
        total_long_term_debt = sum(a["balance"] for a in long_term_debt)
        total_liabilities = round(total_current_liab + total_long_term_debt, 2)

        total_equity = round(sum(a["balance"] for a in equity), 2)
        total_liab_and_equity = round(total_liabilities + total_equity, 2)

        is_balanced = abs(total_assets - total_liab_and_equity) < 0.05

        return {
            "assets": {
                "current_assets": current_assets,
                "investments": investments,
                "fixed_assets": fixed_assets,
                "retirement_assets": retirement_assets,
                "total_current_assets": round(total_current_assets, 2),
                "total_investments": round(total_investments, 2),
                "total_fixed_assets": round(total_fixed_assets, 2),
                "total_retirement": round(total_retirement, 2),
                "total_assets": total_assets
            },
            "liabilities": {
                "current_liabilities": current_liabilities,
                "long_term_debt": long_term_debt,
                "total_current_liabilities": round(total_current_liab, 2),
                "total_long_term_debt": round(total_long_term_debt, 2),
                "total_liabilities": total_liabilities
            },
            "equity": {
                "items": equity,
                "total_equity": total_equity
            },
            "total_liabilities_and_equity": total_liab_and_equity,
            "is_balanced": is_balanced,
            "net_worth": total_equity
        }


    @staticmethod
    def get_income_statement() -> Dict[str, Any]:
        """Generates Income & Expense Statement (P&L)."""
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT code, name, type, sub_type, balance FROM accounts WHERE type IN ('INCOME', 'REVENUE', 'EXPENSE') ORDER BY code ASC;")
        accounts = cursor.fetchall()
        conn.close()

        direct_income = []
        other_income = []

        living_expenses = []
        finance_costs = []
        subscriptions = []
        discretionary = []

        for a in accounts:
            acc_dict = dict(a)
            a_type = a["type"]
            sub = a["sub_type"]

            if a_type in ("INCOME", "REVENUE"):
                if "Direct" in sub or "Salary" in sub:
                    direct_income.append(acc_dict)
                else:
                    other_income.append(acc_dict)
            else:
                if "Needs" in sub or "Living" in sub or "Rent" in sub:
                    living_expenses.append(acc_dict)
                elif "Finance" in sub or "Interest" in sub:
                    finance_costs.append(acc_dict)
                elif "Subscript" in sub:
                    subscriptions.append(acc_dict)
                else:
                    discretionary.append(acc_dict)

        total_income = round(sum(a["balance"] for a in direct_income) + sum(a["balance"] for a in other_income), 2)
        total_expenses = round(
            sum(a["balance"] for a in living_expenses) +
            sum(a["balance"] for a in finance_costs) +
            sum(a["balance"] for a in subscriptions) +
            sum(a["balance"] for a in discretionary), 2
        )

        net_surplus = round(total_income - total_expenses, 2)
        savings_rate = round((net_surplus / total_income * 100), 2) if total_income > 0 else 0.0

        return {
            "income": {
                "direct_income": direct_income,
                "other_income": other_income,
                "total_income": total_income
            },
            "expenses": {
                "living_needs": living_expenses,
                "finance_costs": finance_costs,
                "subscriptions": subscriptions,
                "discretionary": discretionary,
                "total_expenses": total_expenses
            },
            "net_surplus": net_surplus,
            "savings_rate_pct": savings_rate
        }

def String_pad(num: int) -> str:
    return str(num).zfill(3)
