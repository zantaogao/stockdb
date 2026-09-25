#!/usr/bin/env python3
"""步骤2.5 修正版：用前复权价（close×adj_factor/最新adj_factor）自算位置指标。
同时输出不复权值对比，两者差异大 = 窗口内有除权，说明该票的"距20日高"是不复权口径假象。
"""
import sys, io
from pathlib import Path
BASE = Path('/Users/zantao/.hermes/stockdb')
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import duckdb

con = duckdb.connect(str(BASE / 'tushare.db'), read_only=True)

def tscode(c):
    if c.startswith(('688', '60', '900')): return c + '.SH'
    if c.startswith(('0', '3')): return c + '.SZ'
    if c.startswith(('8', '4')): return c + '.BJ'
    return c + '.SH'

def calc(code):
    tc = tscode(code)
    rows = con.execute("""
        SELECT d.trade_date, d.close, COALESCE(a.adj_factor, 1.0)
        FROM daily d LEFT JOIN adj_factor a ON a.ts_code=d.ts_code AND a.trade_date=d.trade_date
        WHERE d.ts_code=? ORDER BY d.trade_date DESC LIMIT 21""", [tc]).fetchall()
    if len(rows) < 6:
        return None
    rows = rows[::-1]
    raw = [float(r[1]) for r in rows]
    adj = [float(r[1]) * float(r[2]) for r in rows]
    last_adj = adj[-1]
    adj = [x / last_adj for x in adj]  # 前复权，最新=原始收盘
    dt = [str(r[0]) for r in rows]
    def m(series):
        last = series[-1]
        return dict(
            last=last,
            r5=(last / series[-6] - 1) * 100,
            r3=(last / series[-4] - 1) * 100,
            r10=(last / series[-11] - 1) * 100 if len(series) >= 11 else None,
            dist_hi=(last / max(series[-20:]) - 1) * 100,
            up=next((i for i in range(1, len(series)) if series[-1 - i] <= series[-2 - i]), len(series) - 1))
    # 连涨天数
    def up_days(series):
        n = 0
        for i in range(len(series) - 1, 0, -1):
            if series[i] > series[i - 1]: n += 1
            else: break
        return n
    a, r = m(adj), m(raw)
    a['up'], r['up'] = up_days(adj), up_days(raw)
    return dict(code=code, date=dt[-1], raw=r, adj=a)

def show(tag, codes):
    print(f'\n### {tag} ###')
    print('  代码     名称        收盘(前复权)  5日%   近3日%  10日%  距20高%  连涨  | 不复权距20高%  除权?')
    for c, n in codes:
        x = calc(c)
        if x is None:
            print(f'  {c} {n}: 数据不足'); continue
        a, r = x['adj'], x['raw']
        flag = ' ←除权失真' if abs(a['dist_hi'] - r['dist_hi']) > 1.0 else ''
        r10 = f"{a['r10']:>+6.2f}" if a['r10'] is not None else '   n/a'
        print(f"  {c} {n:<10} {a['last']:>9.2f} {a['r5']:>+7.2f} {a['r3']:>+7.2f} {r10} {a['dist_hi']:>+7.2f}  {a['up']}天 | {r['dist_hi']:>+7.2f}{flag}")

MAIN = [('688636', '智明达'), ('301557', '常友科技'), ('301237', '和顺科技'), ('601615', '明阳智能'),
        ('688093', '世华科技'), ('301283', '聚胶股份'), ('688191', '智洋创新'), ('002454', '松芝股份'),
        ('603966', '法兰泰克'), ('688186', '广大特材'), ('603202', '天有为'), ('001332', '锡装股份'),
        ('301093', '华兰股份'), ('300658', '延江股份'), ('605598', '上海港湾'), ('301110', '青木科技')]
show('主账户持仓 16 只', MAIN)

show('AI/算力/PCB/光通信榜内票',
     [('603186', '华正新材'), ('002491', '通鼎互联'), ('300328', '宜安科技'), ('688503', '聚和材料'),
      ('301186', '超达装备'), ('301662', '宏工科技'), ('600076', '康欣新材'), ('688118', '普元信息'),
      ('688607', '康众科技'), ('300864', '南大环境')])
show('有色/矿业榜内票',
     [('002738', '中矿资源'), ('301500', '飞南资源'), ('603381', '永臻股份'), ('300818', '耐普矿机'),
      ('600231', '凌钢股份')])
show('其余拟点评榜内票',
     [('300970', '华绿生物'), ('301575', '艾芬达'), ('300908', '仲景食品'), ('603090', '宏盛股份'),
      ('001268', '联合精密'), ('003018', '金富科技'), ('300839', '博汇股份'), ('600785', '新华百货'),
      ('002864', '盘龙药业'), ('002935', '天奥电子')])
show('新能源/光伏方向（含持仓交叉）',
     [('002865', '钧达股份'), ('688560', '明冠新材'), ('301590', '优优绿能'), ('001269', '欧晶科技'),
      ('601778', '晶科科技')])
