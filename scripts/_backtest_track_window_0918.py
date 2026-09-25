# 跟踪满窗口回测：top10榜单票"立即买入" vs "回踩MA10限价介入" vs "突破介入"
# 信号源 signal_history(46信号日)，窗口=10个交易日，成熟信号日截至数据允许
import sqlite3, duckdb, json
import pandas as pd, numpy as np

SIG = '/Users/zantao/.hermes/stockdb/signals.db'
TUSH = '/Users/zantao/.hermes/stockdb/tushare.db'

s = sqlite3.connect(SIG)
sh = pd.read_sql("SELECT date, stock_code, stock_name, fusion_score FROM signal_history", s)
sh['date'] = sh['date'].str.replace('-','')
sh = sh.sort_values(['date','fusion_score'], ascending=[True,False])
top10 = sh.groupby('date').head(10)
sig_dates = sorted(top10['date'].unique())

d = duckdb.connect(TUSH, read_only=True)
cal = [r[0] for r in d.execute("SELECT DISTINCT trade_date FROM index_daily_raw WHERE ts_code='000852.SH' AND trade_date>='20260701' ORDER BY trade_date").fetchall()]

codes = sorted(top10['stock_code'].unique())
def suffix(c):
    return c+'.SH' if c[0]=='6' else (c+'.BJ' if c[0] in '489' else c+'.SZ')
code_list = ','.join("'"+suffix(c)+"'" for c in codes)
px = d.execute(f"""
  SELECT p.ts_code, p.trade_date, p.open, p.high, p.low, p.close, a.adj_factor
  FROM daily p JOIN adj_factor a USING (ts_code, trade_date)
  WHERE p.ts_code IN ({code_list}) AND p.trade_date BETWEEN '20260701' AND '20260918'
""").df()
idx = d.execute("SELECT trade_date, close FROM index_daily_raw WHERE ts_code='000852.SH' AND trade_date>='20260701' ORDER BY trade_date").df()
d.close()

# 复权：按每票最后一日归一
px['f'] = px.groupby('ts_code')['adj_factor'].transform(lambda x: x/x.iloc[-1])
for c in ['open','high','low','close']:
    px['q_'+c] = px[c]*px['f']
px = px.sort_values(['ts_code','trade_date'])
px['ma10'] = px.groupby('ts_code')['q_close'].transform(lambda x: x.rolling(10).mean())
px['hi20'] = px.groupby('ts_code')['q_high'].transform(lambda x: x.rolling(20).max().shift(1))
book = {t: g.set_index('trade_date') for t, g in px.groupby('ts_code')}
ic = idx.set_index('trade_date')['close']

def iret(a, b):  # 指数两日收益
    try: return ic.loc[b]/ic.loc[a]-1
    except Exception: return None

