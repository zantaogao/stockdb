import duckdb, sqlite3, os
BASE = os.path.expanduser('~/.hermes/stockdb')
conn = duckdb.connect(os.path.join(BASE,'tushare.db'), read_only=True)
# 异常票复权因子
for ts in ['001225.SZ','002961.SZ','300908.SZ','600825.SH']:
    print(ts, 'adj:', conn.execute(f"SELECT trade_date, adj_factor FROM adj_factor WHERE ts_code='{ts}' AND trade_date>='20260915' ORDER BY trade_date").fetchall())
    print(ts, 'daily:', conn.execute(f"SELECT trade_date, open, close, pre_close, pct_chg FROM daily WHERE ts_code='{ts}' AND trade_date>='20260918' ORDER BY trade_date").fetchall())

# IC 近10信号日重算（各模型均值）
s = sqlite3.connect(os.path.join(BASE,'signals.db'))
rows = s.execute("SELECT signal_date, ic_reg10, ic_reg20, ic_reg40, ic_fusion FROM ic_daily ORDER BY signal_date DESC LIMIT 10").fetchall()
import statistics as st
d = sorted(rows)
for i, name in [(1,'reg10'),(2,'reg20'),(3,'reg40'),(4,'fusion')]:
    vals = [r[i] for r in d if r[i] is not None]
    print(name, 'n=', len(vals), 'mean=', round(st.mean(vals),4), 'last5mean=', round(st.mean(vals[-5:]),4), 'seq=', [round(v,3) for v in vals])
# 中枢系
try:
    tabs=[r[0] for r in s.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '%center%'").fetchall()]
    print('center tables:', tabs)
    for t in tabs:
        cols=[c[1] for c in s.execute(f"PRAGMA table_info({t})").fetchall()]
        print(t, cols)
except Exception as e: print(e)

# 600892 大晟文化日线
c2 = conn.execute("SELECT trade_date, close, pct_chg, vol FROM daily WHERE ts_code='600892.SH' AND trade_date>='20260910' ORDER BY trade_date").fetchall()
print('600892:', c2)
# 中枢版账户 fusion_center 持仓对应
s.close()
