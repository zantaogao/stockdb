# 回放V4: 止损35笔持有到 T+5/T+10 的全路径 + 卖对/卖早分界特征 + 上界核算
import json, duckdb, statistics

rows = json.load(open('analysis/replay_paths_0902.json'))
ts = duckdb.connect('/Users/zantao/.hermes/stockdb/tushare.db', read_only=True)
ts.execute("CREATE TEMP TABLE dsub AS SELECT stock_code, strftime(date,'%Y%m%d') nd, open, high, low, close FROM stock_daily WHERE strftime(date,'%Y%m%d')>='20260720'")
cal = [r[0] for r in ts.execute("SELECT DISTINCT nd FROM dsub ORDER BY nd").fetchall()]

def px(code, nd, col):
    r = ts.execute(f"SELECT {col} FROM dsub WHERE stock_code=? AND nd=?", [code, nd]).fetchone()
    return r[0] if r else None

def nstep(nd, k):
    if nd not in cal: return None
    i = cal.index(nd)
    return cal[i+k] if i+k < len(cal) else None

out = []
for r in rows:
    nd = str(r['date']).replace('-', '')
    code = r['code']
    row = dict(r)
    for k in (1, 3, 5, 10):
        d2 = nstep(nd, k)
        row[f't{k}_close'] = px(code, d2, 'close') if d2 else None
        lows = [px(code, nstep(nd, j), 'low') for j in range(1, k+1) if nstep(nd, j)]
        lows = [x for x in lows if x]
        row[f't{k}_low'] = min(lows) if lows else None
    out.append(row)
json.dump(out, open('analysis/replay_paths_0902.json', 'w'), ensure_ascii=False)

def ret(r, k, base='px'):
    v = r.get(f't{k}_close')
    return None if not v or not r.get(base) else (v/r[base]-1)*100

print('止损35笔 持有不卖的后续路径（相对卖价%）')
for k in (1, 3, 5, 10):
    vals = [v for r in out if (v := ret(r, k)) is not None]
    if vals:
        worse = sum(1 for v in vals if v < 0)
        print(f'  T+{k:<2} n={len(vals):2d} 均={statistics.mean(vals):+.2f}% 中位={statistics.median(vals):+.2f}% 仍低于卖价(卖对)={worse}')

# 分界特征: "卖对"(t5_close < 卖价) vs "卖早" 两组，比较触发时点已知特征
# 触发时可知: pnl_pct、触发时刻、大盘当日涨跌、当日振幅(day_low/high相对昨收近似用low/close)
def label(r):
    v = r.get('t5_close')
    if v is None or not r['px']: return None
    return '卖对' if v < r['px'] else '卖早'
g1 = [r for r in out if label(r) == '卖对']
g2 = [r for r in out if label(r) == '卖早']
print(f'\n按T+5结局分组: 卖对 {len(g1)} 笔, 卖早 {len(g2)} 笔, 无法判定 {len(out)-len(g1)-len(g2)}')
for name, g in [('卖对', g1), ('卖早', g2)]:
    if not g: continue
    pnls = [r['pnl_pct'] for r in g]
    times = [r['time'] for r in g]
    early = sum(1 for t in times if t < '10:00')
    mkts = [r['mkt_ret'] for r in g if r.get('mkt_ret') is not None]
    # 触发时已深水位
    deep = sum(1 for p in pnls if p <= -9)
    print(f'  {name}: 触发pnl均={statistics.mean(pnls):.1f}% 深度<=-9%占{deep}/{len(g)} | 早盘(<10:00)触发{early}/{len(g)} | 当日大盘均={statistics.mean(mkts) if mkts else 0:+.2f}%')

# 上界核算: 完美研判=每笔选 max(立即卖, 持有到T+5) 的较优者; 规则版=立即卖
import math
upl = []
for r in out:
    v5 = ret(r, 5)
    if v5 is None: continue
    # 完美决策: 若 t5 后仍低于卖价 -> 立即卖(0差); 否则持有到T+5, 收益差 = t5_close/px - 1
    upl.append(max(0.0, v5))
print(f'\n上界: 完美研判比规则版每笔平均多卖 {statistics.mean(upl):+.2f}% (T+5口径, n={len(upl)})')
# 但持有承担的下行风险: 全部持有 vs 全部即卖 的分布
v5s = [v for r in out if (v := ret(r, 5)) is not None]
worst = sorted(v5s)[:5]
print(f'  全部持有T+5最差5笔: {[f"{v:+.1f}" for v in worst]}  (即卖=0 为基准)')

# 按账户看止损笔数集中在哪
import collections
c = collections.Counter(r['aid'] for r in out)
print('\n止损笔数按账户:', dict(c))