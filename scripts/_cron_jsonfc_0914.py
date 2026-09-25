#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fusion_center JSON nav_history 尾三条 + 与库内对比"""
import json, os
p = os.path.expanduser("~/.hermes/stockdb/sim_accounts/fusion_center.json")
d = json.load(open(p, encoding="utf-8"))
nh = d.get("nav_history") or []
print("nav_history 尾4条:")
for h in nh[-4:]:
    print("  ", h)
print("n_pos(JSON 持仓数):", len(d.get("positions") or []))
print("cash:", d.get("cash"))
