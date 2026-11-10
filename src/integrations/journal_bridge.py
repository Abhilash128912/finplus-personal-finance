"""
FinPlus+ Trading Journal Integration Bridge
App #5 -> App #4
Reads actual completed trades from D:\AI_APPS\finplus_trading_journal\journal.db
STRICT FILTER: trade_mode == 'REAL'. Paper trades are strictly discarded!
"""

import sqlite3
from typing import Dict, Any, List
from pathlib import Path
from config.settings import JOURNAL_DB_PATH
from src.db.database import get_connection
from src.utils.time_and_logger import setup_logger, get_utc_iso, get_ist_now

logger = setup_logger("JournalBridge")

class JournalBridge:
    """
    Synchronizes actual realized trading P&L and wallet margin into App #5 accounting ledger.
    """

    @staticmethod
    def sync_real_trading_results() -> Dict[str, Any]:
        """
        Queries journal.db for all REAL trades, computes net aggregate P&L,
        and updates App #5 accounts 1140 (Margin Asset) and 4210 (Other Income).
        """
        if not JOURNAL_DB_PATH.exists():
            logger.warning(f"Journal database not found at {JOURNAL_DB_PATH}.")
            return {
                "status": "OFFLINE",
                "message": "journal.db not located",
                "real_trades_count": 0,
                "net_realized_pnl": 0.0,
                "trading_margin": 0.0
            }

        try:
            # Connect to App #4 journal.db read-only
            j_conn = sqlite3.connect(f"file:{JOURNAL_DB_PATH}?mode=ro", uri=True, timeout=5.0)
            j_conn.row_factory = sqlite3.Row
            cursor = j_conn.cursor()

            # Query REAL completed trades only
            cursor.execute("""
            SELECT COUNT(*) AS total_real,
                   COALESCE(SUM(net_pnl), 0.0) AS total_net_pnl,
                   COALESCE(SUM(CASE WHEN net_pnl > 0 THEN 1 ELSE 0 END), 0) AS real_wins,
                   COALESCE(SUM(CASE WHEN net_pnl <= 0 THEN 1 ELSE 0 END), 0) AS real_losses
            FROM trades
            WHERE trade_mode = 'REAL';
            """)
            trade_stats = cursor.fetchone()

            total_real = trade_stats["total_real"]
            total_net_pnl = round(float(trade_stats["total_net_pnl"]), 2)
            wins = trade_stats["real_wins"]
            losses = trade_stats["real_losses"]

            # Query active wallet margin balance if available
            margin = 0.0
            try:
                cursor.execute("SELECT SUM(allocation_capital) FROM intraday_pool;")
                row = cursor.fetchone()
                if row and row[0]:
                    margin = round(float(row[0]), 2)
            except Exception:
                pass

            j_conn.close()

            # Reconcile into App #5 accounts
            conn = get_connection()
            f_cursor = conn.cursor()

            # Update account 1140 (Trading Margin) only if real margin exists
            if margin > 0.0:
                f_cursor.execute("UPDATE accounts SET balance = ? WHERE code = '1140';", (margin,))

            # Update account 4210 (Realized Trading Gains) if REAL P&L exists
            if total_net_pnl != 0.0:
                f_cursor.execute("UPDATE accounts SET balance = ? WHERE code = '4210';", (total_net_pnl,))

            conn.commit()
            conn.close()

            logger.info(f"Journal Bridge Sync Complete: {total_real} REAL trades synced. Net P&L: ₹{total_net_pnl}, Margin: ₹{margin}.")
            return {
                "status": "SYNCED",
                "real_trades_count": total_real,
                "net_realized_pnl": total_net_pnl,
                "wins": wins,
                "losses": losses,
                "win_rate": round(wins / total_real * 100, 1) if total_real > 0 else 0.0,
                "trading_margin": margin,
                "synced_at": get_ist_now().strftime("%Y-%m-%d %H:%M:%S IST")
            }
        except Exception as e:
            logger.error(f"Error querying journal.db: {e}")
            return {
                "status": "ERROR",
                "error": str(e),
                "trading_margin": 0.0
            }

