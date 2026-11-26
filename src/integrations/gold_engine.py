"""
FinPlus+ Physical Gold Valuation Engine
App #5
Formula: Grams × 22K Rate/Gram (Goodreturns Kerala) minus 23% pledge/depreciation haircut.
Updates account 1230 in SQLite.
"""

from typing import Dict, Any
from src.db.database import get_connection
from src.utils.time_and_logger import setup_logger, get_utc_iso, get_ist_now

logger = setup_logger("GoldEngine")

class GoldEngine:
    @staticmethod
    def get_gold_valuation() -> Dict[str, Any]:
        """Returns physical gold holding and computed net recognized valuation."""
        conn = get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT grams, market_rate_per_gram, haircut_pct, last_updated FROM gold_holdings ORDER BY id ASC LIMIT 1;")
            row = cursor.fetchone()
        finally:
            conn.close()

        if not row:
            grams = 80.0
            rate = 13256.0
            haircut_pct = 23.0
        else:
            grams = float(row["grams"])
            rate = float(row["market_rate_per_gram"])
            haircut_pct = float(row["haircut_pct"])

        gross = round(grams * rate, 2)
        haircut = round(gross * (haircut_pct / 100.0), 2)
        net_val = round(gross - haircut, 2)

        return {
            "grams": grams,
            "purity": "22 Karat (91.6% Purity)",
            "market_rate_per_gram": rate,
            "source": "Goodreturns Kerala / India",
            "gross_market_value": gross,
            "haircut_pct": haircut_pct,
            "haircut_deduction": haircut,
            "net_recognized_asset_value": net_val,
            "pavan": round(grams / 8.0, 1)
        }

    @staticmethod
    def update_gold_holding(grams: float, rate: float, holding_id: int = None) -> Dict[str, Any]:
        """Updates gold holding weight or live Goodreturns market rate."""
        conn = get_connection()
        try:
            cursor = conn.cursor()
            now_iso = get_utc_iso()
            if holding_id is None:
                cursor.execute("SELECT id FROM gold_holdings ORDER BY id ASC LIMIT 1;")
                existing = cursor.fetchone()
                target_id = existing["id"] if existing else None
            else:
                target_id = holding_id

            if target_id is not None:
                cursor.execute("""
                UPDATE gold_holdings
                SET grams = ?, market_rate_per_gram = ?, last_updated = ?
                WHERE id = ?;
                """, (grams, rate, now_iso, target_id))
            else:
                cursor.execute("""
                INSERT INTO gold_holdings (asset_name, grams, purity, market_rate_per_gram, haircut_pct, last_updated)
                VALUES ('22 Karat Gold Jewellery & Sovereign Bars', ?, '22K', ?, 23.0, ?);
                """, (grams, rate, now_iso))

            gross = grams * rate
            net_val = round(gross * 0.77, 2) # 23% haircut

            cursor.execute("SELECT balance FROM accounts WHERE code = '1230';")
            old_row = cursor.fetchone()
            old_val = float(old_row[0]) if old_row else 0.0
            delta = round(net_val - old_val, 2)

            # Update account 1230 in balance sheet
            cursor.execute("UPDATE accounts SET balance = ? WHERE code = '1230';", (net_val,))
            # Update owner's capital account 3100 to preserve double-entry equality
            cursor.execute("UPDATE accounts SET balance = balance + ? WHERE code = '3100';", (delta,))
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

        logger.info(f"Gold holding updated: {grams}g @ ₹{rate}/g = Net Asset Value ₹{net_val}.")
        return GoldEngine.get_gold_valuation()

