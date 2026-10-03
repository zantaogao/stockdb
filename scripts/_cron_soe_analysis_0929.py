# 0929 程福波文章关联央企标的: 估值(最新交易日 daily_basic) + 5/20日动量
import duckdb
db = duckdb.connect('/Users/zantao/.hermes/stockdb/tushare.db', read_only=True)
LAST = db.execute("SELECT MAX(trade_date) FROM daily").fetchone()[0]

GROUPS = {
  '中国宝武系(重组样板)': [('600019.SH','宝钢股份'),('600581.SH','宝钛股份'),('601969.SH','中国海油? N/A')],
  '中国船舶系': [('600150.SH','中国船舶'),('600685.SH','中船防务'),('600764.SH','中国海防'),('688426.SH','康众医疗? N/A')],
  '中远海运系': [('601919.SH','中远海控'),('600026.SH','中远海能'),('600428.SH','中远海特'),('601866.SH','中远海发')],
  '中国中车系': [('601766.SH','中国中车'),('688187.SH','时代电气')],
  '中国稀土集团系': [('000831.SZ','中国稀土'),('600392.SH','盛和资源'),('600259.SH','广晟有色')],
  '长安/招商系': [('000625.SZ','长安汽车'),('601872.SH','招商轮船')],
  'CETC系(军工电子/芯片)': [('600862.SH','中航高科'),('600990.SH','四创电子'),('688270.SH','臻镭科技')],
  '航空工业系': [('600760.SH','中航沈飞'),('600038.SH','中直股份'),('000768.SZ','中航西飞')],
  '航天系': [('600151.SH','航天机电'),('600879.SH','航天电子'),('002025.SZ','航天电器')],
  '量子赛道': [('688027.SH','国盾量子'),('002413.SZ','雷科防务? N/A')],
  '核聚变赛道': [('688122.SH','西部超导'),('600363.SH','联创光电'),('600522.SH','中天科技? N/A')],
  '生物制造赛道': [('600298.SH','安琪酵母'),('300009.SZ','安科生物? N/A')],
  'AI央企甲方': [('600941.SH','中国移动'),('601728.SH','中国电信'),('600050.SH','中国联通')],
  '工业软件/工业母机攻关': [('688777.SH','中控技术? N/A'),('688188.SH','柏楚电子'),('000425.SZ','徐工机械')],
}
GROUPS = {g: [(c,n) for c,n in lst if 'N/A' not in n] for g,lst in GROUPS.items()}
codes = sorted({c for lst in GROUPS.values() for c,_ in lst})
cl = ','.join(f"'{c}'" for c in codes)

base = db.execute(f"""
SELECT d.ts_code, b.name, d.close AS px, db.pe_ttm AS pe, db.pb AS pb, ROUND(db.total_mv/10000,0) AS mv_yi
FROM daily d JOIN stock_basic b ON d.ts_code=b.ts_code
LEFT JOIN daily_basic db ON db.ts_code=d.ts_code AND db.trade_date=d.trade_date
WHERE d.ts_code IN ({cl}) AND d.trade_date='{LAST}'
""").df()

mom = db.execute(f"""
WITH r AS (SELECT ts_code, trade_date, close,
  LAG(close,5) OVER(PARTITION BY ts_code ORDER BY trade_date) c5,
  LAG(close,20) OVER(PARTITION BY ts_code ORDER BY trade_date) c20
  FROM daily WHERE ts_code IN ({cl}))
SELECT ts_code, ROUND((close/c5-1)*100,1) AS chg5, ROUND((close/c20-1)*100,1) AS chg20
FROM r WHERE trade_date='{LAST}'
""").df()

m = base.merge(mom, on='ts_code', how='left')
print('数据日:', LAST)
idx = db.execute("SELECT close FROM index_daily WHERE index_code='000852.SH' ORDER BY date DESC LIMIT 1").fetchone()
for g, lst in GROUPS.items():
    print('\n##', g)
    for c, n in lst:
        row = m[m['ts_code']==c]
        if len(row)==0:
            print(f'  {c} {n}: 库内无此码/无行情'); continue
        r = row.iloc[0]
        def f(x):
            try:
                import math
                if x is None or (isinstance(x,float) and math.isnan(x)): return '—'
                return f'{x:g}'
            except: return str(x)
        print(f"  {c} {r['name']}: 收{f(r['px'])} PE{f(r['pe'])} PB{f(r['pb'])} 总市值{f(r['mv_yi'])}亿 | 5日{f(r['chg5'])}% 20日{f(r['chg20'])}%")
