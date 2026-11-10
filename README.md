# FinPlus+ Wealth & Double-Entry Accounting Engine (App #5)

**App Code:** `APP_05_PERSONAL_FINANCE`  
**Standard Port:** `8004`  
**Database:** Local SQLite (`personal_finance.db` in WAL mode)  
**Standard:** Ind AS / GAAP Double-Entry Mathematical Accounting System  

---

## Capabilities & Architecture
1. **General Journal**: Every transaction is an atomic, balanced double-entry voucher ($\sum \text{Debit} = \sum \text{Credit}$).
2. **General Ledger**: Dynamic T-Account statements with live running balances for any account in the Chart of Accounts.
3. **Trial Balance**: Mathematical proof verifying zero accounting discrepancies.
4. **Classified Balance Sheet**: Assets = Liabilities + Owner's Equity.
5. **Income & Expense Statement (P&L)**: Direct Income + Other Income vs categorized expenses, yielding Net Period Surplus and Savings Rate %.
6. **Mutual Fund Portfolio & AMFI Daily Tracker**:
   - Official daily closing NAVs from Association of Mutual Funds in India (`api.mfapi.in/mf/{scheme_code}`).
   - Tracks units, average purchase cost, invested capital, live market valuation, absolute/CAGR returns, and updates account `1210`.
7. **Automated Long-Term Tracking & Alerts (via NTFY)**:
   - Daily 21:15 IST Portfolio Valuation Briefing.
   - Monthly SIP Due Date Reminders (alerts 2 days prior to bank debit).
   - Market Dip Buying Trigger (alerts when Nifty drops > 1.5% from App #1 breadth).
   - Milestone Radar (portfolio valuation thresholds).
8. **App #4 Trading Journal Live Bridge**:
   - Strictly queries `D:\AI_APPS\finplus_trading_journal\journal.db` for `trade_mode == 'REAL'`.
   - Realized Net P&L (post-tax & post-INDmoney fees) auto-posted into Account `1140 (Trading Margin)` and `4210 (Other Income)`.
9. **Physical 22K Gold Sub-Ledger**:
   - Grams held $\times$ Goodreturns Kerala market rate minus 23% pledge/depreciation haircut.
10. **Two-Way Loan Accounting**:
    - Auto-Accrue from start date & rate% OR manual realized interest.

---

## Running the Server
```powershell
cd D:\AI_APPS\finplus_personal_finance
python -m uvicorn src.api.server:app --host 127.0.0.1 --port 8004
```
Access dashboard at `http://localhost:8004`.

