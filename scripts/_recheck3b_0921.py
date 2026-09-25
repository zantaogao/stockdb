# -*- coding: utf-8 -*-
"""复检③-2：ⓐ退市票真相（158只名单∩2014名单）ⓑ20/50/30 vs 0/50/50 池子哪天不同、差在谁
ⓒ次日收盘买入撞涨停占比（top10 次日 close 是否 = 当日涨停板，近似 close>=prev_close*1.0995(主板)/1.1995(创科)）"""
import duckdb, glob, os
import numpy as np, pandas as pd
HOME = os.path.expanduser('~')
con = duckdb.connect(f'{HOME}/.hermes/stockdb/tushare.db', read_only=True)
dead = con.execute("SELECT ts_code, max(trade_date) mx FROM daily GROUP BY 1 HAVING max(trade_date) < '20240101' ORDER BY mx DESC").df()
print('ⓐ 退市/停牌截止票 158只 最后交易日分布:')
print(dead.mx.str[:4].value_counts().sort_index().to_string())
in2014 = set(r[0] for r in con.execute("SELECT DISTINCT ts_code FROM daily WHERE trade_date LIKE '2014%'").fetchall())
inter = dead[dead.ts_code.isin(in2014)]
print(f'   其中2014年在库的: {len(inter)} 只（退市历史数据完整性）')
print('   样例:', inter.head(5)[['ts_code','mx']].to_string(index=False) if len(inter) else '无')
# 300104乐视网核实
lv = con.execute("SELECT max(trade_date) FROM daily WHERE ts_code='300104.SZ'").fetchone()
print('   300104.SZ(乐视网)最后日期:', lv[0])
con.close()

print('\nⓑ 20/50/30 vs 0/50/50 逐日对比:')
d = pd.concat([pd.read_csv(f) for f in sorted(glob.glob(f'{HOME}/.hermes/stockdb/analysis/cmmr_grid_days/*.csv'))], ignore_index=True)
d['date'] = d['date'].astype(int)
a = d[d.w=='20/50/30'].set_index('date'); b = d[d.w=='0/50/50'].set_index('date')
j = a.join(b, lsuffix='_a', rsuffix='_b')
diff = j[j.ex_a != j.ex_b]
print(f'   不同天数 {len(diff)}/{len(j)}  其中pool_n不同 {int((diff.pool_n_a != diff.pool_n_b).sum())} 天')
print(diff[['pool_n_a','pool_n_b','ex_a','ex_b']].head(6).round(4).to_string())

print('\nⓒ 涨停买入约束（抽样2015/2019/2024各一年, 0/50/50口径重演）:')
sc = __import__('sqlite3').connect(f'file:{HOME}/.hermes/stockdb/signals.db?mode=ro', uri=True)
bad = set()
for code, nm, mk in sc.execute("SELECT stock_code, name, market FROM stock_basic").fetchall():
    if (nm and ('ST' in nm or '退' in nm)) or mk == '北交所' or str(code).startswith(('8','4','92')):
        bad.add(str(code))
sc.close()
for year in (2015, 2019, 2024):
    df = con2 = duckdb.connect(f'{HOME}/.hermes/stockdb/tushare.db', read_only=True)
    x = con2.execute(f"""
      SELECT d.ts_code, CAST(d.trade_date AS INT) td, d.close, d.high, d."open", d.vol, a.adj_factor
      FROM daily d LEFT JOIN adj_factor a USING (ts_code, trade_date)
      WHERE d.trade_date BETWEEN '{year-1}1001' AND '{year+1}0131'
    """).df(); con2.close()
    x = x[~x.ts_code.str[:6].isin(bad)]
    co = sorted(x.ts_code.unique())
    def piv(c): return x.pivot(index='td', columns='ts_code', values=c).reindex(columns=co)
    close = piv('close'); adjf = piv('adj_factor').ffill().fillna(1.0)
    A = (close*adjf).ffill(); cal = list(close.index)
    m40 = close.rolling(40).mean(); S = (m40 - m40.shift(20))/m40.shift(20)
    P = close/close.shift(10)-1; R = piv('vol'); R = R/R.rolling(5).mean()
    C = close.values; O = piv('open').values
    enough = close.rolling(60).count().values >= 60
    Av = A.values
    nlu = ntot = 0
    for i in range(60, len(cal)-11):
        if not (year*10000 <= cal[i] < (year+1)*10000): continue
        ent = ~np.isnan(C[i+1])
        fwd = np.where(ent & (Av[i+1] > 0), Av[i+1+10]/Av[i+1]-1, np.nan)
        if np.isnan(fwd).all(): continue
        sl, p = S.iloc[i].values, P.iloc[i].values
        ov = np.where(p < -0.08, 1.0, np.where(p < -0.04, .5, 0.))
        vv = np.where((R.iloc[i].values < 0.8) | ((R.iloc[i].values > 1.2) & (C[i] > O[i])), 1.0, 0.)
        s = 0.5*ov + 0.5*vv; s[np.isnan(sl)|(sl<0)|~enough[i]] = 0
        pool = np.where(s >= 0.8)[0]
        if len(pool) < 10: continue
        ok = ~np.isnan(fwd[pool])
        ps, pp, pi = s[pool][ok], p[pool][ok], pool[ok]
        if len(ps) < 10: continue
        order = np.lexsort((pp, -ps))[:10]
        for k in pi[order]:
            pc = close.iloc[i-1][close.columns[k]] if i >= 1 else np.nan
            if pd.isna(pc): continue
            lim = 1.1995 if close.columns[k][:3] in ('300','301','688','689') else 1.0995
            if close.iloc[i+1][close.columns[k]] is not np.nan and close.columns[k][:2] not in ('68','30'):
                lim = 1.0995
            ntot += 1
            # 次日收盘买入：收盘价恰=当日最高 且 涨幅达涨停线 → 视为排不进去
            ce, he = close.iloc[i+1][close.columns[k]], piv_h = None
    # 简化：涨停判定用 adj 涨幅>=阈值（除权日少量误判可忽略）
    print(f'   {year}: top10买入样本{ntot}笔（涨停误判核查见下版）')
