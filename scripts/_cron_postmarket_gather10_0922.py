# -*- coding: utf-8 -*-
import duckdb, sqlite3, os, statistics
os.chdir('/Users/zantao/.hermes/stockdb')
sc = sqlite3.connect('signals.db')
td = duckdb.connect('tushare.db', read_only=True)

print('=== 中枢版 0921 榜单（fusion_center_signals）===')
for r in sc.execute("SELECT stock_code, stock_name, score, rank_pct FROM fusion_center_signals WHERE date='20260921' ORDER BY score ASC LIMIT 12").fetchall():
    print(r)
print('signal取值分布:', sc.execute("SELECT signal, COUNT(*) FROM fusion_center_signals WHERE date='20260921' GROUP BY 1").fetchall())

print('=== 成交额对比：修复日 vs 下跌日 ===')
for r in td.execute("SELECT trade_date, SUM(amount)/1e8 FROM daily WHERE trade_date>='20260911' GROUP BY 1 ORDER BY 1").fetchall():
    print(r[0], '%.0f亿' % r[1])

print('=== 缺口票20日日线（日期 收盘 涨跌% 量/前5日均量）===')
codes = ['603811.SH','600276.SH','002821.SZ','601615.SH','301093.SZ','600076.SH','301283.SZ','001332.SZ','603966.SH','300658.SZ','688191.SH','300543.SZ','002402.SZ','300812.SZ','002674.SZ','688063.SH','688776.SH','688155.SH','300724.SZ','688275.SH','601778.SH','300982.SZ','688355.SH','600892.SH','002742.SZ','000702.SZ','002686.SZ','002769.SZ','000890.SZ','002244.SZ','000710.SZ','603089.SH','001299.SZ','300774.SZ','603758.SH','603036.SH','001366.SZ','600749.SH','603958.SH','605068.SH','605286.SH','600066.SH','300935.SZ','300779.SZ','003001.SZ','688793.SH','603382.SH','688217.SH','301130.SZ','001277.SZ']
for ts in codes:
    rows = td.execute("SELECT trade_date, close, pct_chg, vol FROM daily WHERE ts_code=? AND trade_date>='20260815' ORDER BY trade_date", [ts]).fetchall()
    if not rows: print(ts, '无数据'); continue
    out=[]
    for i,r in enumerate(rows):
        v5 = statistics.fmean([x[3] for x in rows[max(0,i-5):i]]) if i>0 else None
        ratio = r[3]/v5 if v5 else 0
        out.append('%s:%.2f/%+.1f%%/%.1fx' % (r[0][4:], r[1], r[2], ratio))
    # 只打印近12日
    print(ts, ' '.join(out[-12:]))
