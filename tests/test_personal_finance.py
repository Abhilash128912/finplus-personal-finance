"""
Focused unit and API tests for FinPlus+ Personal Finance & Double-Entry Accounting Engine.
Uses an isolated temporary SQLite database per test.
"""

import pytest
from fastapi.testclient import TestClient

import config.settings as settings
import src.db.database as db_mod
from src.accounting.double_entry_engine import DoubleEntryEngine
from src.integrations.gold_engine import GoldEngine
from src.integrations.loan_engine import LoanEngine
from src.api.server import app


@pytest.fixture()
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "test_finance.db"
    monkeypatch.setattr(settings, "DB_PATH", db_file)
    monkeypatch.setattr(db_mod, "DB_PATH", db_file)
    monkeypatch.setattr(db_mod, "IS_POSTGRES", False)
    db_mod.init_database()
    return db_file


def test_post_voucher_and_uniqueness(temp_db):
    res1 = DoubleEntryEngine.post_voucher(
        voucher_date="2027-01-15",
        narration="Salary credit",
        entries=[
            {"account_code": "1110", "debit": 50000.0, "credit": 0.0},
            {"account_code": "4110", "debit": 0.0, "credit": 50000.0},
        ],
    )
    assert res1["status"] == "SUCCESS"
    assert res1["voucher_id"] == 1
    assert res1["voucher_no"] == "JV-2027-001"

    res2 = DoubleEntryEngine.post_voucher(
        voucher_date="2027-01-16",
        narration="Rent payment",
        entries=[
            {"account_code": "5110", "debit": 12000.0, "credit": 0.0},
            {"account_code": "1110", "debit": 0.0, "credit": 12000.0},
        ],
    )
    assert res2["voucher_no"] == "JV-2027-002"

    # Delete first voucher and post a third: MAX(voucher_id)+1 avoids UNIQUE collision with JV-2027-002
    conn = db_mod.get_connection()
    try:
        conn.execute("DELETE FROM journal_vouchers WHERE voucher_id = ?;", (res1["voucher_id"],))
        conn.commit()
    finally:
        conn.close()

    res3 = DoubleEntryEngine.post_voucher(
        voucher_date="2027-01-17",
        narration="Groceries",
        entries=[
            {"account_code": "5120", "debit": 3000.0, "credit": 0.0},
            {"account_code": "1110", "debit": 0.0, "credit": 3000.0},
        ],
    )
    assert res3["voucher_no"] == "JV-2027-003"

    tb = DoubleEntryEngine.get_trial_balance()
    assert tb["is_balanced"] is True

    with pytest.raises(ValueError, match="Double-entry violation"):
        DoubleEntryEngine.post_voucher(
            voucher_date="2027-01-17",
            narration="Unbalanced",
            entries=[
                {"account_code": "1110", "debit": 100.0, "credit": 0.0},
                {"account_code": "4110", "debit": 0.0, "credit": 50.0},
            ],
        )


def test_create_account_opening_balance_and_404s(temp_db):
    client = TestClient(app)

    # Create account with non-zero opening balance -> balanced via 3100
    resp = client.post(
        "/api/accounts",
        json={
            "code": "1199",
            "name": "Test Wallet",
            "type": "ASSET",
            "sub_type": "Current Asset",
            "opening_balance": 2500.0,
            "description": "Test",
        },
    )
    assert resp.status_code == 200

    tb = DoubleEntryEngine.get_trial_balance()
    assert tb["is_balanced"] is True
    assert tb["total_debit"] == 2500.0
    assert tb["total_credit"] == 2500.0

    # Duplicate account -> 400
    dup = client.post(
        "/api/accounts",
        json={
            "code": "1199",
            "name": "Dup Wallet",
            "type": "ASSET",
            "sub_type": "Current Asset",
        },
    )
    assert dup.status_code == 400

    # Update / Delete missing account -> 404
    upd_404 = client.put(
        "/api/accounts/9999",
        json={"name": "Missing", "sub_type": "Current Asset", "description": ""},
    )
    assert upd_404.status_code == 404

    del_404 = client.delete("/api/accounts/9999")
    assert del_404.status_code == 404


def test_gold_engine_updates_only_target_row(temp_db):
    conn = db_mod.get_connection()
    try:
        conn.execute(
            """
            INSERT INTO gold_holdings (asset_name, grams, purity, market_rate_per_gram, haircut_pct, last_updated)
            VALUES ('Secondary Sovereign', 50.0, '22K', 10000.0, 23.0, '2026-01-01T00:00:00Z');
            """
        )
        conn.commit()
    finally:
        conn.close()

    val = GoldEngine.update_gold_holding(grams=10.0, rate=14000.0)
    assert val["grams"] == 10.0
    assert val["net_recognized_asset_value"] == round(10.0 * 14000.0 * 0.77, 2)

    conn = db_mod.get_connection()
    try:
        rows = conn.execute("SELECT id, asset_name, grams FROM gold_holdings ORDER BY id ASC;").fetchall()
        assert len(rows) == 2
        assert rows[0]["grams"] == 10.0
        assert rows[1]["grams"] == 50.0  # Untouched!
    finally:
        conn.close()

    tb = DoubleEntryEngine.get_trial_balance()
    assert tb["is_balanced"] is True


def test_loan_engine_uses_loan_account_code(temp_db):
    conn = db_mod.get_connection()
    try:
        conn.execute(
            """
            INSERT INTO loans (loan_name, account_code, principal, start_date, annual_rate_pct, mode, manual_realized_interest, monthly_emi)
            VALUES ('Personal Loan', '2230', 100000.0, '2026-01-01', 12.0, 'MANUAL', 5000.0, 4500.0);
            """
        )
        conn.commit()
        loan_id = conn.execute("SELECT id FROM loans WHERE account_code = '2230';").fetchone()["id"]
    finally:
        conn.close()

    LoanEngine.update_loan(
        loan_id=loan_id,
        principal=80000.0,
        start_date="2026-01-01",
        rate=12.0,
        mode="MANUAL",
        manual_interest=2500.0,
    )

    conn = db_mod.get_connection()
    try:
        bal_2230 = conn.execute("SELECT balance FROM accounts WHERE code = '2230';").fetchone()["balance"]
        bal_2210 = conn.execute("SELECT balance FROM accounts WHERE code = '2210';").fetchone()["balance"]
        assert bal_2230 == 82500.0
        assert bal_2210 == 0.0
    finally:
        conn.close()

    with pytest.raises(ValueError, match="not found"):
        LoanEngine.update_loan(9999, 1000.0, "2026-01-01", 10.0, "MANUAL", 0.0)
