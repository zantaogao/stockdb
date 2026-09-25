"""单日评分回放 smoke test：计时 + 验证 as_of 链路可用（只读，不写任何生产表）"""
import time, sys
sys.path.insert(0, '/Users/zantao/.hermes/stockdb')
import duckdb
from core.scoring import score_stock, _load_models
from core.db import TUSHARE_DB_PATH

DATE = '20250630'
_load_models()
conn = duckdb.connect(str(TUSHARE_DB_PATH), read_only=True)
stocks = [r[0] for r in conn.execute(
    "SELECT ts_code FROM stock_basic WHERE ts_code LIKE '%.SH' OR ts_code LIKE '%.SZ'").fetchall()]
print('universe:', len(stocks))
t0 = time.time()
ok = fail = 0
res = []
for i, ts in enumerate(stocks[:300]):  # 抽300只计时
    try:
        code = ts.split('.')[0]
        rows = conn.execute(
            "SELECT trade_date, close, open, high, low, pct_chg, vol, amount FROM daily "
            f"WHERE ts_code='{ts}' AND trade_date <= '{DATE}' ORDER BY trade_date DESC LIMIT 200").fetchall()
        if len(rows) < 120:
            fail += 1; continue
        s = score_stock(code, rows, conn=conn, as_of_date=DATE)
        if s: ok += 1; res.append(s)
        else: fail += 1
    except Exception:
        fail += 1
el = time.time() - t0
print('300股: %.1fs -> 全市场估算 %.0fmin (单线程)' % (el, el/300*len(stocks)/60))
print('sample:', {k: res[0].get(k) for k in ['reg10_pred','reg_pred','reg40_pred']} if res else None)
