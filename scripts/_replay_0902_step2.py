# 回放V2: 止损类卖出事件的"如果晚点卖"反事实路径
# 规则版=触发时点价; 备选=+15min/+30min/当日尾盘/次日开盘/次日收盘/T+2收盘
# 覆盖: 分钟级仅 20260825+ 全量; 更早事件退化为日线级(次日开盘/收盘/T+2收盘)
import sqlite3, duckdb, json, statistics

events = json.load(open('analysis/replay_events_0902.json'))
stops = [e for e in events if e['pnl_pct'] is not None and e['pnl_pct'] <= -6]
print('止损类事件:', len(stops))

def norm_date(s): return str(s).replace('-', '')

d = duckdb.connect('/Users/zantao/.hermes/stockdb/tdx_archive.db', read_only=True)
ts = duckdb.connect('/Users/zantao/.hermes/stockdb/tushare.db', read_only=True)

# 交易日历（tushare.db stock_daily: date 列混格式，REPLACE 归一）
cal = [r[0] for r in ts.execute(
    "SELECT DISTINCT strftime(date,'%Y%m%d') dd FROM stock_daily WHERE dd>='20260701' ORDER BY dd").fetchall()]
def next_nds(nd, n):
    if nd not in cal: return []
    i = cal.index(nd)
    return [cal[i+k] for k in range(1, n+1) if i+k < len(cal)]

def min_px(code, nd, target_min):
    """分钟库: nd 日 >=target_min 的第一根分钟 close"""
    r = d.execute("SELECT close FROM min1_archive WHERE date=? AND code=? AND tm>=? ORDER BY tm LIMIT 1",
                  [int(nd), code, target_min]).fetchone()
    return r[0] if r else None

def daily_px(code, nd, col):
    r = ts.execute(f"SELECT {col} FROM stock_daily WHERE stock_code=? AND strftime(date,'%Y%m%d')=?",
                   [code, nd]).fetchone()
    return r[0] if r else None

# 提速: 一次性物化所需子集（8月+ 全部个股日线）
need_codes = sorted({e['code'] for e in stops} | {'000001'})
ts.execute("CREATE TEMP TABLE dsub AS SELECT stock_code, strftime(date,'%Y%m%d') nd, open, high, low, close, change_pct FROM stock_daily WHERE strftime(date,'%Y%m%d')>='20260720'")
def dpx(code, nd, col):
    r = ts.execute(f"SELECT {col} FROM dsub WHERE stock_code=? AND nd=?", [code, nd]).fetchone()
    return r[0] if r else None

results = []
for e in stops:
    nd = norm_date(e['date']); code = e['code']; px = e['px']
    hh, mm = (e['time'] or '09:35:00').split(':')[:2]
    trig_min = int(hh)*60 + int(mm)
    nxt = next_nds(nd, 2)
    row = dict(e)
    row['p_15m'] = min_px(code, nd, min(trig_min+15, 870)) if trig_min < 870 else None
    row['p_30m'] = min_px(code, nd, min(trig_min+30, 870)) if trig_min < 840 else None
    row['p_close'] = min_px(code, nd, 870)
    row['p_next_open'] = daily_px(code, nxt[0], 'open') if nxt else None
    row['p_next_close'] = daily_px(code, nxt[0], 'close') if nxt else None
    row['p_t2_close'] = daily_px(code, nxt[1], 'close') if len(nxt) > 1 else None
    row['day_low'] = daily_px(code, nd, 'low')
    row['next_low'] = daily_px(code, nxt[0], 'low') if nxt else None
    # 触发时点大盘环境: 当日上证指数涨跌幅（000001 sh 日线近似）
    row['mkt_ret'] = daily_px('000001', nd, 'change_pct')
    results.append(row)

json.dump(results, open('analysis/replay_paths_0902.json', 'w'), ensure_ascii=False)

def delta(r, k):
    v = r.get(k)
    return None if (v is None or not r['px']) else (v/r['px']-1)*100

print()
print('相对实际卖价的价差（正=晚卖更划算=规则卖早了；负=规则卖对了）')
for k in ['p_15m','p_30m','p_close','p_next_open','p_next_close','p_t2_close']:
    vals = [v for r in results if (v := delta(r, k)) is not None]
    if not vals: continue
    win = sum(1 for v in vals if v > 0)
    print(f'{k:12s} n={len(vals):3d} 晚卖占优={win/len(vals)*100:5.1f}% 均差={statistics.mean(vals):+.2f}% 中位={statistics.median(vals):+.2f}%')

lows = [x for r in results for x in [r['day_low'], r['next_low']] if x]
vals = [(min([r['day_low'], r['next_low']])/r['px']-1)*100 for r in results
        if r['px'] and r['day_low'] and r['next_low']]
if vals:
    print(f'\n完美后视上界(触发后2日最低价 vs 实际卖价) n={len(vals)} 均={statistics.mean(vals):+.2f}% 中位={statistics.median(vals):+.2f}%')

# 按触发时点分组: 早盘(<=10:00) vs 尾盘确认(>=14:30)
for label, cond in [('早盘触发(<10:00)', lambda r: r['time'] < '10:00'),
                    ('盘中/尾盘(>=10:00)', lambda r: r['time'] >= '10:00')]:
    sub = [r for r in results if cond(r)]
    if not sub: continue
    for k in ['p_close','p_next_close']:
        vals = [v for r in sub if (v := delta(r, k)) is not None]
        if vals:
            win = sum(1 for v in vals if v > 0)
            print(f'{label} {k}: n={len(vals)} 晚卖占优={win/len(vals)*100:.0f}% 均差={statistics.mean(vals):+.2f}%')