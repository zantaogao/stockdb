import json, glob
d='/Users/zantao/.hermes/stockdb/sim_accounts'
for f in sorted(glob.glob(d+'/*.json')):
    if 'bak' in f or 'old' in f or 'err' in f: continue
    try:
        j=json.load(open(f))
    except: continue
    name=f.split('/')[-1].replace('.json','')
    nav=j.get('nav',{})
    if nav.get('date')!='2026-09-25': continue
    buys=[(t.get('code'),t.get('name'),t.get('shares'),round(t.get('price',0),2),t.get('reason',''))
          for t in j.get('trades',[]) if str(t.get('date','')).replace('-','').endswith('0925') and str(t.get('action','')).endswith('买入')]
    sells=[(t.get('code'),t.get('name'),t.get('shares'),round(t.get('price',0),2),t.get('reason',''))
           for t in j.get('trades',[]) if str(t.get('date','')).replace('-','').endswith('0925') and str(t.get('action','')).endswith('卖出')]
    pos=j.get('positions',[])
    print(f'{name}: NAV={nav.get("nav")} cash={j.get("cash")} 持仓{len(pos)}只')
    for b in buys: print(f'  买入 {b[0]} {b[1]} {b[2]}股@{b[3]} [{b[4]}]')
    for s in sells: print(f'  卖出 {s[0]} {s[1]} {s[2]}股@{s[3]} [{s[4]}]')
    for p in pos:
        print(f'  持 {p.get("code")} {p.get("name")} {p.get("shares")}股 (cost {p.get("avg_cost")})')
