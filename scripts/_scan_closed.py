import csv, collections, sys
rows=list(csv.reader(open('/tmp/agent_trades.csv')))
print('trade rows:',len(rows))
amt=collections.defaultdict(float); qty=collections.defaultdict(int); last={}
for d,dir,c,q,p,a in rows:
    q=int(q); a=float(a)
    amt[c]+= a if dir=='SELL' else -a
    qty[c]+= -q if dir=='SELL' else q
    last[c]=(d,dir)
closed=[(c,amt[c],last[c]) for c in amt if qty[c]==0]
won=[x for x in closed if x[1]>0]; lost=[x for x in closed if x[1]<=0]
print('closed',len(closed),'win',len(won),'lose',len(lost),'realized %.0f'%sum(x[1] for x in closed))
print('gross win %.0f gross loss %.0f'%(sum(x[1] for x in won),sum(x[1] for x in lost)))
print('open:',{c:q for c,q in qty.items() if q!=0})
