#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""get_position_sizing 单测（2026-09-21 防碎仓修复）

覆盖：①基数改 NAV 的核心回归 ②现金夹逼 ③NAV×2.5% 最小权重门槛 ④大盘系数
      ⑤不建仓档 ⑥科创/创业 200 股校验 ⑦total_value=0 除零保护
两台通用：从源码 ast 抽取常量与函数（不 import 模块，避免顶层副作用）；
MacBook 版多 defense_mode 参数 → 自动识别并注入 defense stub。
用法：python3 -B _test_position_sizing.py [intraday_decision.py 路径]
"""
import ast
import inspect
import sys
import types

PATH = sys.argv[1] if len(sys.argv) > 1 else '/Users/zantao/.hermes/stockdb/scripts/intraday_decision.py'
WANT = {'POSITION_SCALE', 'MIN_POSITION_RATIO', 'MIN_CASH_RATIO', 'MAX_POSITION_RATIO'}

tree = ast.parse(open(PATH, encoding='utf-8').read())
nodes = []
for n in tree.body:
    if isinstance(n, ast.Assign) and any(getattr(t, 'id', '') in WANT for t in n.targets):
        nodes.append(n)
    elif isinstance(n, ast.FunctionDef) and n.name == 'get_position_sizing':
        nodes.append(n)
ns = {'defense': types.SimpleNamespace(buy_scale=lambda m: 1.0 if m == 'normal' else 0.5)}
exec(ast.unparse(ast.Module(body=nodes, type_ignores=[])), ns)
fps = ns['get_position_sizing']
SIG = inspect.signature(fps)
HAS_DM = 'defense_mode' in SIG.parameters
print('被测: %s' % PATH)
print('签名: %s' % SIG)
print('MIN_POSITION_RATIO=%s   defense_mode 参数: %s' % (ns.get('MIN_POSITION_RATIO'), HAS_DM))
print()


def sz(cash, tv, price, score, mkt=0.0, code='600000.SH'):
    kw = {'defense_mode': 'normal'} if HAS_DM else {}
    return fps(cash, tv, price, score, mkt, code, **kw)


NAV = 1000000.0
cases = [
    ('① 满仓现金 + 评分90 → 15% NAV',                        sz(NAV, NAV, 10, 90), 15000),
    ('② 核心回归: 现金35.7%NAV + 评分70 → 5% NAV(非5%现金)',  sz(357000, NAV, 10, 70), 5000),
    ('③ 现金夹逼: 现金3%NAV + 评分70 → 3% NAV',              sz(30000, NAV, 10, 70), 3000),
    ('④ 防碎门槛: 现金2.4%NAV + 评分70 → 0 股',              sz(24000, NAV, 10, 70), 0),
    ('⑤ 大盘-1.5% → 系数0.8: 评分70 → 4% NAV',              sz(NAV, NAV, 10, 70, -1.5), 4000),
    ('⑥ 大盘-1.5% + 现金3%NAV → 夹逼 3% NAV',               sz(30000, NAV, 10, 70, -1.5), 3000),
    ('⑦ 评分65(<70) → 不建仓',                              sz(NAV, NAV, 10, 65), 0),
    ('⑧ 评分78 → 10% NAV',                                  sz(NAV, NAV, 10, 78), 10000),
    ('⑨ 创业板高价: NAV10万/评分70/价30元 → 100股<200 → 0',  sz(100000, 100000, 30, 70, 0, '300001.SZ'), 0),
    ('⑩ total_value=0 → 0 股(不崩)',                        sz(NAV, 0, 10, 70), 0),
]
ok = 0
for name, got, want in cases:
    g = got[0] if isinstance(got, tuple) else got
    good = (g == want)
    ok += good
    print('  %s %s  → 实得 %s 股 (期望 %s)' % ('✅' if good else '❌', name, g, want))

old = int(0.05 * 357000 / 10 / 100) * 100
new = sz(357000, NAV, 10, 70)[0]
print()
print('  旧逻辑对照(现金基数): 357000×5%% = %s 股；新逻辑(NAV基数): %s 股 → %s'
      % (old, new, '修复生效 ✅' if new > old else '未生效 ❌'))
ok += (new > old)
total = len(cases) + 1
print()
print('结果：%s/%s 通过' % (ok, total))
sys.exit(0 if ok == total else 1)
