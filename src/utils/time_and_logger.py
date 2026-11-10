"""
FinPlus+ Utilities: Logger and Time Management
"""

import logging
import sys
from datetime import datetime, timezone, timedelta

IST = timezone(timedelta(hours=5, minutes=30))

def get_utc_now() -> datetime:
    return datetime.now(timezone.utc)

def get_utc_iso() -> str:
    return get_utc_now().isoformat()

def get_ist_now() -> datetime:
    return datetime.now(IST)

def get_ist_time_str() -> str:
    return get_ist_now().strftime("%Y-%m-%d %H:%M:%S IST")

def setup_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    if not logger.handlers:
        logger.setLevel(logging.INFO)
        handler = logging.StreamHandler(sys.stdout)
        formatter = logging.Formatter(
            fmt="[%(asctime)s] [%(levelname)s] [%(name)s]: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    return logger

