import sqlite3
c = sqlite3.connect('/Users/zantao/.hermes/stockdb/ledger.db')
c.row_factory = sqlite3.Row
cols = [d[1] for d in c.execute("PRAGMA table_info(strategy_positions)")]
print("strategy_positions cols:", cols)
# 今日变动过的持仓（按 update_date/日期列查）
for dcol in ('update_date','trade_date','date','buy_date','updated_at'):
    if dcol in cols:
        rows = c.execute(f"SELECT * FROM strategy_positions WHERE replace({dcol},'-','')>=? ", ('20260831',)).fetchall()
        print(f"rows with {dcol}>=20260831:", len(rows))
        for r in rows:
            print(dict(r))
# 各账户今日 NAV
mcols = [d[1] for d in c.execute("PRAGMA table_info(strategy_accounts_meta)")]
print("meta cols:", mcols)
for r in c.execute("SELECT * FROM strategy_accounts_meta").fetchall():
    d = dict(r)
    print({k: d.get(k) for k in ('name','strategy','nav','nav_date','date','last_update','cash') if k in d})