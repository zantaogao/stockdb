# -*- coding: utf-8 -*-
# 补取：0918 各榜 top10 全名单 + 次日(0921)表现 + signal_history 原始复算IC + 0921各榜重合
import duckdb, sqlite3, os, json
os.chdir('/Users/zantao/.hermes/stockdb')
sc = sqlite3.connect('signals.db')
td = duckdb.connect('tushare.db', read_only=True)

print('===== signal_history 字段 =====')
print([r[1] for r in sc.execute('PRAGMA table_info(signal_history)').fetchall()])

# 0918 三模型融合 top10（signal_history 最新有分日）
print('===== 0918 fusion3f top10 with 0921 perf =====')
rows = sc.execute("SELECT stock_code, fusion_score FROM signal_history WHERE REPLACE(date,'-','')='20260918' ORDER BY fusion_score DESC LIMIT 10").fetchall()
codes = [r[0] if '.' in r[0] else r[0]+'.SZ' for r in rows]
ph = ','.join(['?']*len(codes))
perf = {r[0]: r[1] for r in td.execute(f"SELECT ts_code, pct_chg FROM daily WHERE trade_date='20260921' AND ts_code IN ({ph})", codes).fetchall()}
name = {r[0]: r[1] for r in td.execute("SELECT ts_code, name FROM stock_basic").fetchall()}
for (c, s), tc in zip(rows, codes):
    print(c, name.get(tc, tc), 'score', s, '0921涨跌', perf.get(tc, '停牌/无数据'))
avg = [float(perf[t]) for t in codes if t in perf]
zz = td.execute("SELECT pct_chg FROM index_daily_raw WHERE ts_code='000852.SH' AND trade_date='20260921'").fetchone()
print('top10等权均值 %.2f vs 中证1000 %.2f 超额 %+.2f' % (sum(avg)/len(avg), float(zz[0]), sum(avg)/len(avg)-float(zz[0])))

# 近4信号日 fusion3f top10 次日超额（自己复算）
print('===== 近4信号日 fusion3f top10 次日超额（原始复算） =====')
dates = [r[0] for r in sc.execute("SELECT DISTINCT REPLACE(date,'-','') FROM signal_history WHERE fusion_score IS NOT NULL ORDER BY 1 DESC LIMIT 5").fetchall()][1:5]
for d in dates:
    rows = sc.execute("SELECT stock_code FROM signal_history WHERE REPLACE(date,'-','')=? ORDER BY fusion_score DESC LIMIT 10", [d]).fetchall()
    codes = [r[0] if '.' in r[0] else r[0]+'.SZ' for r in rows]
    nxt = td.execute("SELECT MIN(trade_date) FROM daily WHERE trade_date > ?", [d]).fetchone()[0]
    ph = ','.join(['?']*len(codes))
    pr = td.execute(f"SELECT AVG(pct_chg), COUNT(*) FROM daily WHERE trade_date=? AND ts_code IN ({ph})", [nxt]+codes).fetchone()
    zi = td.execute("SELECT pct_chg FROM index_daily_raw WHERE ts_code='000852.SH' AND trade_date=?", [nxt]).fetchone()
    if pr[0] is not None and zi:
        print(d, '->', nxt, 'top10均值 %.2f 基准 %.2f 超额 %+.2f (有数据%d只)' % (float(pr[0]), float(zi[0]), float(pr[0])-float(zi[0]), pr[1]))
    else:
        print(d, '->', nxt, '无次日数据(明日)')

# 0921 各榜重合
uni = json.load(open('analysis/opinion_universe.json'))
print('===== universe.json 键 =====')
print(list(uni.keys()))
for k, v in uni.items():
    if isinstance(v, dict): print(k, list(v.keys())[:8])
    elif isinstance(v, list): print(k, 'list', len(v), v[:2])

# CMMR/center 0921 top10 重合数（从表直接取）
cm = [r[0] for r in sc.execute("SELECT ts_code FROM cmmr_scores WHERE score_date=(SELECT MAX(score_date) FROM cmmr_scores) ORDER BY score DESC LIMIT 10").fetchall()]
cf = [r[0] for r in sc.execute("SELECT ts_code FROM cmmr_fusion_scores WHERE score_date=(SELECT MAX(score_date) FROM cmmr_fusion_scores) ORDER BY score DESC LIMIT 10").fetchall()]
cd_ = [r[0] for r in sc.execute("SELECT ts_code FROM center_dual_scores WHERE score_date=(SELECT MAX(score_date) FROM center_dual_scores) ORDER BY score DESC LIMIT 10").fetchall()]
f3 = ['688679.SH','301575.SZ','301590.SZ','301233.SZ','688081.SH','300970.SZ','301085.SZ','688720.SH','001317.SZ','300912.SZ']
import itertools
sets = {'fusion3f': set(f3), 'cmmr': set(cm), 'cmmr_fusion': set(cf), 'center_dual': set(cd_)}
for a, b in itertools.combinations(sets, 2):
    print('重合', a, b, len(sets[a] & sets[b]), sorted(sets[a] & sets[b]))
