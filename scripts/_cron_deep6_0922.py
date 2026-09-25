#!/usr/bin/env python3
import sqlite3, os, statistics as st
os.chdir(os.path.expanduser('~/.hermes/stockdb'))
led = sqlite3.connect('file:ledger.db?mode=ro', uri=True)
sig = sqlite3.connect('file:signals.db?mode=ro', uri=True)

print('== 主账户 距止损/止盈 ==')
for code,name,price,tp,sl in led.execute("SELECT code,name,latest_price,target_price,stop_loss FROM holdings"):
    d_tp = (tp/price-1)*100 if tp and price else None
    d_sl = (price/sl-1)*100 if sl and price else None
    print(f'{code} {name} px={price} 距止盈 {d_tp:+.1f}% 距止损 {d_sl:+.1f}%')

print('== 策略账户 R7 浮亏线(现价<=成本*0.94) ==')
tabs = [r[0] for r in led.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
print('ledger tabs:', tabs)
for t in tabs:
    if 'hold' in t and t!='holdings':
        cols=[c[1] for c in led.execute(f"PRAGMA table_info({t})").fetchall()]
        print(t, cols)
        try:
            for r in led.execute(f"SELECT * FROM {t}").fetchall():
                s=str(r)
                print(' ', s[:160])
        except Exception as e: print(t, e)

print('== IC 均值（5/10日窗口）==')
rows = sig.execute("SELECT signal_date,ic_fusion,ic_reg10,ic_reg20,ic_reg40 FROM ic_daily ORDER BY signal_date DESC LIMIT 15").fetchall()[::-1]
for i,name in [(1,'fusion'),(2,'reg10'),(3,'reg20'),(4,'reg40')]:
    s5=[r[i] for r in rows[-5:]]; s10=[r[i] for r in rows[-10:]]
    print(f'{name}: 5日均 {st.mean(s5):+.3f} 10日均 {st.mean(s10):+.3f} 近5序列 {[round(x,3) for x in s5]}')
cr = sig.execute("SELECT date,ic FROM fusion_ic_daily ORDER BY date DESC LIMIT 15").fetchall()[::-1]
print('center(fusion_ic_daily): 5日均 %+.3f 10日均 %+.3f' % (st.mean([r[1] for r in cr[-5:]]), st.mean([r[1] for r in cr[-10:]])))
cd = sig.execute("SELECT date,ic FROM center_dual_ic_daily ORDER BY date DESC LIMIT 15").fetchall()[::-1]
print('center_dual: 5日均 %+.3f 10日均 %+.3f' % (st.mean([r[1] for r in cd[-5:]]), st.mean([r[1] for r in cd[-10:]])))

print('== ic_window 近8日 center/dual/cmmr top组前向收益 ==')
for r in sig.execute("SELECT signal_date,ic_center_w10,fwd10_top_center,ic_dual_w10,fwd10_top_dual,ic_cmmr_w10,fwd10_top_cmmr,fwd10_top_3f,ic_reg10_w10,fwd10_top FROM ic_window ORDER BY signal_date DESC LIMIT 10").fetchall():
    print(str(r)[:200])
