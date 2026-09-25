#!/usr/bin/env python3
"""排查 09-16 对账报警：trade_log vs sim_accounts JSON 逐笔差异根因（只读）"""
import sqlite3, json
from collections import defaultdict
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
c = sqlite3.connect(str(BASE / 'ledger.db'))
D = '20260916'
strats = ['center_dual','cmmr_fusion','fusion3f','fusion_center','fusion_dual']

for aid in strats:
    d = json.load(open(BASE / 'sim_accounts' / f'{aid}.json'))
    jtr = [t for t in d.get('trades',[]) if str(t.get('date','')).replace('-','')==D]
    tl = c.execute("""SELECT code,direction,price,quantity,trade_time FROM trade_log
        WHERE strategy=? AND REPLACE(trade_date,'-','')=? ORDER BY trade_time,id""",(aid,D)).fetchall()
    print(f'==== {aid} ==== JSON trades today: {len(jtr)}, trade_log today: {len(tl)}')
    # key by (code, dir, shares) ignoring price, count and list prices
    jmap = defaultdict(list); tmap = defaultdict(list)
    for t in jtr:
        act = 'BUY' if t.get('action')=='买入' else 'SELL'
        jmap[(t.get('code'),act,t.get('shares'))].append((t.get('price'),t.get('trade_time')))
    for code,direction,price,qty,tt in tl:
        tmap[(code,direction,qty)].append((price,tt))
    codes = sorted(set(jmap)|set(tmap))
    for k in codes:
        j, t = jmap.get(k,[]), tmap.get(k,[])
        if len(j)==len(t):
            jp = sorted(round(float(a),2) for a,_ in j); tp = sorted(round(float(a),2) for a,_ in t)
            if jp!=tp:
                print(f'  PRICE-DIFF {k}: JSON{jp} vs TL{tp}')
        else:
            print(f'  COUNT-DIFF {k}: JSON {len(j)} {j} | TL {len(t)} {t}')
    # for codes flagged, show the position status
    pos_codes = {x['code']: x.get('shares') for x in d.get('positions',[])}
    flagged = set()
    for k in codes:
        j, t = jmap.get(k,[]), tmap.get(k,[])
        if len(j)!=len(t): flagged.add(k[0])
        else:
            jp = sorted(round(float(a),2) for a,_ in j); tp = sorted(round(float(a),2) for a,_ in t)
            if jp!=tp: flagged.add(k[0])
    for code in sorted(flagged):
        # full history for this code both sides
        jh = [t for t in d.get('trades',[]) if t.get('code')==code]
        th = c.execute("""SELECT trade_date,direction,price,quantity FROM trade_log
            WHERE strategy=? AND code=? ORDER BY REPLACE(trade_date,'-',''),trade_time""",(aid,code)).fetchall()
        print(f'  -- {code} still_in_positions={pos_codes.get(code)} | JSON hist {[(h.get("date"),h.get("action"),h.get("shares"),h.get("price")) for h in jh]}')
        print(f'     TL hist {th}')
c.close()
