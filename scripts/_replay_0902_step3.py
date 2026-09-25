# 回放V3: 止损触发35笔逐笔明细 + 环境分组（哪类触发卖对了/卖早了）
# 关键区分: p_close是"卖价->收盘价"的时点差, 含持有beta; 研判空间=完美后视与规则版的差
import json, sqlite3, statistics

rows = json.load(open('analysis/replay_paths_0902.json'))
ts = None

# 逐票次日实际收益 vs 卖价 (即"不卖会怎样")
print('%-10s %-8s %-6s %8s %7s %7s %7s %7s' % ('date','aid','code','pnl%','mkt%','->close','->次日','2日最低'))
for r in sorted(rows, key=lambda x: (x['date'], x['time'])):
    def d(k):
        v = r.get(k)
        return f'{(v/r["px"]-1)*100:+.1f}' if v else '  n/a'
    lows = [x for x in [r.get('day_low'), r.get('next_low')] if x]
    low2 = f'{(min(lows)/r["px"]-1)*100:+.1f}' if lows and r['px'] else 'n/a'
    mkt = f"{r['mkt_ret']:+.1f}" if r.get('mkt_ret') is not None else 'n/a'
    print('%-10s %-8s %-6s %8.1f %7s %7s %7s %7s' % (
        r['date'], r['aid'], r['code'], r['pnl_pct'], mkt,
        d('p_close'), d('p_next_close'), low2))

# 分环境: 大盘暴跌日 vs 普通日
import collections
def grp(r):
    m = r.get('mkt_ret')
    if m is None: return '无大盘数据'
    return '大盘日(<-1%)' if m < -1 else ('大盘弱(0~-1%)' if m < 0 else '大盘红(>0%)')
for g in ['大盘红(>0%)', '大盘弱(0~-1%)', '大盘日(<-1%)']:
    sub = [r for r in rows if grp(r) == g]
    if not sub: continue
    v1 = [(r['p_close']/r['px']-1)*100 for r in sub if r.get('p_close')]
    v2 = [(r['p_next_close']/r['px']-1)*100 for r in sub if r.get('p_next_close')]
    v3 = [(min([x for x in [r.get('day_low'), r.get('next_low')] if x])/r['px']-1)*100
          for r in sub if r.get('day_low') and r.get('next_low')]
    # 卖对比例 = 2日最低价比卖价低（即规则卖价高于后2日最低=卖得不算亏）—— 用"次日收盘仍低于卖价"= 卖对
    sold_right = sum(1 for r in sub if r.get('p_next_close') and r['p_next_close'] < r['px'])
    print(f'{g}: n={len(sub)} 卖对(次日收盘<卖价)={sold_right}/{len([r for r in sub if r.get("p_next_close")])} '
          f'->close均={statistics.mean(v1) if v1 else 0:+.2f} ->次日均={statistics.mean(v2) if v2 else 0:+.2f} '
          f'完美后视均={statistics.mean(v3) if v3 else 0:+.2f}')

# 按触发类型
def tp(r):
    p = r['pnl_pct']
    return 'R5硬' if p <= -12 else ('加速' if p <= -9 else 'R7浮亏')
for g in ['R5硬', '加速', 'R7浮亏']:
    sub = [r for r in rows if tp(r) == g]
    if not sub: continue
    sold_right = sum(1 for r in sub if r.get('p_next_close') and r['p_next_close'] < r['px'])
    n_ok = len([r for r in sub if r.get('p_next_close')])
    v2 = [(r['p_next_close']/r['px']-1)*100 for r in sub if r.get('p_next_close')]
    print(f'{g}: n={len(sub)} 卖对率={sold_right}/{n_ok} ->次日均={statistics.mean(v2) if v2 else 0:+.2f}')