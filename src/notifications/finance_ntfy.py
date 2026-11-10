"""
FinPlus+ Personal Finance NTFY Alert Dispatcher
App #5
Dispatches automated daily portfolio briefings, SIP debit reminders, and market dip triggers.
"""

import urllib.request
import json
from typing import Dict, Any, Optional
from config.settings import NTFY_SERVER, NTFY_TOPIC
from src.db.database import get_connection
from src.utils.time_and_logger import setup_logger, get_utc_iso, get_ist_now

logger = setup_logger("FinanceNTFY")

class FinanceNTFYDispatcher:
    @staticmethod
    def send_notification(
        title: str,
        message: str,
        category: str = "DAILY_BRIEFING",
        tags: str = "chart_with_upwards_trend,moneybag",
        priority: str = "3"
    ) -> bool:
        """Sends a notification to the user's phone via NTFY."""
        url = f"{NTFY_SERVER}/{NTFY_TOPIC}"
        headers = {
            "Title": title.encode("utf-8"),
            "Priority": priority,
            "Tags": tags
        }

        try:
            req = urllib.request.Request(url, data=message.encode("utf-8"), headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=5) as resp:
                if resp.status == 200:
                    logger.info(f"NTFY push alert delivered: {title}")
                    # Save to database log
                    conn = get_connection()
                    cursor = conn.cursor()
                    cursor.execute("""
                    INSERT INTO daily_alerts (title, message, category, dispatched_at)
                    VALUES (?, ?, ?, ?);
                    """, (title, message, category, get_utc_iso()))
                    conn.commit()
                    conn.close()
                    return True
        except Exception as e:
            logger.error(f"Failed to dispatch NTFY notification: {e}")
            return False
        return False

