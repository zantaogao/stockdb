# 回放V6: 卖对/卖早 分组 vs 触发日盘中特征（研判层有没有可用的区分信号）
import json, statistics, duckdb

out = json.load(open('analysis/replay_paths_0902.json'))
sig = duckdb.connect('/Users/zantao/.hermes/stockdb/signals.db', read_only=True)
ts = duckdb.connect('/Users/zantao/.hermes/stockdb/tushare.db', read_only=True)
ts.execute("CREATE TEMP TABLE dsub AS SELECT stock_code, strftime(date,'%Y%m%d') nd, open, change_pct FROM stock_daily WHERE strftime(date,'%Y%m%d')>='20260720'")

FEATS = ['open30_ret', 'tail30_ret', 'vwap_dev', 'rv_1m', 'amp_intra', 'vol_dist_am', 'vol_dist_tail', 'tail5_ret', 'last_vol_share']

def label(r):
    v = r.get('t5_close')
    if v is None or not r['px']: return None
    return '卖对' if v < r['px'] else '卖早'

items = []
for r in out:
    lb = label(r)
    if lb is None: continue
    nd = str(r['date']).replace('-', '')
    f = sig.execute(f"SELECT {', '.join(FEATS)} FROM tdx_intraday_feat WHERE date=? AND code=?",
                    [nd, r['code']]).fetchone()
    d = ts.execute("SELECT change_pct FROM dsub WHERE stock_code=? AND nd=?", [r['code'], nd]).fetchone()
    if f:
        items.append((lb, r['code'], r['pnl_pct'], f, d[0] if d else None))

print(f'有特征的已判定样本: {len(items)}')
for lb in ('卖对', '卖早'):
    sub = [x for x in items if x[0] == lb]
    if not sub: continue
    print(f'\n{lb}组 n={len(sub)}:')
    for _, code, pnl, f, chg in sub:
        fs = ' '.join('%s=%s' % (n, ('%.2f' % v) if v is not None else 'na') for n, v in zip(FEATS, f))
        print(f'  {code} pnl={pnl:+.1f}% 日涨跌={chg if chg is not None else "na"}% | {fs}')

for i, name in enumerate(FEATS):
    a = [x[3][i] for x in items if x[0]=='卖对' and x[3][i] is not None]
    b = [x[3][i] for x in items if x[0]=='卖早' and x[3][i] is not None]
    if a and b:
        print(f'{name:15s} 卖对均={statistics.mean(a):+.3f} (n={len(a)})  卖早均={statistics.mean(b):+.3f} (n={len(b)})')