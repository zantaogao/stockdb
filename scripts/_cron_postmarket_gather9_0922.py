# -*- coding: utf-8 -*-
import duckdb, sqlite3, os, json
os.chdir('/Users/zantao/.hermes/stockdb')
sc = sqlite3.connect('signals.db')

print('=== ic_window 近14行关键列（signal_date, ic_center_w10, ic_dual_w10, ic_cmmr_w10, ic_cmmrf_w10, ic_3f_w10, fwd10_top系列）===')
for r in sc.execute("""SELECT signal_date, ic_center_w10, ic_dual_w10, ic_cmmr_w10, ic_cmmrf_w10, ic_3f_w10,
 fwd10_top_center, fwd10_top_dual, fwd10_top_cmmr, fwd10_top_cmmrf, fwd10_top_3f
 FROM ic_window ORDER BY signal_date DESC LIMIT 14""").fetchall():
    print(r[0], ['%.3f' % v if v is not None else 'NA' for v in r[1:]])

print('=== fusion_center_signals 结构+最新 ===')
print([x[1] for x in sc.execute('PRAGMA table_info(fusion_center_signals)').fetchall()])
print(sc.execute("SELECT MAX(date) FROM fusion_center_signals").fetchone())

print('=== 0921 各榜Top10 定义与重合（draft口径：signal_history fusion_score / cmmr表 / center_dual）===')
f3 = [r[0] for r in sc.execute("SELECT stock_code FROM signal_history WHERE REPLACE(date,'-','')='20260921' ORDER BY fusion_score DESC LIMIT 10").fetchall()]
print('三模型0921 top10:', f3)
cm = [r[0] for r in sc.execute("SELECT ts_code FROM cmmr_top10_ic_daily ORDER BY date DESC LIMIT 10") .fetchall()] if False else None
# cmmr 榜单来源：opinion_universe.json 的 top10（draft同源）
uni = json.load(open('analysis/opinion_universe.json'))
lists = {k: [x['code'] if isinstance(x,dict) else x for x in v] for k,v in uni['top10'].items()}
import itertools
for a,b in itertools.combinations(lists,2):
    ov = set(lists[a]) & set(lists[b])
    if ov: print('重合', a, b, len(ov), sorted(ov))

print('=== 0921 榜内票 5日/10日涨幅与今日涨跌（用于明日预案逐票）===')
td = duckdb.connect('tushare.db', read_only=True)
allc = sorted({c[:6] for v in lists.values() for c in v})
for c6 in allc:
    pass

print('=== 主账户同板块：榜内票的行业 ===')
sb = {r[0]: (r[1], r[2]) for r in td.execute("SELECT ts_code, name, industry FROM stock_basic").fetchall()} if True else {}
q = "SELECT ts_code, name, industry FROM stock_basic WHERE ts_code LIKE ? OR ts_code LIKE ?"
inds = {}
for c6 in allc:
    for suf in ['.SZ','.SH','.BJ']:
        try:
            r = td.execute("SELECT name, industry FROM stock_basic WHERE ts_code=?", [c6+suf]).fetchone()
        except Exception:
            r = None
        if r: inds[c6] = r; break
print(json.dumps(inds, ensure_ascii=False))
