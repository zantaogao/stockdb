import sqlite3, duckdb, json

sig = sqlite3.connect('/Users/zantao/.hermes/stockdb/signals.db')
led = sqlite3.connect('/Users/zantao/.hermes/stockdb/ledger.db')
td  = duckdb.connect('/Users/zantao/.hermes/stockdb/tushare.db', read_only=True)

# --- fusion_center top15% next-day excess on last 5 signal days ---
print("=== fusion_center top10 next-day excess ===")
rows = sig.execute("""SELECT DISTINCT date FROM fusion_center_signals
ORDER BY date DESC LIMIT 8""").fetchall()
print("center signal dates:", rows[:8])
sds = [r[0] for r in rows[:7]]
for sd in sorted(sds):
    sdn = sd.replace('-', '')
    nxt = td.execute(f"SELECT MIN(trade_date) FROM daily WHERE trade_date > '{sdn}'").fetchone()[0]
    if not nxt: continue
    tops = sig.execute("""SELECT stock_code FROM fusion_center_signals WHERE date=?
ORDER BY score DESC LIMIT 10""", (sd,)).fetchall()
    codes = [t[0] if '.' in t[0] else t[0] for t in tops]
    if not codes: print(sd, "empty"); continue
    inl = ",".join(f"'{c}'" for c in codes)
    rets = td.execute(f"""SELECT AVG(pct_chg) FROM (
      SELECT pct_chg FROM daily WHERE left(ts_code,6) IN ({inl}) AND trade_date='{nxt}')""").fetchone()
    mkt = td.execute(f"SELECT pct_chg FROM index_daily_raw WHERE ts_code='000852.SH' AND trade_date='{nxt}'").fetchone()
    if rets and rets[0] is not None and mkt:
        print(sd, f"top10 {rets[0]:+.2f}% vs 1000 {mkt[0]:+.2f}% excess {rets[0]-mkt[0]:+.2f}% n={len(codes)}")

# --- center_dual / fusion next-day top10 from ic_daily top_ret already have; check center_dual top15 overlap ---
print("\n=== center_dual_ic top_ret recent (1d) ===")
for r in sig.execute("SELECT date,top_ret,bottom_ret,ic FROM center_dual_ic_daily ORDER BY date DESC LIMIT 6").fetchall():
    print(r)

# --- main account trades today ---
print("\n=== trade_log 2026-09-16 ===")
for r in led.execute("SELECT trade_date,code,name,direction,price,quantity,amount,strategy,notes FROM trade_log WHERE trade_date LIKE '%20260916%' OR trade_date LIKE '%2026-09-16%' ORDER BY id").fetchall():
    print(r)
print("cols:", [c[1] for c in led.execute("PRAGMA table_info(trade_log)").fetchall()])

# --- today's center signal top list & my-holdings center scores ---
print("\n=== today center score of main holdings + fusion score ===")
hold = [r[0] for r in led.execute("SELECT code FROM holdings").fetchall()]
inl = ",".join(f"'{h}'" for h in hold)
try:
    for r in sig.execute(f"SELECT stock_code,score,signal FROM fusion_center_signals WHERE date=(SELECT MAX(date) FROM fusion_center_signals) AND stock_code IN ({inl}) ORDER BY score DESC").fetchall():
        print(r)
except Exception as e: print("center err", e)
try:
    for r in sig.execute(f"SELECT stock_code,fusion_score FROM signal_history WHERE REPLACE(date,'-','')=(SELECT MAX(REPLACE(date,'-','')) FROM signal_history) AND stock_code IN ({inl})").fetchall():
        print(r)
except Exception as e: print("sig err", e)

# --- opinion_log today (intraday engine actions) ---
print("\n=== opinion_log last 3 lines ===")
import io
lines = open('/Users/zantao/.hermes/stockdb/analysis/opinion_log.jsonl').read().strip().split('\n')
for l in lines[-3:]: print(l[:300])

# --- defense state ---
print("\n=== defense_state ===")
print(led.execute("SELECT * FROM defense_state").fetchall())

# --- today's fusion top10 next-day check already in draft; get universe boll pos for lists ---
u = json.load(open('/Users/zantao/.hermes/stockdb/analysis/opinion_universe.json'))
uni = u['universe']
for k in ['300970','001332','301186','603966','301575','301590','300908','688081','688191','301538',
          '000926','603583','002933','300073','300879','003003','300948','600980','300837','000536',
          '605598','001238','300881','300854','301636','688217','605056','688557','301512','600076','601949','600103','603999','300839','002679','603618','301259','603900','688300']:
    v = uni.get(k)
    if not v: print(k,"not in universe"); continue
    bp = None
    try:
        bp = (v['signal_close']-v['boll_low'])/(v['boll_up']-v['boll_low'])*100 if v['boll_up']!=v['boll_low'] else None
    except: pass
    lists = [x['account'] for x in v.get('in_lists',[])]
    print(k, v['name'], f"boll={bp:.0f}% chg5d={v.get('chg5d')} lists={lists}")
sig.close(); led.close(); td.close()
