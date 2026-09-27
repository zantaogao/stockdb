"""fusion_score 历史验证 + ex修复影响对比（0926）
A) 历史 40 个信号日（旧口径入库, ex=0）：fus 分层/ρ vs 后5日超额
B) 修复后对 3 个采样信号日重算 ex（新口径），对比新旧 top100 与分层
"""
import duckdb, sqlite3, sys, numpy as np
sys.path.insert(0, '/Users/zantao/.hermes/stockdb/scripts')
sys.path.insert(0, '/Users/zantao/.hermes/stockdb')
from scipy import stats

TUSHARE = '/Users/zantao/.hermes/stockdb/tushare.db'
conn = duckdb.connect(TUSHARE, read_only=True)
idx = conn.execute("SELECT date, close FROM index_daily WHERE index_code='000001' ORDER BY date").fetchall()
dates = [str(d)[:10] for d, _ in idx]
mkt = np.diff(np.log([float(c) for _, c in idx]))
sig_dates = [r[0] for r in sqlite3.connect('/Users/zantao/.hermes/stockdb/signals.db').execute(
    "SELECT DISTINCT REPLACE(date,'-','') FROM signal_history ORDER BY date DESC LIMIT 40").fetchall()]
print('验证窗口:', sig_dates[-1], '→', sig_dates[0], f'共{len(sig_dates)}个信号日')

# 每票日线缓存一次
all_daily = {}
for ts, td, c in conn.execute("SELECT ts_code, trade_date, close FROM daily").fetchall():
    all_daily.setdefault(ts, []).append((str(td), float(c)))
for ts in all_daily: all_daily[ts].sort()

def fwd_excess(ts, d8, n=5):
    ser = all_daily.get(ts, [])
    i = np.searchsorted([x[0] for x in ser], d8, side='right')
    base = None
    for k in range(len(ser) - 1, -1, -1):
        if ser[k][0] <= d8: base = ser[k][1]; break
    if base is None or len(ser) <= i + n - 1: return None
    if ser[i + n - 1][0] == ser[i - 1][0]: return None  # 停牌
    return ser[i + n - 1][1] / base - 1 - float(np.exp(np.sum(mkt[dates.index(f"{d8[:4]}-{d8[4:6]}-{d8[6:]}"):dates.index(f"{d8[:4]}-{d8[4:6]}-{d8[6:]}") + n])) - 1)

sh = sqlite3.connect('/Users/zantao/.hermes/stockdb/signals.db')
ic_rows = []
for d8 in sig_dates:
    pairs = []
    for code, fs in sh.execute(f"SELECT stock_code, fusion_score FROM signal_history WHERE REPLACE(date,'-','')='{d8}' AND fusion_score IS NOT NULL").fetchall():
        ts = f"{code}.SH" if code[0] == '6' else (f"{code}.BJ" if code[0] == '9' else f"{code}.SZ")
        ex = fwd_excess(ts, d8)
        if ex is not None: pairs.append((float(fs), ex))
    if len(pairs) >= 2000:
        a = np.array(pairs)
        rho = stats.spearmanr(a[:, 0], a[:, 1]).statistic
        ic_rows.append((d8, len(a), rho, a[np.argsort(a[:, 0])][-10:, 1].mean(), a[:, 1].mean()))
        print(f'{d8} n={len(a)} ρ={rho:+.4f} top10ex={ic_rows[-1][3]:+.4f} mkt_ex={ic_rows[-1][4]:+.4f}', flush=True)
sh.close()
R = np.array(ic_rows)
t = R[:, 2].mean() / (R[:, 2].std(ddof=1) / np.sqrt(len(R)))
print(f'\nA) 40日 平均ρ={R[:,2].mean():+.4f} NW-t≈{t:.2f} top10日均超额均值={R[:,3].mean():+.4f}')
conn.close()
