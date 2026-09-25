#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""分模型 IC 趋势 (signals.db 只读)"""
import os, sqlite3
os.chdir(os.path.expanduser('~/.hermes/stockdb'))
c = sqlite3.connect('signals.db')
c.row_factory = sqlite3.Row

def table_ok(t):
    r = c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", [t]).fetchone()
    return r is not None

for t in ['ic_daily', 'fusion_ic_daily', 'center_dual_ic_daily', 'ic_window', 'signal_history']:
    print(t, 'exists' if table_ok(t) else 'MISSING')
print()

def dump(t, limit=12):
    print('=' * 60)
    print('TABLE', t)
    try:
        cols = [r[1] for r in c.execute(f"PRAGMA table_info({t})").fetchall()]
        print('cols:', cols)
        # find date col
        dcol = None
        for cand in ['signal_date', 'trade_date', 'date', 'dt']:
            if cand in cols:
                dcol = cand
                break
        q = f"SELECT * FROM {t} ORDER BY {dcol} DESC LIMIT {limit}" if dcol else f"SELECT * FROM {t} LIMIT {limit}"
        for r in c.execute(q).fetchall():
            d = dict(r)
            # trim long fields
            out = {k: (round(v, 4) if isinstance(v, float) else (str(v)[:40] if v is not None else None)) for k, v in d.items()}
            print(out)
    except Exception as e:
        print('ERR', e)

for t in ['ic_daily', 'fusion_ic_daily', 'center_dual_ic_daily', 'ic_window']:
    if table_ok(t):
        dump(t)
c.close()
