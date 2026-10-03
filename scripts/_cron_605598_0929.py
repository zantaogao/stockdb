# 605598 上海港湾 近况: 持仓状态+价格走势+评分链
import duckdb, sqlite3
db = duckdb.connect('/Users/zantao/.hermes/stockdb/tushare.db', read_only=True)
print('--- 近20日日线 ---')
print(db.execute("""SELECT trade_date,close,pct_chg,ROUND(amount/1e4,0) amt_万 FROM daily
WHERE ts_code='605598.SH' AND trade_date>='20260901' ORDER BY trade_date""").df().to_string(index=False))
print('--- 月度 ---')
print(db.execute("""SELECT substr(trade_date,1,6) ym, MIN(low) lo, MAX(high) hi,
MIN_BY(close,trade_date) f, MAX_BY(close,trade_date) m FROM daily
WHERE ts_code='605598.SH' AND trade_date>='20260601' GROUP BY 1 ORDER BY 1""").df().to_string(index=False))
print('--- 估值 ---')
print(db.execute("SELECT pe_ttm,pb,ROUND(total_mv/10000,0) mv_yi FROM daily_basic WHERE ts_code='605598.SH' AND trade_date=(SELECT MAX(trade_date) FROM daily_basic)").df().to_string(index=False))

led = sqlite3.connect('/Users/zantao/.hermes/stockdb/ledger.db')
print('--- 持仓(ledger最新) ---')
for acc in led.execute("SELECT DISTINCT account FROM holdings").fetchall():
    rows = led.execute("SELECT account,stock_code,stock_name,volume,cost_price,update_time FROM holdings WHERE stock_code LIKE '%605598%' AND account=?", (acc[0],)).fetchall()
    if rows: print(rows)
print('--- 605598 全部成交流水 ---')
try:
    for r in led.execute("SELECT trade_time,account,action,price,volume,amount,pnl,pnl_pct,reason FROM trade_log WHERE stock_code LIKE '%605598%' ORDER BY trade_time").fetchall():
        print(r)
except Exception as e: print('err',e)

sig = sqlite3.connect('/Users/zantao/.hermes/stockdb/signals.db')
print('--- 评分链最新 ---')
print('signal_history:', sig.execute("SELECT date,fusion_score,final_score,cmmr_score,reg10,reg20,reg40 FROM signal_history WHERE stock_code='605598' ORDER BY date DESC LIMIT 3").fetchall())
print('fusion_3f:', sig.execute("SELECT date,fusion_3f_score,signal FROM fusion_3f_signals WHERE stock_code='605598' ORDER BY date DESC LIMIT 3").fetchall())
