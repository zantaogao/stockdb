# -*- coding: utf-8 -*-
"""defense.py 状态机冒烟测试（2026-09-16 挂上验收）：不碰真库状态行（测试用事务回滚）"""
import sys, os
sys.path.insert(0, os.path.expanduser('~/.hermes/stockdb'))
from core import defense

ok = True
def chk(name, cond):
    global ok
    print(('PASS' if cond else 'FAIL'), name)
    ok = ok and cond

# 纯函数
chk('buy_scale normal=1', defense.buy_scale('normal') == 1.0)
chk('buy_scale halved=0.5', defense.buy_scale('halved') == 0.5)
chk('float_stop normal=0.94', defense.float_stop('normal') == 0.94)
chk('float_stop crash2=0.95', defense.float_stop('crash2') == 0.95)
chk('kill fusion2.9', defense.defense_kill_fusion('halved', 2.9) is True)
chk('kill fusion=None 不误杀', defense.defense_kill_fusion('crash2', None) is False)
chk('kill normal不杀', defense.defense_kill_fusion('normal', 1.0) is False)

# cut_plan：NAV=100万(现金20+市值80)，cap 50% → 需卖≥30万，fusion升序先砍低分
pos = [
    {'code': '600001', 'shares': 1000, 'price': 200.0},   # mv 20万 fusion 8
    {'code': '600002', 'shares': 1000, 'price': 300.0},   # mv 30万 fusion 2
    {'code': '600003', 'shares': 1000, 'price': 300.0},   # mv 30万 fusion 5
]
fmap = {'600001': 8.0, '600002': 2.0, '600003': 5.0}
cuts, msg = defense.cut_plan('crash2', pos, 200000, fmap)
chk('cut_plan 先砍fusion最低600002(30万)', cuts == ['600002'])
# 边界：mv==cap 不砍
pos2 = [{'code': '600001', 'shares': 1000, 'price': 200.0}]
cuts2, _ = defense.cut_plan('crash2', pos2, 200000, fmap)  # mv20 nav40 cap20 → 不砍
chk('已≤5成 清单为空', cuts2 == [])
# fusion 缺失不砍
cuts3, _ = defense.cut_plan('crash2', [{'code': '600009', 'shares': 1000, 'price': 800.0}],
                            200000, fmap)
chk('fusion缺失不砍', cuts3 == [])
# normal 模式空
cuts4, _ = defense.cut_plan('normal', pos, 200000, fmap)
chk('normal 清单为空', cuts4 == [])

# get_fusion_map 真库
fm = defense.get_fusion_map()
chk(f'get_fusion_map 有数据({len(fm)}只)', len(fm) > 1000)

# _index_last_two 真库
rows = defense._index_last_two()
chk(f'指数最近两行 {rows[0][0]}', len(rows) == 2 and rows[0][0] == '20260915')

print('RESULT:', 'ALL PASS' if ok else 'HAS FAIL')
