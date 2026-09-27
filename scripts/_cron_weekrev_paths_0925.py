import pandas as pd

def bar(path, date, t):
    df = pd.read_parquet(path)
    d = df[(df['date'] == date)]
    if d.empty:
        return None
    r = d[d['time'].astype(str).str.startswith(t[:8])]
    return r[['time','open','high','low','close']].to_dict('records')

# For each trade this week, print key minute context around execution
trades = [
    ('sz_301538', '2026-09-18', 'BUY', 41.01),
    ('sh_688592', '2026-09-18', 'BUY', 22.81),
    ('sh_605598', '2026-09-24', 'SELL', 24.82),
    ('sh_688607', '2026-09-24', 'SELL', 38.05),
    ('sz_301338', '2026-09-24', 'SELL', 99.91),
    ('sz_301538', '2026-09-24', 'SELL', 41.0),
    ('sh_603382', '2026-09-24', 'BUY', 19.01),
    ('sz_300500', '2026-09-24', 'BUY', 9.61),
    ('sh_688659', '2026-09-24', 'BUY', 9.32),
    ('sz_300982', '2026-09-24', 'BUY', 14.39),
]
for code, date, d, px in trades:
    df = pd.read_parquet(f'minutes/5min/{code}.parquet')
    day = df[df['date'] == date]
    if day.empty:
        print(f'{code} {date} {d}: NO DATA')
        continue
    prev = df[df['date'] < date].tail(1)
    pc = float(prev['close'].iloc[0]) if not prev.empty else None
    open_ = float(day['open'].iloc[0]); close = float(day['close'].iloc[-1])
    hi = float(day['high'].max()); lo = float(day['low'].min())
    # find bar nearest to fill price
    day2 = day.copy()
    day2['diff'] = (day2['close'] - px).abs()
    nb = day2.sort_values('diff').iloc[0]
    print(f'{code} {date} {d} px={px} prevclose={pc} open={open_} hi={hi} lo={lo} close={close} '
          f'fillbar={str(nb["time"])[8:12]} daychg={(close/pc-1)*100:.2f}% hi_from_px={(hi/px-1)*100:.2f}% lo_from_px={(lo/px-1)*100:.2f}%')
    # 3-day forward for buys (to next available days)
    after = df[df['date'] > date].head(3)
    for _, r in after.iterrows():
        print(f'    fwd {r["date"]}: close={r["close"]} hi={r["high"]} lo={r["low"]}')
