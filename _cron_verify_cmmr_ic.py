import sqlite3

c = sqlite3.connect('/Users/zantao/.hermes/stockdb/state.db')
print("== cmmr_ic_daily 最近5条 ==")
for r in c.execute("SELECT date, ic, samples, win_rate, forward_days FROM cmmr_ic_daily ORDER BY date DESC LIMIT 5"):
    print(r)
print("== fusion_ic_daily 最近5条 ==")
for r in c.execute("SELECT date, ic, samples, win_rate, forward_days FROM fusion_ic_daily ORDER BY date DESC LIMIT 5"):
    print(r)
print("== 2026-07-31 行 ==")
for r in c.execute("SELECT date, ic, samples, win_rate, forward_days FROM cmmr_ic_daily WHERE date='2026-07-31'"):
    print("cmmr:", r)
for r in c.execute("SELECT date, ic, samples, win_rate, forward_days FROM fusion_ic_daily WHERE date='2026-07-31'"):
    print("fusion:", r)
