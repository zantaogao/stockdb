import sqlite3, duckdb
c = sqlite3.connect('/Users/zantao/.hermes/stockdb/ledger.db')
rows = c.execute('SELECT code,name,buy_date,avg_cost,shares,stop_loss,target_price FROM holdings').fetchall()
d = duckdb.connect('/Users/zantao/.hermes/stockdb/tushare.db', read_only=True)
last = d.execute('SELECT MAX(trade_date) FROM daily').fetchone()[0]
close = dict(d.execute(f"SELECT code, close FROM (SELECT ts_code as code, close, ROW_NUMBER() OVER (PARTITION BY ts_code ORDER BY trade_date DESC) rn FROM daily WHERE trade_date<='{last}') WHERE rn=1").fetchall())
print(f'最新收盘日: {last}')
out=[]
for code,name,bd,cost,sh,sl,tp in rows:
    p = close.get(code) or close.get(code+'.SZ') or close.get(code+'.SH')
    if p is None:
        print(code,name,'NO PRICE'); continue
    pnl=(p/cost-1)*100
    eff=min(sl,cost*0.94)
    dist=(p/eff-1)*100
    src='scan' if sl<=cost*0.94 else 'floor-6%'
    flag=''
    if pnl<=-12: flag=' <== 触发硬止损-12%'
    elif pnl<=-9: flag=' <== 触发加速止损-9%'
    elif p<=eff: flag=' <== 触发规则4跌破止损'
    elif dist<2: flag=' <== 接近止损(<2%)'
    out.append((dist,f'{code} {name:<6} 成本{cost:.2f} 现价{p:.2f} 浮动{pnl:+6.1f}% eff={eff:.2f}({src}) 距止损{dist:+5.1f}%{flag}'))
out.sort()
for _,line in out: print(line)