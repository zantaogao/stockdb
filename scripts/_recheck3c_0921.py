# -*- coding: utf-8 -*-
"""ⓒ 现实约束检验：0/50/50 与 40/40/20 的 top10 买入日撞涨停/一字板占比（2015/2019/2024）
撞涨停 = 买入日(信号日次日)收盘涨幅≥9.9%(主板)/19.9%(创科) 且 收盘=最高（封死）→ 实盘可能买不进"""
import duckdb, sqlite3, os
import numpy as np, pandas as pd
HOME = os.path.expanduser('~')
sc = sqlite3.connect(f'file:{HOME}/.hermes/stockdb/signals.db?mode=ro', uri=True)
bad = set()
for code, nm, mk in sc.execute("SELECT stock_code, name, market FROM stock_basic").fetchall():
    if (nm and ('ST' in nm or '退' in nm)) or mk == '北交所' or str(code).startswith(('8','4','92')):
        bad.add(str(code))
sc.close()
for year in (2015, 2019, 2024):
    con = duckdb.connect(f'{HOME}/.hermes/stockdb/tushare.db', read_only=True)
    x = con.execute(f"""
      SELECT d.ts_code, CAST(d.trade_date AS INT) td, d.close, d.high, d."open", d.vol, a.adj_factor
      FROM daily d LEFT JOIN adj_factor a USING (ts_code, trade_date)
      WHERE d.trade_date BETWEEN '{year-1}1001' AND '{year+1}0131'
    """).df(); con.close()
    x = x[~x.ts_code.str[:6].isin(bad)]
    co = sorted(x.ts_code.unique())
    def piv(c): return x.pivot(index='td', columns='ts_code', values=c).reindex(columns=co)
    close = piv('close'); opn = piv('open'); vol = piv('vol')
    adjf = piv('adj_factor').ffill().fillna(1.0)
    A = (close*adjf).ffill(); cal = list(close.index)
    m40 = close.rolling(40).mean(); S = (m40 - m40.shift(20))/m40.shift(20)
    P = close/close.shift(10)-1
    Rv = (vol/vol.rolling(5).mean()).values
    Av, Cv, Ov, Hv = A.values, close.values, opn.values, close.values
    H = piv('high').values
    enough = close.rolling(60).count().values >= 60
    is20 = np.array([c[:3] in ('300','301','688','689') for c in co])
    for wname, (wt, wo, wv) in (('40/40/20',(0.4,0.4,0.2)), ('0/50/50',(0.0,0.5,0.5))):
        ntot = nlu = nuniv = 0
        for i in range(60, len(cal)-11):
            if not (year*10000 <= cal[i] < (year+1)*10000): continue
            ent = ~np.isnan(Cv[i+1])
            fwd = np.where(ent & (Av[i+1] > 0), Av[i+1+10]/Av[i+1]-1, np.nan)
            if np.isnan(fwd).all(): continue
            sl, p = S.values[i], P.values[i]
            t = np.where(sl > 0.02, 1.0, np.where(sl > 0, 0.5, 0.0))
            ov = np.where(p < -0.08, 1.0, np.where(p < -0.04, .5, 0.))
            vv = np.where((Rv[i] < 0.8) | ((Rv[i] > 1.2) & (Cv[i] > Ov[i])), 1.0, 0.)
            s = wt*t + wo*ov + wv*vv
            s[np.isnan(sl)|(sl<0)|~enough[i]] = 0
            pool = np.where(s >= 0.8)[0]
            if len(pool) < 10: continue
            ok = ~np.isnan(fwd[pool])
            ps, pp, pi = s[pool][ok], p[pool][ok], pool[ok]
            if len(ps) < 10: continue
            order = np.lexsort((pp, -ps))[:10]
            for k in pi[order]:
                ret = A.iloc[i+1, k]/A.iloc[i, k] - 1  # 买入日相对前日收盘的复权涨幅
                ntot += 1
                lim = 0.199 if is20[k] else 0.099
                if ret >= lim and H[i+1, k] <= close.values[i+1, k]*1.0001:
                    nuniv += 1  # 封死一字（最高=收盘）
                elif ret >= lim:
                    nlu += 1    # 收盘涨停但盘中开板
        print(f'{year} {wname}: 买入{ntot}笔 收盘涨停{ nlu+nuniv}({(nlu+nuniv)/max(ntot,1)*100:.1f}%) 其中一字封死{nuniv}({nuniv/max(ntot,1)*100:.1f}%)')
