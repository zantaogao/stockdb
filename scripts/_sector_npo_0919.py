# 华为NPO产业链票走势：今日HC2026发布业界首个量产NPO(Hi-ONE光引擎/7.2T NPO模块)
# 按名查代码→拉近20交易日走势(5/10/20日涨幅、今日、距20日高、量能)
import duckdb
import pandas as pd
d = duckdb.connect('/Users/zantao/.hermes/stockdb/tushare.db', read_only=True)
names = ['中际旭创','新易盛','天孚通信','光迅科技','华工科技','剑桥科技','德科立','源杰科技','仕佳光子','长芯博创','太辰光','意华股份','太龙股份','永鼎股份','沪电股份','深南电路','生益科技','中国长城','神州数码','软通动力','润和软件','拓维信息','四川长虹','烽火通信','中兴通讯','紫光股份','锐捷网络','长飞光纤','亨通光电','中天科技','特发信息','通鼎互联','华工科技','博创科技','腾景科技','致尚科技','沃尔核材','神宇股份','鼎通科技','华丰科技','意华股份']
names = sorted(set(names))
like = '||'.join(names)
sb = d.execute(f"SELECT ts_code,name FROM stock_basic WHERE name IN ({','.join(chr(39)+n+chr(39) for n in names)})").df()
print('找到', len(sb), '只:', sb['name'].tolist())
codes = sb['ts_code'].tolist()
cl = ','.join(chr(39)+c+chr(39) for c in codes)
q = d.execute(f"""
SELECT ts_code, trade_date, open, high, low, close, vol FROM daily
WHERE ts_code IN ({cl}) AND trade_date>='20260810' ORDER BY ts_code, trade_date
""").df()
# 复权
adj = d.execute(f"SELECT ts_code, trade_date, adj_factor FROM adj_factor WHERE trade_date>='20260810' AND ts_code IN ({cl})").df()
q = q.merge(adj, on=['ts_code','trade_date'])
q['f'] = q.groupby('ts_code')['adj_factor'].transform(lambda x: x/x.iloc[-1])
q['qc'] = q['close']*q['f']
idx = d.execute("SELECT trade_date, close FROM index_daily_raw WHERE ts_code='000852.SH' AND trade_date>='20260810' ORDER BY trade_date").df().set_index('trade_date')['close']
nm = sb.set_index('ts_code')['name'].to_dict()
out = []
for tc, g in q.groupby('ts_code'):
    g = g.sort_values('trade_date')
    c = g['qc'].values; dd = g['trade_date'].values
    if len(c) < 6: continue
    r5 = (c[-1]/c[-6]-1)*100; r10 = (c[-1]/c[-11]-1)*100 if len(c)>=11 else None
    r20 = (c[-1]/c[1]-1)*100
    chg = (c[-1]/c[-2]-1)*100
    hd = (c[-1]/g['high'].max()-1)*100
    v5 = g['vol'].tail(5).mean(); v20 = g['vol'].mean()
    # 同期基准(同区间中证1000)
    try:
        b5 = (idx.loc[dd[-1]]/idx.loc[dd[-6]]-1)*100
        ex5 = r5-b5
    except Exception:
        ex5 = None
    out.append((nm[tc], tc, chg, r5, r10, r20, hd, v5/v20, ex5))
o = pd.DataFrame(out, columns=['名称','代码','今日%','5日%','10日%','20日%','距20日高%','量比5/20','5日超额pp']).sort_values('5日超额pp', ascending=False)
b5d = (idx.iloc[-1]/idx.iloc[-6]-1)*100; b10=(idx.iloc[-1]/idx.iloc[-11]-1)*100; b20=(idx.iloc[-1]/idx.iloc[1]-1)*100
print(f'基准: 5日{b5d:+.2f}% 10日{b10:+.2f}% 20日{b20:+.2f}%')
print(o.to_string(index=False, float_format=lambda x:f'{x:.1f}'))
d.close()
