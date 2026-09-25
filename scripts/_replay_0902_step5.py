# 回放V5: 稳健性核查——样本集中度 + 触发时刻分钟路径(8/25后)
import json, statistics, collections
import duckdb

out = json.load(open('analysis/replay_paths_0902.json'))
d = duckdb.connect('/Users/zantao/.hermes/stockdb/tdx_archive.db', read_only=True)

# 1) 事件集中度: 8/31 暴跌次日占多少
cnt = collections.Counter(str(r['date']) for r in out)
print('事件逐日分布:', dict(sorted(cnt.items())))

# 2) T+1 全样本(33笔)按日分组——是否被 8/25-26 反弹日主导
byday = collections.defaultdict(list)
for r in out:
    if r.get('p_next_close') and r['px']:
        byday[str(r['date'])].append((r['p_next_close']/r['px']-1)*100)
for day, v in sorted(byday.items()):
    print(f'  {day}: n={len(v):2d} T+1均={statistics.mean(v):+.2f}%')
# 剔除最大单日后的T+1
allv = [(str(r['date']), (r['p_next_close']/r['px']-1)*100) for r in out if r.get('p_next_close') and r['px']]
big = max(byday, key=lambda k: len(byday[k]))
rest = [v for dd, v in allv if dd != big]
print(f'剔除{big}({len(byday[big])}笔)后 T+1均={statistics.mean(rest):+.2f}% 中位={statistics.median(rest):+.2f}% n={len(rest)}')

# 3) 8/25+ 的止损触发: 触发后15/30/60分钟路径（分钟级，验证"晚点卖"在日内是否成立）
late = [r for r in out if str(r['date']).replace('-','') >= '20260825']
print(f'\n分钟可查事件(8/25+): {len(late)} 笔')
for off in (15, 30, 60):
    vals = []
    for r in late:
        nd = int(str(r['date']).replace('-',''))
        hh, mm = (r['time'] or '09:35').split(':')[:2]
        tm0 = int(hh)*60+int(mm)
        q = d.execute("SELECT close FROM min1_archive WHERE date=? AND code=? AND tm=? ORDER BY tm LIMIT 1",
                      [nd, r['code'], tm0]).fetchone()
        r2 = d.execute("SELECT close FROM min1_archive WHERE date=? AND code=? AND tm>=? ORDER BY tm LIMIT 1",
                       [nd, r['code'], tm0+off]).fetchone()
        if q and r2:
            vals.append((r2[0]/q[0]-1)*100)
    if vals:
        up = sum(1 for v in vals if v > 0)
        print(f'  触发后+{off}min: n={len(vals)} 占优(更高)={up} 均={statistics.mean(vals):+.2f}% 中位={statistics.median(vals):+.2f}%')