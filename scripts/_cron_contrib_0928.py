import duckdb, sqlite3
l = sqlite3.connect('/Users/zantao/.hermes/stockdb/ledger.db')
holds = l.execute("SELECT code,name,avg_cost,shares,latest_price,pnl_pct,target_price,stop_loss,buy_date FROM holdings ORDER BY pnl_pct").fetchall()
d = duckdb.connect('/Users/zantao/.hermes/stockdb/tushare.db', read_only=True)
tot = 0
rows = []
for code,name,cost,sh,px,pnl,tp,sl,bd in holds:
    ts = code + ('.SH' if code.startswith('6') else '.SZ')
    prev = d.execute("SELECT close,pct_chg,vol FROM daily WHERE ts_code=? AND trade_date<'20260928' ORDER BY trade_date DESC LIMIT 1", [ts]).fetchone()
    today = d.execute("SELECT pct_chg,vol,high,low FROM daily WHERE ts_code=? AND trade_date='20260928'", [ts]).fetchone()
    contrib = sh*(today[3]+ (0))*0  # placeholder
    diff = today[3] - prev[2] if False else None
    # contribution = shares * (close_today - close_prev); prev close:
    contrib = sh*( (px if False else 0) )
    rows.append((code,name,cost,sh,px,pnl,tp,sl,bd,prev[0],today[0],prev[1]))
for r in rows:
    code,name,cost,sh,px,pnl,tp,sl,bd,pclose,tpct,pctg = r
    # today close from daily today[?] — recompute simply: close_today = pclose*(1+tpct/100)
    close_t = pclose*(1+tpct/100)
    contrib = sh*(close_t-pclose)
    tot += contrib
    print(code,name,f'sh={sh} prev={pclose} today%={tpct:.2f} contrib={contrib:+.0f} pnl%={pnl} stop={sl} tp={tp}')
print('TOTAL today contribution ≈', round(tot))
# 跳空/跌停判断
print('---今日跳空低开与跌停判断---')
for r in rows:
    code,name = r[0],r[1]
    ts = code + ('.SH' if code.startswith('6') else '.SZ')
    o = d.execute("SELECT open,low,close FROM daily WHERE ts_code=? AND trade_date='20260928'",[ts]).fetchone()
    gap = (o[0]/r[9]-1)*100
    print(code,name,f'gap_open={gap:+.1f}% low_vs_prevclose={(o[1]/r[9]-1)*100:+.1f}%')
d.close()
