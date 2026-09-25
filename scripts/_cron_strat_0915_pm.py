#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""校验策略账户日更：各账户最新交易日/状态，重点看 fusion3f/fusion_dual 停在 20260910 是否正常。只读。"""
import sqlite3, os, glob

base = os.path.expanduser("~/.hermes/stockdb")

def hdr(p):
    try:
        with open(p, "rb") as f:
            return f.read(16)
    except Exception as e:
        return b"ERR:" + str(e).encode()

cands = [os.path.join(base, "strategy_accounts.db"),
         os.path.join(base, "ledger.db"),
         os.path.join(base, "signals.db")]
for p in cands:
    print("FILE", p, os.path.getsize(p) if os.path.exists(p) else "MISSING", hdr(p))

for p in cands:
    if not os.path.exists(p):
        continue
    try:
        c = sqlite3.connect("file:%s?mode=ro" % p, uri=True)
        tabs = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        print("\n=== %s tables: %s" % (os.path.basename(p), tabs))
        for t in tabs:
            if "strat" in t or "account" in t or "equity" in t or "nav" in t:
                cols = [r[1] for r in c.execute("PRAGMA table_info(%s)" % t)]
                n = c.execute("SELECT COUNT(*) FROM %s" % t).fetchone()[0]
                print("  - %s(%d) cols=%s" % (t, n, cols))
        c.close()
    except Exception as e:
        print("ERR open", p, e)
