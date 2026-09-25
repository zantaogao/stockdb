# -*- coding: utf-8 -*-
import duckdb, sqlite3, os, statistics
os.chdir('/Users/zantao/.hermes/stockdb')
td = duckdb.connect('tushare.db', read_only=True)
sc = sqlite3.connect('signals.db')

# 0918 各榜 top10 的今日(0921)单日收益 vs 中证1000 +1.02%
zi = 1.0215
def top10(tbl, col, d, asc=False, extra=''):
    order = 'ASC' if asc else 'DESC'
    return [r[0] for r in sc.execute(f"SELECT stock_code, {col} v FROM {tbl} WHERE REPLACE(date,'-','')='{d}' {extra} AND {col} IS NOT NULL ORDER BY v {order} LIMIT 10").fetchall()]

def perf(codes, d0, d1):
    # d0收盘 -> d1收盘 收益
    outs=[]
    for c6 in codes:
        suf = ('.SZ' if c6[0] in '03' else '.SH') if not c6[0]=='6' else '.SH'
        suf = '.SH' if c6[0]=='6' else '.SZ'
        r = td.execute("SELECT a.close, b.close FROM (SELECT close FROM daily WHERE ts_code=? AND trade_date<=? ORDER BY trade_date DESC LIMIT 1) a, (SELECT close FROM daily WHERE ts_code=? AND trade_date<=? ORDER BY trade_date DESC LIMIT 1) b", [c6+suf, d0, c6+suf, d1]).fetchone()
        if r and r[0]: outs.append((r[1]/r[0]-1)*100)
    return (statistics.fmean(outs) if outs else None), len(outs)

boards = {
 '三模型融合': top10('signal_history','fusion_score','20260918'),
 'CMMR独立': top10('signal_history','cmmr_score','20260918'),
 'CMMR+融合': top10('signal_history','fusion_score_cmmr','20260918'),
}
boards['中枢版'] = top10('fusion_center_signals','score','20260918',asc=True)

print('0918榜 -> 0921单日 等权收益 vs 中证1000 +1.02%:')
for k, v in boards.items():
    if not v: print(k, '无榜'); continue
    m, n = perf(v, '20260918', '20260921')
    print(k, 'n=%d 均%.2f%% 超额%.2fpp' % (n, m, m-zi), v)

# 中枢 top15% 名单重叠（0918 vs 0921 强买池）
a = set(r[0] for r in sc.execute("SELECT stock_code FROM fusion_center_signals WHERE date='20260918' AND signal='强买'").fetchall())
b = set(r[0] for r in sc.execute("SELECT stock_code FROM fusion_center_signals WHERE date='20260921' AND signal='强买'").fetchall())
ov = len(a & b)
print('强买池重叠 0918∩0921:', ov, '/', len(b), '= %.1f%% (随机基准≈池占比)' % (ov/max(len(b),1)*100), '池大小', len(a))

# 0921 中枢榜 与 0918 中枢榜 交集
a2 = set(r[0] for r in sc.execute("SELECT stock_code FROM fusion_center_signals WHERE date='20260918' ORDER BY score ASC LIMIT 10").fetchall())
b2 = set(r[0] for r in sc.execute("SELECT stock_code FROM fusion_center_signals WHERE date='20260921' ORDER BY score ASC LIMIT 10").fetchall())
print('中枢top10两日交集:', sorted(a2 & b2))
# 中枢/双榜 0921 各票最新日线（g4是0918口径，这里补0921关键数）
codes = ['600527','603363','300846','600830','300324','300935','002463','603220','300501','001269',
         '688377','603585','603811','300881','300970','300854','600076','300651','603190','301590',
         '300876','301163','300949','603214','600668',
         '000017','000430','000712','000735','001296','002017','002072','002084','002104','002165',
         '002144','301167','300844','301037','002858','300621','688681','301006',
         '001216','600825','603958','688356','600103','603090','301237','000711','000635']
for c6 in codes:
    suf = '.SH' if c6[0]=='6' else '.SZ'
    rows = td.execute("SELECT trade_date, close, pct_chg, vol FROM daily WHERE ts_code=? ORDER BY trade_date DESC LIMIT 21", [c6+suf]).fetchall()
    if not rows: print(c6, '无数据'); continue
    rows = list(reversed(rows))
    closes = [r[1] for r in rows]
    last = closes[-1]
    ma20 = statistics.fmean(closes[-20:])
    hi20, lo20 = max(closes), min(closes)
    g5 = (last/closes[-6]-1)*100 if len(closes)>5 else None
    # 布林位置
    sd = statistics.pstdev(closes[-20:]); 
    bl = (last-(ma20-2*sd))/(4*sd)*100 if sd else None
    consec = 0
    for r in reversed(rows):
        v = r[2]
        if consec==0 and v<0: consec=-1
        elif consec==0 and v>0: consec=1
        elif consec>0 and v>0: consec+=1
        elif consec<0 and v<0: consec-=1
        else: break
    v5 = statistics.fmean([r[3] for r in rows[-6:-1]])
    print(c6, rows[-1][0][4:], '收%.2f 5日%+.1f%% 偏MA20%+.1f%% 布林%.0f%% 距20高%.1f%% 距20低%+.1f%% 连%+d 今量%.1fx' % (
        last, g5 or 0, (last/ma20-1)*100, bl if bl is not None else -999,
        (last/hi20-1)*100, (last/lo20-1)*100, consec, rows[-1][3]/v5 if v5 else 0))
