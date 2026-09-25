#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""汇率/美债观察哨：每日收盘后拉 4 项宏观情绪指标入库 signals.db.fx_sentinel_daily
数据源全部国内直连（不动梯子）：
  - 央行中间价/中行折算价: akshare currency_boc_sina（中行牌价页）
  - 在岸人民币即期:        新浪 hq.sinajs.cn fx_susdcny
  - 美债10Y/2Y+中债10Y:    akshare bond_zh_us_rate（东财源）
  - 美元指数DXY:           东财 push2 secid=100.UDI（f43/100）
口径：date=自然日YYYYMMDD；USDCNY中间价单位=元/100美元（沿用中行6.7787→677.87）。
增量：只拉库里最新date之后的；中间价上午9:15发布，16:50链跑到时必有。
"""
import os, sys, json, sqlite3, time
import requests

BASE = os.path.expanduser('~/.hermes/stockdb')
DB = os.path.join(BASE, 'signals.db')
HEAD = {'Referer': 'https://finance.sina.com.cn', 'User-Agent': 'Mozilla/5.0'}

def _retry(fn, n=3, sleep=3):
    last = None
    for i in range(n):
        try:
            return fn()
        except Exception as e:
            last = e
            time.sleep(sleep * (i + 1))
    raise last

conn = sqlite3.connect(DB)
conn.execute("""CREATE TABLE IF NOT EXISTS fx_sentinel_daily (
    date TEXT PRIMARY KEY,        -- YYYYMMDD 自然日
    pmi_mid REAL,                 -- 央行中间价 元/100美元
    usdcny REAL,                  -- 在岸即期（新浪，元）
    cn10y REAL, us10y REAL, us2y REAL,  -- 国债收益率 %
    us_cn_spread REAL,            -- 美10Y - 中10Y（bp 用 %差值，正=倒挂加深方向）
    dxy REAL,                     -- 美元指数
    computed_at TEXT DEFAULT (datetime('now','localtime'))
)""")
conn.commit()
latest = conn.execute("SELECT MAX(date) FROM fx_sentinel_daily").fetchone()[0] or '00000000'

rows = {}  # date -> dict

# 1) 中行牌价（中间价）+ 2) 在岸即期 —— 拉近30天窗口容忍周末缺口
import akshare as ak
from datetime import date, timedelta
end = date.today().strftime('%Y%m%d')
start = (date.today() - timedelta(days=30)).strftime('%Y%m%d')
boc = _retry(lambda: ak.currency_boc_sina(symbol="美元", start_date=start, end_date=end))
for _, r in boc.iterrows():
    d = str(r['日期']).replace('-', '')
    mid = r.get('央行中间价')
    if mid == mid and mid is not None:  # 非NaN
        rows.setdefault(d, {})['pmi_mid'] = float(mid)

# 在岸即期 + 离岸CNH（新浪只有当日快照，写快照自带日期）
try:
    t = _retry(lambda: requests.get('https://hq.sinajs.cn/list=fx_susdcny,fx_susdcnh', headers=HEAD, timeout=10).text)
    for seg in t.split('var hq_str_')[1:]:
        name, body = seg.split('=', 1)
        parts = body.split('"')[1].split(',')
        if 'susdcnh' in name.lower():
            key, vi = 'usdcnh', 8   # 离岸
        elif 'susdcny' in name.lower():
            key, vi = 'usdcny', 8   # 在岸
        else:
            continue
        if len(parts) > vi and parts[vi] not in ('', '0.0000', '0.00000'):
            d = parts[-1].replace('-', '') if parts[-1][:2] == '20' else date.today().strftime('%Y%m%d')
            rows.setdefault(d, {})[key] = float(parts[vi])
except Exception as e:
    print(f'⚠️ 在岸/离岸即期拉取失败: {e!r}', file=sys.stderr)

# 3) 中美国债收益率（东财，bond_zh_us_rate 支持 start_date 全量再过滤）
ust = _retry(lambda: ak.bond_zh_us_rate(start_date=start))
for _, r in ust.iterrows():
    d = str(r['日期']).replace('-', '')[:10]
    cn, u10, u2 = r.get('中国国债收益率10年'), r.get('美国国债收益率10年'), r.get('美国国债收益率2年')
    rec = {}
    if cn == cn and cn is not None: rec['cn10y'] = float(cn)
    if u10 == u10 and u10 is not None: rec['us10y'] = float(u10)
    if u2 == u2 and u2 is not None: rec['us2y'] = float(u2)
    if rec.get('cn10y') is not None and rec.get('us10y') is not None:
        rec['us_cn_spread'] = round(rec['us10y'] - rec['cn10y'], 4)
    if rec:
        rows.setdefault(d, {}).update({k: v for k, v in rec.items() if k not in rows.get(d, {})})

# 4) 美元指数（东财 push2 实时，f43/100；历史K线接口对100.UDI不可用，只记当日快照）
try:
    j = _retry(lambda: requests.get(
        'https://push2.eastmoney.com/api/qt/stock/get',
        params={'secid': '100.UDI', 'fields': 'f43,f86'}, timeout=10).json())
    v = (j.get('data') or {}).get('f43')
    ts = (j.get('data') or {}).get('f86')
    if v:
        d = time.strftime('%Y%m%d', time.localtime(int(ts))) if ts else date.today().strftime('%Y%m%d')
        rows.setdefault(d, {})['dxy'] = v / 100.0
except Exception as e:
    print(f'⚠️ DXY拉取失败: {e!r}', file=sys.stderr)

n = 0
for d in sorted(rows):
    if d <= latest or d > end:
        continue
    rec = rows[d]
    if len(rec) < 2:
        continue  # 只有一两项的边角日不写（周末噪音）
    conn.execute("""INSERT OR REPLACE INTO fx_sentinel_daily
        (date,pmi_mid,usdcny,usdcnh,cn10y,us10y,us2y,us_cn_spread,dxy) VALUES (?,?,?,?,?,?,?,?,?)""",
        (d, rec.get('pmi_mid'), rec.get('usdcny'), rec.get('usdcnh'), rec.get('cn10y'),
         rec.get('us10y'), rec.get('us2y'), rec.get('us_cn_spread'), rec.get('dxy')))
    n += 1
conn.commit()

hist = conn.execute("SELECT date,pmi_mid,us10y,us_cn_spread,dxy FROM fx_sentinel_daily ORDER BY date DESC LIMIT 5").fetchall()
print(f"汇率哨 新增{n}日 累计{conn.execute('SELECT COUNT(*) FROM fx_sentinel_daily').fetchone()[0]}日")
for h in hist:
    print(' | '.join(str(x) for x in h))
# 异动提醒（相对5日均值）
import statistics as st_
last5 = conn.execute("SELECT us10y,us_cn_spread,dxy,pmi_mid FROM fx_sentinel_daily ORDER BY date DESC LIMIT 6").fetchall()
if len(last5) >= 6:
    a = last5[0]; base = last5[1:]
    alerts = []
    for i, name in [(0, '美债10Y'), (1, '中美利差'), (2, '美元指数')]:
        if a[i] is not None:
            m = st_.mean(r[i] for r in base if r[i] is not None)
            sd = st_.pstdev([r[i] for r in base if r[i] is not None]) or 1e-9
            if abs(a[i] - m) / sd > 2:
                alerts.append(f"{name} 单日异动 {a[i]-m:+.3f} (2σ)")
    if alerts:
        print('🚨 ' + '; '.join(alerts))