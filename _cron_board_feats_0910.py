import duckdb, sqlite3, json, os
os.chdir(os.path.expanduser('~/.hermes/stockdb'))
tdb = duckdb.connect('tushare.db', read_only=True)

boards = {
 '三模型融合': ['001332.SZ','688191.SH','688081.SH','688377.SH','603966.SH','600076.SH','688155.SH','688399.SH','300274.SZ','002674.SZ'],
 'CMMR独立': ['603102.SH','603036.SH','000931.SZ','300935.SZ','688265.SH','600594.SH','300779.SH','603758.SH','002244.SZ','300358.SZ'],
 'CMMR+': ['688217.SH','301130.SZ','603102.SH','301167.SZ','001277.SZ','300886.SZ','688004.SH','603089.SH','603382.SH','688793.SH'],
 '中枢版': ['002133.SZ','603108.SH','600435.SH','002066.SZ','002421.SZ','688041.SH','301199.SZ','605289.SH','300403.SZ','300165.SZ'],
 '中枢版+三模型': ['001238.SZ','605598.SH','688335.SH','688776.SH','688576.SH','301005.SZ','300543.SZ','688288.SH','002402.SZ','603040.SH'],
}
allc = sorted(set(c for v in boards.values() for c in v))
res = {}
for c in allc:
    rows = tdb.execute(f"SELECT trade_date, close, vol FROM daily WHERE ts_code='{c}' ORDER BY trade_date DESC LIMIT 60").fetchall()
    if len(rows) < 25:
        res[c] = None; continue
    rows = list(reversed(rows))
    closes = [r[1] for r in rows]; vols=[r[2] for r in rows]
    close = closes[-1]
    ma20 = sum(closes[-20:])/20
    dev = (close/ma20-1)*100
    # bollinger position 20,2
    last20 = closes[-20:]
    m = sum(last20)/20
    sd = (sum((x-m)**2 for x in last20)/20)**0.5
    up, lo = m+2*sd, m-2*sd
    boll = (close-lo)/(up-lo)*100 if up>lo else 50
    chg5 = (close/closes[-6]-1)*100 if len(closes)>=6 else None
    hi20 = max(closes[-20:]); dist_hi20 = (close/hi20-1)*100
    volr = vols[-1]/(sum(vols[-6:-1])/5) if sum(vols[-6:-1])>0 else None
    res[c] = dict(close=round(close,2), dev=round(dev,1), boll=round(boll,0), chg5=round(chg5,1), dist_hi=round(dist_hi20,1), volr=round(volr,2) if volr else None)

# names
names = dict(tdb.execute("SELECT ts_code, name FROM stock_basic").fetchall())
# resonance count
from collections import Counter
cnt = Counter()
for v in boards.values():
    for c in v: cnt[c]+=1

for b, lst in boards.items():
    print('====', b)
    for c in lst:
        d = res.get(c)
        print(c, names.get(c,'?'), 'res=%d'%cnt[c], d)

print('==== main holdings stop/target dist ====')
led = sqlite3.connect('file:ledger.db?mode=ro', uri=True)
for code,name,shares,cost,px,stop,tgt in led.execute("SELECT code,name,shares,avg_cost,latest_price,stop_loss,target_price FROM holdings WHERE status='open'").fetchall():
    ds = (px/stop-1)*100 if stop else None
    dt = (tgt/px-1)*100 if tgt and px else None
    print(code, name, 'px=%.2f'%px, 'stop=%s dist_stop=%s'%(stop, ('%.1f%%'%ds) if ds is not None else '-'), 'tgt=%s dist_tgt=%s'%(tgt, ('%.1f%%'%dt) if dt is not None else '-'))

print('==== R7 浮亏 (现价<=成本*0.94) 策略账户 ====')
for code,name,shares,cost,px,pnl,acct in led.execute("SELECT h.code,h.name,h.shares,h.avg_cost,h.latest_price,h.pnl_pct,s.account_id FROM holdings h JOIN strategy_holdings s ON h.code=s.code AND h.name=s.name WHERE h.status='open'").fetchall()[:5]:
    print('sample', code,name,acct)
# fallback: strategy_holdings schema
try:
    cols=[r[1] for r in led.execute('PRAGMA table_info(strategy_holdings)')]
    print('strategy_holdings cols', cols)
except Exception as e: print(e)

print('==== rebalance dates ====')
try:
    cols=[r[1] for r in led.execute('PRAGMA table_info(strategy_accounts_meta)')]
    print('meta cols', cols)
    for r in led.execute('SELECT * FROM strategy_accounts_meta').fetchall():
        print(r[:6])
except Exception as e: print(e)
