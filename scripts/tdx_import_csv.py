#!/usr/bin/env python3
"""导入 PC 导出的分钟 CSV → tdx_intraday_feat（2026-08-08 主数据源切换）
数据源: PC tdx_stock_data.db（mootdx 自动更新 cron 15:30, Gateway 守护）
CSV 格式: code,market,datetime(YYYYMMDD HHMM),open,high,low,close,amount,volume
用法: python3 -B scripts/tdx_import_csv.py [min1.csv] [min5.csv]
"""
import sys, csv, sqlite3
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
sys.path.insert(0, str(BASE / 'scripts'))

import importlib.util
spec = importlib.util.spec_from_file_location('tdxagg', str(BASE / 'scripts' / 'tdx_intraday_agg.py'))
tdxagg = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tdxagg)
import pandas as pd

CSV1 = sys.argv[1] if len(sys.argv) > 1 else '/tmp/tdx_min1_recent.csv'
# ⚠️ 2026-09-24 修复（两台同步，M2 同日已改）：min5 **默认不再参与聚合**。
#    原默认值 /tmp/tdx_min5_recent.csv 会让 tdx_sync.sh 即使少传参数也导入 min5：
#    它对同一批日期 DELETE-by-date 后只插回个位数行（agg_day 要求 len(df)>=100，
#    5 分钟线一天仅 48 根）→ 把 min1 写入的当日全市场 ~5,200 行整段删掉（M2 自 07-23 起每天只剩 4 行）。
CSV5 = sys.argv[2] if len(sys.argv) > 2 else None
STATE_DB = str(BASE / 'signals.db')  # v2温层

def import_csv(fn):
    if not fn:
        print('  ⏭ min5 聚合已跳过（2026-09-24 修复：避免 DELETE-by-date 清掉 min1 的全市场数据）')
        return 0
    if not Path(fn).exists() or Path(fn).stat().st_size == 0:
        print(f'  ⏭ {fn} 不存在或为空')
        return 0
    df = pd.read_csv(fn, dtype={'code': str})
    if df.empty:
        print(f'  ⏭ {fn} 无数据行')
        return 0
    df['date'] = df['datetime'].str[:8].astype(int)
    df['tm'] = df['datetime'].str[9:11].astype(int) * 60 + df['datetime'].str[11:13].astype(int)
    df = df.rename(columns={'volume': 'vol'})
    df = df[(df['tm'] >= 9 * 60 + 31) & (df['tm'] <= 15 * 60)]
    rows = []
    for (code, date), grp in df.groupby(['code', 'date']):
        r = tdxagg.agg_day(grp.reset_index(drop=True))
        if r:
            r['code'] = code
            r['market'] = 'sh' if str(code).startswith(('6', '9')) else 'sz'
            rows.append(r)
    if not rows:
        print(f'  ⏭ {fn} 聚合 0 行')
        return 0
    out = pd.DataFrame(rows)
    s = sqlite3.connect(STATE_DB)
    s.execute("""CREATE TABLE IF NOT EXISTS tdx_intraday_feat (
        date INTEGER, code TEXT, market TEXT, n_bars INTEGER,
        open30_ret REAL, tail30_ret REAL, vwap_dev REAL,
        rv_1m REAL, amp_intra REAL, vol_dist_am REAL, vol_dist_tail REAL,
        PRIMARY KEY (date, code))""")
    # 2026-09-02 新增列（tail5急拉+尾笔集中度），已有库自动补列
    _have = {r[1] for r in s.execute("PRAGMA table_info(tdx_intraday_feat)").fetchall()}
    for _col in ('tail5_ret', 'last_vol_share'):
        if _col not in _have:
            s.execute(f"ALTER TABLE tdx_intraday_feat ADD COLUMN {_col} REAL")
    # ⚠️ 2026-09-24 纵深守卫：同一日期若库里已有大量行、而本次聚合只有零头 → 跳过该日期
    #    （防"小批量覆盖大批量"重演：本次 min5 事故就是这么清空全市场数据的）
    COLS = ['date', 'code', 'market', 'n_bars', 'open30_ret', 'tail30_ret',
            'vwap_dev', 'rv_1m', 'amp_intra', 'vol_dist_am', 'vol_dist_tail',
            'tail5_ret', 'last_vol_share']
    skipped = []
    for d in out['date'].unique():
        d = int(d)
        sub = out[out['date'] == d]
        n_new = len(sub)
        have = s.execute("SELECT COUNT(*) FROM tdx_intraday_feat WHERE date=?", (d,)).fetchone()[0]
        if have > 0 and n_new < max(500, have // 2):
            skipped.append(d)
            print(f'  ⚠️ {d}: 本次聚合仅 {n_new} 行，库中已有 {have} 行 → 跳过写入，保留原数据')
            continue
        s.execute("DELETE FROM tdx_intraday_feat WHERE date=?", (d,))
        s.executemany(
            "INSERT OR REPLACE INTO tdx_intraday_feat "
            "(date,code,market,n_bars,open30_ret,tail30_ret,vwap_dev,rv_1m,amp_intra,vol_dist_am,vol_dist_tail,tail5_ret,last_vol_share) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            sub[COLS].values.tolist())
    s.commit()
    s.close()
    print(f'  ✅ {fn}: {len(out)} 行 → tdx_intraday_feat（日期 {sorted(out["date"].unique())[-1]} 起）'
          + (f'，跳过 {len(skipped)} 个日期 {skipped}' if skipped else ''))
    return len(out)

n1 = import_csv(CSV1)
n5 = import_csv(CSV5)
print(f'导入完成: min1 {n1} 行, min5 {n5} 行')
