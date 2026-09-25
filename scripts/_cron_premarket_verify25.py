#!/usr/bin/env python3
"""步骤2.5 二次核验：对主账户持仓 + 拟点名榜内票，自算 5日涨幅/距20日新高/连涨天数/近3日累计
数据源：tushare.db(DuckDB 只读) daily 表；ledger.db 持仓成本现价。
"""
import sys, io
from pathlib import Path
BASE = Path('/Users/zantao/.hermes/stockdb')
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import duckdb, sqlite3

con = duckdb.connect(str(BASE / 'tushare.db'), read_only=True)

def tscode(c):
    if c.startswith(('688', '60', '900')):
        return c + '.SH'
    if c.startswith(('0', '3')):
        return c + '.SZ'
    if c.startswith(('8', '4')):
        return c + '.BJ'
    return c + '.SH'

def calc(code):
    tc = tscode(code)
    rows = con.execute("SELECT trade_date, close FROM daily WHERE ts_code=? ORDER BY trade_date DESC LIMIT 21", [tc]).fetchall()
    if len(rows) < 6:
        return None
    rows = rows[::-1]  # 升序
    cl = [float(r[1]) for r in rows]
    dt = [str(r[0]) for r in rows]
    last = cl[-1]
    r5 = (last / cl[-6] - 1) * 100 if len(cl) >= 6 else None
    r3 = (last / cl[-4] - 1) * 100 if len(cl) >= 4 else None
    r10 = (last / cl[-11] - 1) * 100 if len(cl) >= 11 else None
    hi20 = max(cl[-20:])
    dist_hi = (last / hi20 - 1) * 100
    up = 0
    for i in range(len(cl) - 1, 0, -1):
        if cl[i] > cl[i - 1]:
            up += 1
        else:
            break
    return dict(code=code, tc=tc, date=dt[-1], close=last, r5=r5, r3=r3, r10=r10,
                hi20=hi20, dist_hi=dist_hi, up=up)

def show(tag, codes):
    print(f'\n### {tag} ###')
    print('  代码     名称        收盘     5日%    近3日%   10日%   距20高%  连涨')
    for c, n in codes:
        r = calc(c)
        if r is None:
            print(f'  {c} {n}: 数据不足(未获取)')
            continue
        print(f"  {r['code']} {n:<10} {r['close']:>8.2f} {r['r5']:>+7.2f} {r['r3']:>+7.2f} {r['r10']:>+7.2f} {r['dist_hi']:>+7.2f}  {r['up']}天  [{r['date']}]")

# ---- 主账户持仓（ledger.db 权威源） ----
cur = sqlite3.connect(str(BASE / 'ledger.db'))
try:
    rows = cur.execute("SELECT stock_code, stock_name, shares, cost_price FROM holdings").fetchall()
except Exception:
    rows = cur.execute("SELECT * FROM holdings").fetchall()
print('### ledger.db holdings 原始 ###')
for r in rows:
    print('  ', r)
print(f'  账户现金/资产: ', cur.execute("SELECT * FROM account_balance").fetchall()[-3:])

MAIN = [('688636', '智明达'), ('301557', '常友科技'), ('301237', '和顺科技'), ('601615', '明阳智能'),
        ('688093', '世华科技'), ('301283', '聚胶股份'), ('688191', '智洋创新'), ('002454', '松芝股份'),
        ('603966', '法兰泰克'), ('688186', '广大特材'), ('603202', '天有为'), ('001332', '锡装股份'),
        ('301093', '华兰股份'), ('300658', '延江股份'), ('605598', '上海港湾'), ('301110', '青木科技')]
show('主账户持仓 16 只', MAIN)

# ---- 榜内票（按隔夜板块映射挑出来的重点） ----
AI = [('603186', '华正新材'), ('002491', '通鼎互联'), ('300328', '宜安科技'), ('688503', '聚和材料'),
      ('301186', '超达装备'), ('301662', '宏工科技'), ('600076', '康欣新材'), ('688118', '普元信息'),
      ('688607', '康众科技'), ('300864', '南大环境')]
show('AI/算力/PCB/光通信方向榜内票', AI)

METAL = [('002738', '中矿资源'), ('301500', '飞南资源'), ('603381', '永臻股份'), ('300818', '耐普矿机'),
         ('600231', '凌钢股份'), ('000990', '诚志股份')]
show('有色/大宗/矿业方向榜内票', METAL)

OTHER = [('300970', '华绿生物'), ('301575', '艾芬达'), ('300908', '仲景食品'), ('603090', '宏盛股份'),
         ('001268', '联合精密'), ('003018', '金富科技'), ('300839', '博汇股份'), ('600785', '新华百货')]
show('其余拟点评榜内票', OTHER)

NEW_ENERGY = [('002865', '钧达股份'), ('688560', '明冠新材'), ('301590', '优优绿能'), ('001269', '欧晶科技'),
              ('300176', '鸿特科技'), ('601778', '晶科科技'), ('601615', '明阳智能')]
show('新能源/光伏/锂电方向（含持仓交叉）', NEW_ENERGY)
