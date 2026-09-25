# 对账：账本 market_ret vs 真实中证1000 日涨幅，并算修正后真实超额
import duckdb, sqlite3

td = duckdb.connect('/Users/zantao/.hermes/stockdb/tushare.db', read_only=True)
rows = td.execute(
    "SELECT date, close FROM index_daily WHERE index_code='000852' "
    "AND date BETWEEN DATE '2026-08-03' AND DATE '2026-09-16' ORDER BY date").fetchall()
real = {}
prev = None
first_close = rows[0][1]
for d, c in rows:
    if prev is not None:
        real[str(d).replace('-', '')] = round((c / prev - 1) * 100, 4)
    prev = c

db = sqlite3.connect('file:/Users/zantao/.hermes/stockdb/ledger.db?mode=ro', uri=True)
saved = db.execute(
    "SELECT date, market_ret FROM strategy_accounts WHERE account_id='cmmr' ORDER BY date").fetchall()

print('date | 账本mr | 真实日涨幅 | 差')
n_diff = 0
for d, mr in saved:
    r_ = real.get(d)
    if r_ is None:
        continue
    if abs((mr or 0) - r_) > 0.15:
        n_diff += 1
        print(f"{d} | {mr} | {r_} | 差{(mr or 0)-r_:+.2f}")
print('差异>0.15%的天数:', n_diff, '/', len(real))

bench = (rows[-1][1] / first_close - 1) * 100
print('真实基准累计(8/3收→9/16收):', round(bench, 2), '%')
for aid in ['cmmr', 'cmmr_fusion']:
    nav = db.execute(
        "SELECT nav FROM strategy_accounts WHERE account_id=? ORDER BY date DESC LIMIT 1",
        (aid,)).fetchone()[0]
    cum = (nav / 1e6 - 1) * 100
    print(aid, '| 累计', round(cum, 2), '% | 真实超额', round(cum - bench, 2), '%')
