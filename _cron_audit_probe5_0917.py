import sqlite3, json
base = '/Users/zantao/.hermes/stockdb'
c = sqlite3.connect(base + '/ledger.db')
for aid in ('fusion3f','fusion_dual','center_dual','fusion_center','cmmr_fusion'):
    sp = c.execute("SELECT code,shares,updated_at FROM strategy_positions WHERE account_id=? ORDER BY code", (aid,)).fetchall()
    print(aid, 'strategy_positions:', sp)
    m = c.execute("SELECT cash,updated_at FROM strategy_accounts_meta WHERE account_id=?", (aid,)).fetchall()
    print(aid, 'meta cash:', m)
# cleanup codes still in strategy_positions?
cleanup = {'fusion3f':['600198','600395','600403','601001','601991'],
 'fusion_dual':['000545','001260','002565','002972','300036','300444','300511','300772','601615','603279','603585','603665'],
 'center_dual':['000990','001256','001332','002531','002866','603698','688486'],
 'fusion_center':['000032','000720','600790','600841','601996','603103'],
 'cmmr_fusion':['605189']}
print()
for aid, codes in cleanup.items():
    remain = c.execute(f"SELECT code,shares FROM strategy_positions WHERE account_id=? AND code IN ({','.join('?'*len(codes))})", (aid,*codes)).fetchall()
    print(aid, 'cleanup codes still in strategy_positions:', remain)