results = {'immediate': [], 'dip': [], 'breakout': [], 'no_trigger_dip': [], 'no_trigger_bo': []}
for sd in sig_dates:
    di = [i for i,dd in enumerate(cal) if dd > sd]
    if len(di) < 1: continue
    e0 = cal[di[0]]                       # T+1
    # 窗口=入场后10个交易日; 立即策略入场T+1开盘, 出场T+11
    for _, row in top10[top10['date']==sd].iterrows():
        t = suffix(row['stock_code'])
        if t not in book: continue
        g = book[t]
        days = [dd for dd in g.index if dd > sd]
        if len(days) < 11: continue       # 窗口不满10日的不计入(跟踪未结束)
        o1 = g.loc[days[0],'q_open']; 
        # A 立即: T+1开盘买, 持10日
        pa = g.loc[days[10],'q_close']/o1-1
        bm = iret(days[0], days[10])
        results['immediate'].append((sd, row['stock_code'], row['stock_name'], pa, bm))
        # B 回踩MA10: T+1起10个交易日内 low<=ma10 触发, 触发日收盘买, 再持10日(需窗口足够→用触发后第10日, 数据到918为限, 不足则持有到918)
        trig = None
        for k in range(0, min(10, len(days)-1)):
            dd = days[k]
            if g.loc[dd,'q_low'] <= g.loc[dd,'ma10'] and not np.isnan(g.loc[dd,'ma10']):
                trig = k; break
        if trig is not None:
            end = min(trig+10, len(days)-1)
            if end > trig:
                pb = g.loc[days[end],'q_close']/g.loc[days[trig],'q_close']-1
                mb = iret(days[trig], days[end])
                results['dip'].append((sd, row['stock_code'], row['stock_name'], pb, mb, trig, end-trig))
        else:
            results['no_trigger_dip'].append((sd, row['stock_code'], (g.loc[days[min(10,len(days)-1)],'q_close']/o1-1)))
        # C 突破前20日高
        trig2 = None
        for k in range(0, min(10, len(days)-1)):
            dd = days[k]
            if not np.isnan(g.loc[dd,'hi20']) and g.loc[dd,'q_high'] > g.loc[dd,'hi20']:
                trig2 = k; break
        if trig2 is not None:
            end = min(trig2+10, len(days)-1)
            if end > trig2:
                pc = g.loc[days[end],'q_close']/g.loc[days[trig2],'q_close']-1
                mc = iret(days[trig2], days[end])
                results['breakout'].append((sd, row['stock_code'], row['stock_name'], pc, mc, trig2, end-trig2))
        else:
            results['no_trigger_bo'].append((sd, row['stock_code'], (g.loc[days[min(10,len(days)-1)],'q_close']/o1-1)))

def summ(rows, label):
    if not rows: print(label, '无'); return
    r = np.array([x[3] for x in rows])*100; b = np.array([x[4] for x in rows if x[4] is not None])*100
    ex = (r-b).mean()
    print(f"{label}: n={len(rows)} 平均{r.mean():+.2f}% 中位{np.median(r):+.2f}% 胜率{(r>0).mean()*100:.0f}% | 同期基准{b.mean():+.2f}% 超额{ex:+.2f}pp")

print('成熟信号日数:', len(sig_dates))
summ(results['immediate'], 'A 立即(T+1开盘,持10日)')
summ(results['dip'], 'B 回踩MA10介入(触发日收盘,持≤10日)')
summ(results['breakout'], 'C 突破20日高介入(触发日收盘,持≤10日)')
nt = results['no_trigger_dip']
if nt:
    r = np.array([x[2] for x in nt])*100
    print(f"B未触发组(踏空/避开): n={len(nt)} 若强行T+1买回报均值{r.mean():+.2f}% 胜率{(r>0).mean()*100:.0f}%")
nt2 = results['no_trigger_bo']
if nt2:
    r = np.array([x[2] for x in nt2])*100
    print(f"C未触发组(盘整): n={len(nt2)} 若强行T+1买回报均值{r.mean():+.2f}% 胜率{(r>0).mean()*100:.0f}%")
# 触发耗时
if results['dip']:
    tg = np.array([x[5] for x in results['dip']])
    print('回踩触发耗时(交易日): 中位', int(np.median(tg)), '均值%.1f'%tg.mean())
# 按信号日分期看稳定性(前半/后半)
for tag, sub in [('immediate', results['immediate']), ('dip', results['dip'])]:
    if len(sub) >= 10:
        dates = sorted(set(x[0] for x in sub)); half = dates[len(dates)//2]
        for lbl, rows in [('前段', [x for x in sub if x[0] < half]), ('后段', [x for x in sub if x[0] >= half])]:
            if rows: summ(rows, f'  分段-{tag}-{lbl}')
json.dump({k:[list(map(lambda v: float(v) if isinstance(v,(np.floating,)) else v, x)) for x in v] for k,v in results.items()},
          open('/Users/zantao/.hermes/stockdb/scripts/_track_bt_rows_0918.json','w'), default=str, ensure_ascii=False)
print('明细已存 _track_bt_rows_0918.json')
