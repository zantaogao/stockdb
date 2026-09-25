#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""11:15 tick 只读复核：策略账户 pos_value 是否用实时价（而非成本价兜底）。"""
import sqlite3, sys
sys.path.insert(0, '/Users/zantao/.hermes/stockdb')
from core.prices import fetch_prices_batch

c = sqlite3.connect('/Users/zantao/.hermes/stockdb/ledger.db')
for aid in ['agent_auto', 'center_dual', 'cmmr', 'cmmr_fusion', 'fusion_center']:
    pos = list(c.execute(
        'SELECT code,name,shares,avg_cost FROM strategy_positions WHERE account_id=?', (aid,)))
    codes = [p[0] for p in pos]
    rtp = fetch_prices_batch(codes) if codes else {}
    miss = [p[0] for p in pos if not rtp.get(p[0])]
    live_val = sum(p[2] * (rtp.get(p[0]) or p[3]) for p in pos)
    cost_val = sum(p[2] * p[3] for p in pos)
    db = list(c.execute(
        "SELECT pos_value FROM strategy_accounts_legacy WHERE account_id=? AND REPLACE(date,'-','')='20260915'", (aid,)))
    dbv = db[0][0] if db else None
    print(f'{aid:14s} n={len(pos):3d} live={live_val:11.0f} cost={cost_val:11.0f} db={dbv:11.0f} '
          f'db-live={dbv-live_val:+9.0f} miss={len(miss)} {miss[:5]}')
    # 逐票：db 侧是否有票恰好等于成本价（疑似兜底）无法逐票看，但整体不一致即非全兜底
