# -*- coding: utf-8 -*-
import duckdb, os, subprocess
os.chdir('/Users/zantao/.hermes/stockdb')
# NAS 备份最近成功/失败带时间戳
out = subprocess.run("grep -nE '✅ NAS 备份完成|❌ SSH 连接失败|===== NAS' ~/.hermes/logs/nas_backup.log | tail -6", shell=True, capture_output=True, text=True).stdout
print(out)
td = duckdb.connect('tushare.db', read_only=True)
print('=== 0918/0921 行业日均涨跌（daily join stock_basic，含量比）===')
for d in ['20260918','20260921']:
    rows = td.execute("""
      SELECT b.industry, AVG(pct_chg) p, COUNT(*) n FROM daily d JOIN stock_basic b ON d.ts_code=b.ts_code
      WHERE d.trade_date=? AND b.industry IS NOT NULL GROUP BY 1 HAVING n>=8 ORDER BY p DESC""", [d]).fetchall()
    print(d, 'TOP6', [(n, round(p,2)) for n,p,_ in rows[:6]])
    print(d, 'BOT6', [(n, round(p,2)) for n,p,_ in rows[-6:]])
    for t in ('半导体','元器件','全国地产','生物制药','化学制药'):
        v = [round(p,2) for n,p,_ in rows if n==t]
        if v: print('   ', d, t, v)
