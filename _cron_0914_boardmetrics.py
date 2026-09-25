#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""夜报技术面口径：四榜共40票的 MA20偏离/布林位置/5日涨幅/距20日新高/量能比"""
import os
import duckdb

os.chdir(os.path.expanduser('~/.hermes/stockdb'))

BOARDS = {
    '三模型融合': ['001332', '603966', '688377', '688576', '688081', '688191', '300812', '301413', '301237', '300680'],
    '10d独立': ['600076', '300328', '603090', '688073', '600785', '300864', '688062', '002346', '002491', '300839'],
    '中枢版': ['301103', '600658', '000599', '600322', '688733', '301032', '300158', '600116', '300318', '301508'],
    '中枢版+三模型': ['603811', '301338', '688021', '300274', '300176', '002864', '300971', '688410', '300724', '301601'],
}

# 板块归属（从 draft 拿名字/板块）
con = duckdb.connect('tushare.db', read_only=True)

def metrics(code):
    ts = code
    # 后缀猜测
    cands = []
    if code.startswith('6'):
        cands = [code + '.SH']
    elif code.startswith(('0', '3')):
        cands = [code + '.SZ']
    else:
        cands = [code + '.SH', code + '.SZ']
    ts = cands[0]
    rows = con.execute("""
        SELECT trade_date, close, vol FROM daily WHERE ts_code=? ORDER BY trade_date DESC LIMIT 30
    """, [ts]).fetchall()
    if not rows:
        return None
    closes = [r[1] for r in rows]
    vols = [r[2] for r in rows]
    px = closes[0]
    ma20 = sum(closes[:20]) / 20
    dev20 = (px / ma20 - 1) * 100
    sd = (sum((x - ma20) ** 2 for x in closes[:20]) / 20) ** 0.5
    up, lo = ma20 + 2 * sd, ma20 - 2 * sd
    bpos = (px - lo) / (up - lo) * 100 if up > lo else 50.0
    r5 = (px / closes[5] - 1) * 100 if len(closes) > 5 else None
    r10 = (px / closes[10] - 1) * 100 if len(closes) > 10 else None
    hi20 = max(closes[:20])
    d_hi20 = (px / hi20 - 1) * 100
    v5 = sum(vols[1:6]) / 5 if len(vols) > 5 else None
    vratio = vols[0] / v5 if v5 else None
    ma10 = sum(closes[:10]) / 10
    return dict(px=px, ma20=ma20, dev20=dev20, bpos=bpos, boll_up=up, boll_lo=lo,
                r5=r5, r10=r10, hi20=hi20, d_hi20=d_hi20, vratio=vratio, ma10=ma10, n=len(closes))

names = {}
try:
    sb = con.execute("SELECT ts_code, name FROM stock_basic").fetchall()
    names = {r[0]: r[1] for r in sb}
except Exception as e:
    print('stock_basic ERR', e)

for b, codes in BOARDS.items():
    print('=' * 55)
    print('BOARD', b)
    for c in codes:
        ts = c + ('.SH' if c.startswith('6') else '.SZ')
        m = metrics(c)
        nm = names.get(ts, '?')
        if not m:
            print(f"  {nm} {c}: 无数据")
            continue
        print(f"  {nm} {c}: 价{m['px']:.2f} MA10={m['ma10']:.2f} MA20={m['ma20']:.2f} 偏MA20={m['dev20']:+.1f}% "
              f"布林位={m['bpos']:.0f}%(上{m['boll_up']:.2f}/下{m['boll_lo']:.2f}) 5日={m['r5']:+.1f}% 10日={m['r10']:+.1f}% "
              f"距20日高={m['d_hi20']:+.1f}%(高{m['hi20']:.2f}) 量比={m['vratio']:.2f}")
con.close()
