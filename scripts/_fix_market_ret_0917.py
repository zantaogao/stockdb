# 20260804 market_ret 修数：账本记的是盘中瞬时值(+0.33%)，真实收盘 +2.82%
# 全账户扫描：所有 strategy_accounts 行，与中证1000官方收盘日涨幅对账，差>0.15pp 的改为真实值
# 一次性脚本（2026-09-17 用户拍板）
import shutil, sqlite3, duckdb

LEDGER = '/Users/zantao/.hermes/stockdb/ledger.db'
BAK = LEDGER + '.bak.20260917_mrfix'

td = duckdb.connect('/Users/zantao/.hermes/stockdb/tushare.db', read_only=True)
rows = td.execute(
    "SELECT date, close FROM index_daily WHERE index_code='000852' ORDER BY date").fetchall()
real = {}
prev = None
for d, c in rows:
    if prev is not None:
        real[str(d).replace('-', '')] = round((c / prev - 1) * 100, 4)
    prev = c

shutil.copy2(LEDGER, BAK)
print('备份:', BAK)

db = sqlite3.connect(LEDGER)
bad = db.execute(
    "SELECT account_id, date, market_ret FROM strategy_accounts").fetchall()
n_fix = 0
for aid, d, mr in bad:
    r_ = real.get(d)
    if r_ is None:
        continue  # 指数首日无涨幅可比
    if abs((mr if mr is not None else 0.0) - r_) > 0.15:
        print(f"改: {aid} {d}: {mr} -> {r_}")
        db.execute("UPDATE strategy_accounts SET market_ret=? WHERE account_id=? AND date=?",
                   (r_, aid, d))
        n_fix += 1
db.commit()
print('共修正', n_fix, '行')

# 验证
db2 = sqlite3.connect('file:' + LEDGER + '?mode=ro', uri=True)
for aid in ['cmmr', 'cmmr_fusion']:
    nav = db2.execute("SELECT nav FROM strategy_accounts WHERE account_id=? ORDER BY date DESC LIMIT 1",
                      (aid,)).fetchone()[0]
    srs = db2.execute("SELECT market_ret FROM strategy_accounts WHERE account_id=? ORDER BY date",
                      (aid,)).fetchall()
    b = 1.0
    for (m,) in srs:
        if m is not None:
            b *= (1 + m / 100)
    cum = (nav / 1e6 - 1) * 100
    print(f"复核 {aid}: 累计 {cum:.2f}% 超额(账本基准重算) {cum - (b - 1) * 100:.2f}%")
