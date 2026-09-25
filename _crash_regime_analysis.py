import sqlite3, duckdb, statistics
sig = sqlite3.connect('/Users/zantao/.hermes/stockdb/signals.db')
rows = sig.execute("SELECT signal_date, top10_ew, top10_win, sb_ew, mkt_ew, n_sb FROM fusion_3f_backtest ORDER BY signal_date").fetchall()
d = duckdb.connect('/Users/zantao/.hermes/stockdb/tushare.db', read_only=True)
idx = {r[0].replace('-',''): r[1] for r in d.execute("SELECT CAST(date AS VARCHAR), change_pct FROM index_daily WHERE index_code='000852'").fetchall()}
print(len(rows), 'backtest days; idx days:', len(idx))
print('date range of backtest:', rows[0][0], '->', rows[-1][0])
crash, normal, missing = [], [], []
for (dt, top10, top10w, sb, mkt, n) in rows:
    key = dt.replace('-','')
    if key not in idx:
        missing.append(dt); continue
    (crash if idx[key] <= -3.0 else normal).append((dt, idx[key], top10, top10w, sb, mkt))
print('missing idx for:', missing)
print('CRASH days (idx<=-3%):')
for c in crash: print(c)
nt = [x[2] for x in normal if x[2] is not None]
nsb = [x[4] for x in normal if x[4] is not None]
print('NORMAL days:', len(normal), 'with top10 ret:', len(nt))
if nt:
    print('normal top10 mean: %.3f median: %.3f win>0: %d/%d' % (statistics.mean(nt), statistics.median(nt), sum(1 for v in nt if v>0), len(nt)))
# also mild down days -1~-3
mild = [x for x in normal if x[1] <= -1.0]
print('MILD days (-1~-3%):', len(mild))
for m in mild: print(m)
mt = [x[2] for x in mild if x[2] is not None]
if mt: print('mild top10 mean: %.3f win>0: %d/%d' % (statistics.mean(mt), sum(1 for v in mt if v>0), len(mt)))
up = [x for x in normal if x[1] > 0]
ut = [x[2] for x in up if x[2] is not None]
if ut: print('up days top10 mean: %.3f win>0: %d/%d (n=%d)' % (statistics.mean(ut), sum(1 for v in ut if v>0), len(ut), len(ut)))
