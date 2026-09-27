import pandas as pd
import sqlite3

# 09-24 sells: exit price vs subsequent days (fwd as available: only 09-24 data ends week; 09-25 is holiday)
for code, name, sell_px in [('605598','上海港湾',24.82),('688607','康众科技',38.05),('301338','凯格精机',99.91),('301538','骏鼎达',41.0)]:
    pref = 'sh_' if code.startswith('6') else 'sz_'
    df = pd.read_parquet(f'minutes/5min/{pref}{code}.parquet')
    d = df[df['date']=='2026-09-24']
    close = float(d['close'].iloc[-1]); hi=float(d['high'].max()); lo=float(d['low'].min())
    print(f'{name} sell@{sell_px} day_close={close} day_hi={hi} day_lo={lo} close_vs_sell={(close/sell_px-1)*100:+.2f}% lo_vs_sell={(lo/sell_px-1)*100:+.2f}%')

# 09-18 buys current state
for code,name,cost in [('688592','司南导航',22.81),('301538','骏鼎达',41.01)]:
    pref = 'sh_' if code.startswith('6') else 'sz_'
    df = pd.read_parquet(f'minutes/5min/{pref}{code}.parquet')
    d = df[df['date']>='2026-09-18']
    print(f'{name} buy@{cost}:', [(r['date'], float(r['close'])) for _,r in d.groupby('date').tail(1).iterrows()])

# intraday: did SELLs hit near day-low (bad timing) or after drop?
con = sqlite3.connect('ledger.db')
# defense state
try:
    print(con.execute("SELECT * FROM defense_state").fetchall())
except Exception as e: print('defense err', e)
print(con.execute("PRAGMA table_info(defense_state)").fetchall())
