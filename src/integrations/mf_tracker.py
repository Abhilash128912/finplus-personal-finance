"""
FinPlus+ Mutual Funds Portfolio & AMFI Daily Tracker
App #5
Fetches official daily NAVs from AMFI (Association of Mutual Funds in India via api.mfapi.in)
Tracks invested amount, live market valuation, absolute/CAGR returns, and updates account 1210.
"""

import urllib.request
import json
from typing import List, Dict, Any, Optional
from src.db.database import get_connection
from src.utils.time_and_logger import setup_logger, get_utc_iso, get_ist_now

logger = setup_logger("MutualFundsTracker")

AMFI_API_BASE = "https://api.mfapi.in/mf"

class MutualFundsTracker:
    """
    Manages user Mutual Fund holdings and fetches live AMFI daily NAVs.
    """

    @staticmethod
    def get_portfolio() -> Dict[str, Any]:
        """Returns all schemes, portfolio totals, and performance summary."""
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
        SELECT id, scheme_code, scheme_name, category, units, avg_buy_nav, latest_nav, nav_date, sip_day, last_updated
        FROM mutual_funds
        ORDER BY id ASC;
        """)
        funds = cursor.fetchall()
        conn.close()

        holdings = []
        tot_invested = 0.0
        tot_current = 0.0

        for f in funds:
            units = float(f["units"])
            buy_nav = float(f["avg_buy_nav"])
            latest_nav = float(f["latest_nav"])

            invested = round(units * buy_nav, 2)
            current = round(units * latest_nav, 2)
            pnl = round(current - invested, 2)
            ret_pct = round((pnl / invested * 100), 2) if invested > 0 else 0.0

            tot_invested += invested
            tot_current += current

            holdings.append({
                "id": f["id"],
                "scheme_code": f["scheme_code"],
                "scheme_name": f["scheme_name"],
                "category": f["category"],
                "units": units,
                "avg_buy_nav": buy_nav,
                "latest_nav": latest_nav,
                "nav_date": f["nav_date"],
                "sip_day": f["sip_day"],
                "invested_amount": invested,
                "current_valuation": current,
                "net_pnl": pnl,
                "return_pct": ret_pct
            })

        tot_invested = round(tot_invested, 2)
        tot_current = round(tot_current, 2)
        tot_pnl = round(tot_current - tot_invested, 2)
        tot_ret_pct = round((tot_pnl / tot_invested * 100), 2) if tot_invested > 0 else 0.0

        return {
            "total_invested": tot_invested,
            "current_valuation": tot_current,
            "total_pnl": tot_pnl,
            "absolute_return_pct": tot_ret_pct,
            "schemes_count": len(holdings),
            "holdings": holdings,
            "updated_at": get_ist_now().strftime("%Y-%m-%d %H:%M:%S IST")
        }

    @staticmethod
    def add_fund(scheme_code: str, scheme_name: str, category: str, units: float, avg_buy_nav: float, sip_day: int = 10) -> Dict[str, Any]:
        """Adds a new mutual fund scheme and fetches its live AMFI NAV."""
        live_nav = avg_buy_nav
        nav_date = get_ist_now().strftime("%d-%m-%Y")

        # Attempt to fetch live NAV from AMFI
        try:
            url = f"{AMFI_API_BASE}/{scheme_code}"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode())
                if data.get("data"):
                    latest = data["data"][0]
                    live_nav = float(latest["nav"])
                    nav_date = latest["date"]
                    if not scheme_name and data.get("meta"):
                        scheme_name = data["meta"].get("scheme_name", scheme_name)
        except Exception as e:
            logger.warning(f"Could not fetch AMFI live NAV for {scheme_code}: {e}")

        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
        INSERT INTO mutual_funds (scheme_code, scheme_name, category, units, avg_buy_nav, latest_nav, nav_date, sip_day, last_updated)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(scheme_code) DO UPDATE SET
            units = units + excluded.units,
            latest_nav = excluded.latest_nav,
            last_updated = excluded.last_updated;
        """, (scheme_code, scheme_name, category, units, avg_buy_nav, live_nav, nav_date, sip_day, get_utc_iso()))
        conn.commit()
        conn.close()

        # Update account 1210 in accounts table
        MutualFundsTracker.sync_valuation_to_balance_sheet()

        return {"status": "SUCCESS", "scheme_code": scheme_code, "live_nav": live_nav}

    @staticmethod
    def sync_all_amfi_navs() -> Dict[str, Any]:
        """Fetches live closing NAVs for all portfolio schemes from AMFI."""
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id, scheme_code FROM mutual_funds;")
        funds = cursor.fetchall()

        updated_count = 0
        for f in funds:
            code = f["scheme_code"]
            try:
                url = f"{AMFI_API_BASE}/{code}"
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=5) as resp:
                    data = json.loads(resp.read().decode())
                    if data.get("data"):
                        latest = data["data"][0]
                        nav = float(latest["nav"])
                        nav_date = latest["date"]
                        cursor.execute("""
                        UPDATE mutual_funds
                        SET latest_nav = ?, nav_date = ?, last_updated = ?
                        WHERE id = ?;
                        """, (nav, nav_date, get_utc_iso(), f["id"]))
                        updated_count += 1
            except Exception as e:
                logger.error(f"Failed updating NAV for scheme {code}: {e}")

        conn.commit()
        conn.close()

        # Update balance sheet account 1210
        MutualFundsTracker.sync_valuation_to_balance_sheet()

        return {
            "status": "COMPLETED",
            "updated_schemes": updated_count,
            "timestamp": get_ist_now().strftime("%Y-%m-%d %H:%M:%S IST")
        }

    @staticmethod
    def sync_valuation_to_balance_sheet():
        """Updates account 1210 in the accounts table to match the live portfolio market value."""
        portfolio = MutualFundsTracker.get_portfolio()
        tot_val = portfolio["current_valuation"]

        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE accounts SET balance = ? WHERE code = '1210';", (tot_val,))
        conn.commit()
        conn.close()
        logger.info(f"Account 1210 (Mutual Funds) updated on Balance Sheet to ₹{tot_val}.")

