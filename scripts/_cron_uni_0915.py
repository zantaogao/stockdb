# -*- coding: utf-8 -*-
"""opinion_universe.json 中除权票字段核查（2026-09-15）"""
import json, os
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
u = json.load(open(os.path.join(BASE, 'analysis/opinion_universe.json'), encoding='utf-8'))
print("generated_at:", u.get('generated_at'), "signal_date:", u.get('signal_date'), "exec_date:", u.get('exec_date'))
print("池子票数:", len(u.get('universe', {})))
for c in ['301237', '300908', '300818', '301283', '600076', '300970']:
    v = u['universe'].get(c)
    print(f"  {c}: {v}")
print("\n账户:", json.dumps(u.get('accounts', {}), ensure_ascii=False)[:600])
print("\ntop10 keys:", list(u.get('top10', {}).keys()))
print("\nmain_holdings 条数:", len(u.get('main_holdings', [])))
