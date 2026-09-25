#!/usr/bin/env python3
"""三模型窗口期 IC 计算+回填（2026-08-05）
对已到期的信号日，用全截面数据算真窗口 IC：
  ic_reg10_w10 = corr(reg10分, T→T+10收益)    10d模型 vs 10日窗口
  ic_reg20_w20 = corr(reg20分, T→T+20收益)    20d模型 vs 20日窗口
  ic_reg40_w40 = corr(reg40分, T→T+40收益)    40d模型 vs 40日窗口
  ic_fusion_wN = corr(融合分, T→T+N收益)      融合分 vs 各窗口（对照）
窗口IC与模型预测窗口匹配，才是"模型真实预测力"的验证。
写 ic_window 表（signal_date 主键），每天回填已到期日，幂等。
"""
import sqlite3, duckdb, numpy as np
from pathlib import Path
from datetime import datetime

BASE = Path.home() / '.hermes' / 'stockdb'
STATE_DB = BASE / 'signals.db'  # v2温层
TUSHARE_DB = BASE / 'tushare.db'

def code_to_ts_code(code):
    s = str(code)
    if s.startswith(('600', '601', '602', '603', '604', '605', '688', '689')):
        return f'{s}.SH'
    return f'{s}.SZ'

def main():
    state = sqlite3.connect(str(STATE_DB), timeout=30)
    tushare = duckdb.connect(str(TUSHARE_DB), read_only=True)

    # 建表
    state.execute("""
        CREATE TABLE IF NOT EXISTS ic_window (
            signal_date TEXT PRIMARY KEY,
            calc_date TEXT,
            n DOUBLE,
            ic_reg10_w10 DOUBLE,
            ic_reg20_w20 DOUBLE,
            ic_reg40_w40 DOUBLE,
            ic_fusion_w10 DOUBLE,
            ic_fusion_w20 DOUBLE,
            ic_fusion_w40 DOUBLE,
            ic_3f_w10 DOUBLE,
            ic_cmmr_w10 DOUBLE,
            ic_cmmrf_w10 DOUBLE,
            ic_center_w10 DOUBLE,
            ic_dual_w10 DOUBLE,
            fwd10_top DOUBLE,
            fwd20_top DOUBLE,
            fwd40_top DOUBLE,
            fwd10_top_3f DOUBLE,
            fwd10_top_cmmr DOUBLE,
            fwd20_top_cmmr DOUBLE,
            fwd10_top_cmmrf DOUBLE,
            fwd20_top_cmmrf DOUBLE,
            fwd40_top_cmmrf DOUBLE,
            fwd10_top_center DOUBLE,
            fwd10_top_dual DOUBLE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    # 自愈防御：CREATE IF NOT EXISTS 对已存在表不加新列（2026-08-07 踩坑），缺列则 ALTER
    have_cols = {r[1] for r in state.execute("PRAGMA table_info(ic_window)").fetchall()}
    for c in ('fwd10_top_3f', 'fwd10_top_cmmr', 'fwd20_top_cmmr', 'fwd10_top_cmmrf', 'fwd20_top_cmmrf', 'fwd40_top_cmmrf', 'fwd10_top_center', 'fwd10_top_dual', 'ic_dual_w10',
              'fwd10_top_main', 'fwd20_top_main', 'fwd40_top_main'):
        if c not in have_cols:
            state.execute(f"ALTER TABLE ic_window ADD COLUMN {c} DOUBLE")
            print(f'  [自愈] ic_window 补列 {c}')
    state.commit()
    # 2026-08-05: 旧表加策略账户信号列（ALTER 兼容）
    for col in ('ic_3f_w10', 'ic_cmmr_w10', 'ic_cmmrf_w10', 'ic_center_w10'):
        try:
            state.execute(f"ALTER TABLE ic_window ADD COLUMN {col} DOUBLE")
            print(f"  ✅ ic_window 增加列 {col}")
        except Exception:
            pass

    # 交易日历
    trading_days = [str(r[0]) for r in tushare.execute(
        "SELECT DISTINCT trade_date FROM daily WHERE ts_code LIKE '%.SH' ORDER BY trade_date").fetchall()]
    td_idx = {d: i for i, d in enumerate(trading_days)}
    last_td = trading_days[-1]
    print(f'交易日: {len(trading_days)} ({trading_days[0]}~{last_td})')

    # 加载全量 close（内存 dict：1.5 万条/日 × 5500 只 ≈ 1500万 条，太大；改用按日查询）
    # 优化：只对信号日涉及的股票和窗口终点日查询

    # 所有信号日（2026-08-08: 过滤失真期——8/1 前评分管线因子全0+7/30信号复制, ic_daily 失真行已删,
    # 此处显式 >= 20260803 双重防护, 防未来误回填失真期行污染 ic_window）
    sig_dates = [str(r[0]).replace('-', '') for r in state.execute(
        "SELECT DISTINCT REPLACE(date,'-','') FROM signal_history WHERE REPLACE(date,'-','') IN "
        "(SELECT REPLACE(signal_date,'-','') FROM ic_daily) AND REPLACE(date,'-','') >= '20260803' ORDER BY 1").fetchall()]
    print(f'信号日: {len(sig_dates)} 天')

    # 需要回填的行：ic_window 不存在 或 fwd10_top IS NULL 且已到期
    done = {str(r[0]) for r in state.execute("SELECT signal_date FROM ic_window").fetchall()}

    # ST/北交所过滤（2026-08-07 与策略账户执行侧 get_signal_targets 同口径，top10 验证列用）
    bad_codes = set()
    try:
        for r in state.execute("SELECT stock_code, name, market FROM stock_basic").fetchall():
            sc, nm, mk = r
            if (nm and ('ST' in nm or '退' in nm)) or mk == '北交所' or str(sc).startswith(('8', '4', '92')):
                bad_codes.add(sc)
    except Exception:
        pass

    updated = 0
    for sd in sig_dates:
        if sd not in td_idx:
            continue
        i0 = td_idx[sd]
        # 需要至少 10 日窗口到期才算（w10 是最短窗口）
        if i0 + 10 >= len(trading_days):
            continue
        # 已算过且含 w40 的跳过（2026-08-23 改：已有行也须补 fwd20/fwd40_top_cmmrf 新列——
        # fwd20 已算且（fwd40 已算 或 w40 未到期）才 skip；w40 到期后仍 NULL 则重算补上。
        # 2026-08-28 改：加 main top10 三列检查（fwd10_top_main NULL = 历史行未回填过 → 不 skip 重算））
        if sd in done:
            row = state.execute("SELECT ic_reg40_w40, fwd40_top, fwd20_top_cmmrf, fwd40_top_cmmrf, fwd10_top_main, fwd20_top_cmmr FROM ic_window WHERE signal_date=?", (sd,)).fetchone()
            if row and row[0] is not None and row[2] is not None and row[4] is not None and row[5] is not None:
                if row[3] is not None or (i0 + 40 >= len(trading_days)):
                    continue

        # 取该日全量评分（主模型 + 策略账户信号源）
        sig = state.execute(
            "SELECT stock_code, reg10, reg20, reg40, fusion_score, cmmr_score, fusion_score_cmmr FROM signal_history "
            "WHERE REPLACE(date,'-','')=?", (sd,)).fetchall()
        # fusion_3f_score（独立表，按股票对齐；signal 列用于强买过滤——2026-08-07 与策略账户执行侧 get_signal_targets 同口径）
        # 2026-08-08: 加 flow_alpha——执行侧 ORDER BY fusion_3f_score DESC, flow_alpha DESC 二级排序，
        # 满分(100)同分时排序键必须与执行侧一致，否则验证的 top10 ≠ 实盘执行的 top10
        f3f_rows = state.execute(
            "SELECT stock_code, fusion_3f_score, flow_alpha, signal FROM fusion_3f_signals "
            "WHERE REPLACE(date,'-','')=? AND fusion_3f_score IS NOT NULL", (sd,)).fetchall()
        f3f = {r[0]: r[1] for r in f3f_rows}
        f3f_flow = {r[0]: (r[2] or 0.0) for r in f3f_rows}
        f3f_strong = {r[0] for r in f3f_rows if r[3] == '强买'}
        # 中枢版 score（独立表，2026-08-06 新增；signal 列同口径）
        center_rows = state.execute(
            "SELECT stock_code, score, signal FROM fusion_center_signals "
            "WHERE REPLACE(date,'-','')=? AND score IS NOT NULL", (sd,)).fetchall()
        center = {r[0]: r[1] for r in center_rows}
        center_strong = {r[0] for r in center_rows if r[2] == '强买'}
        if not sig:
            continue

        # 各窗口终点日
        ends = {}
        for off in (10, 20, 40):
            if i0 + off < len(trading_days):
                ends[off] = trading_days[i0 + off]
        if 10 not in ends:
            continue

        # 批量取价：信号日 + 各终点日 的所有涉及股票
        codes = [code_to_ts_code(c) for c, *_ in sig]
        uniq_codes = list(dict.fromkeys(codes))
        ph = ','.join(['?'] * len(uniq_codes))
        dates_needed = [sd] + list(ends.values())
        px = {}  # (date, ts_code) -> close
        for d in dates_needed:
            rows = tushare.execute(
                f"SELECT ts_code, close FROM daily WHERE trade_date=? AND ts_code IN ({ph})",
                (d,) + tuple(uniq_codes)).fetchall()
            for tc, c in rows:
                px[(d, tc)] = float(c)

        # 组装每只股票各窗口收益
        recs = {'code': [], 'reg10': [], 'reg20': [], 'reg40': [], 'fusion': [],
                'cmmr': [], 'cmmrf': [], 'f3f': [], 'center': []}
        rets = {off: [] for off in ends}
        for row, tc in zip(sig, codes):
            code, r10, r20, r40, fus, cmmr, cmmrf = row
            p0 = px.get((sd, tc))
            if not p0 or p0 <= 0:
                continue
            ok = True
            for off in ends:
                pn = px.get((ends[off], tc))
                if not pn or pn <= 0:
                    ok = False
                    break
            if not ok:
                continue
            recs['code'].append(code)
            rets[10].append((px[(ends[10], tc)] / p0 - 1) * 100)
            recs['reg10'].append(float(r10) if r10 is not None else 0.0)
            recs['reg20'].append(float(r20) if r20 is not None else 0.0)
            recs['reg40'].append(float(r40) if r40 is not None else 0.0)
            recs['fusion'].append(float(fus) if fus is not None else 0.0)
            recs['cmmr'].append(float(cmmr) if cmmr is not None else 0.0)
            recs['cmmrf'].append(float(cmmrf) if cmmrf is not None else 0.0)
            recs['f3f'].append(float(f3f.get(code, 0.0)))
            recs['center'].append(float(center.get(code, 0.0)))
            if 20 in ends:
                rets[20].append((px[(ends[20], tc)] / p0 - 1) * 100)
            if 40 in ends:
                rets[40].append((px[(ends[40], tc)] / p0 - 1) * 100)

        n = len(recs['fusion'])
        if n < 100:
            print(f'  ⏭ {sd}: 样本不足 {n}')
            continue

        # fusion_dual 组合分（2026-08-10 新增：0.5*pct(fusion_3f)+0.5*pct(fusion_score)，
        # 与策略账户 get_signal_targets fusion_dual 同口径——rank 百分位等权）
        f3_vals = np.array(recs['f3f'], dtype=float)
        md_vals = np.array(recs['fusion'], dtype=float)
        f3_rank = np.argsort(np.argsort(f3_vals)) + 1
        md_rank = np.argsort(np.argsort(md_vals)) + 1
        recs['dual'] = [0.5 * f3_rank[i] / n * 100 + 0.5 * md_rank[i] / n * 100
                        for i in range(n)]

        def corr(a, b):
            if len(a) != len(b) or len(a) < 10:
                return None
            return round(float(np.corrcoef(np.array(a), np.array(b))[0, 1]), 4)

        ic_reg10_w10 = corr(recs['reg10'], rets[10])
        ic_reg20_w20 = corr(recs['reg20'], rets[20]) if 20 in rets else None
        ic_reg40_w40 = corr(recs['reg40'], rets[40]) if 40 in rets else None
        ic_fusion_w10 = corr(recs['fusion'], rets[10])
        ic_fusion_w20 = corr(recs['fusion'], rets[20]) if 20 in rets else None
        ic_fusion_w40 = corr(recs['fusion'], rets[40]) if 40 in rets else None
        # 策略账户信号源（10日窗口=执行窗口，2026-08-05 新增）
        ic_3f_w10 = corr(recs['f3f'], rets[10])
        ic_cmmr_w10 = corr(recs['cmmr'], rets[10])
        ic_cmmrf_w10 = corr(recs['cmmrf'], rets[10])
        # 中枢版（2026-08-06 新增，10日窗口=验证窗口）
        ic_center_w10 = corr(recs['center'], rets[10])
        # fusion_dual 组合（2026-08-10 新增，10日窗口=执行窗口）
        ic_dual_w10 = corr(recs['dual'], rets[10])

        # top10 等权（融合分）
        fused = sorted(zip(recs['fusion'], rets[10]), key=lambda x: x[0], reverse=True)
        top_n = max(1, n // 10)
        top_rets10 = [r for _, r in fused[:top_n]]
        fwd10_top = round(sum(top_rets10) / len(top_rets10), 3) if top_rets10 else None
        fused20 = sorted(zip(recs['fusion'], rets.get(20, [])), key=lambda x: x[0], reverse=True) if 20 in rets else []
        top20 = [r for _, r in fused20[:top_n]] if fused20 else []
        fwd20_top = round(sum(top20) / len(top20), 3) if top20 else None
        fused40 = sorted(zip(recs['fusion'], rets.get(40, [])), key=lambda x: x[0], reverse=True) if 40 in ends else []
        top40 = [r for _, r in fused40[:top_n]] if fused40 else []
        fwd40_top = round(sum(top40) / len(top40), 3) if top40 else None

        # 策略账户信号源 top10（真 10 只等权，2026-08-07 新增——与执行侧 get_signal_targets 同口径：
        # 强买集合内排序 / cmmr>0 / cmmrf p85 / 中枢强买，均过滤 ST/北交所）
        rec_codes = recs.get('code', [])

        def top10_ret(score_list, strong_set=None, positive=False, pct85=False, tiebreak=None, rets_off=10):
            items = []
            for code, sc, r in zip(rec_codes, score_list, rets[rets_off]):
                if code in bad_codes:
                    continue
                if strong_set is not None and code not in strong_set:
                    continue
                if positive and not (sc and sc > 0):
                    continue
                items.append((code, sc, r))
            if pct85 and items:  # cmmrf 执行口径：>0 的分数取 p85 以上
                scs = sorted(sc for _, sc, _ in items)
                th = scs[int(len(scs) * 0.85)]
                items = [(c, sc, r) for c, sc, r in items if sc >= th]
            # 2026-08-08: tiebreak（flow_alpha）与执行侧 ORDER BY fusion_3f_score DESC, flow_alpha DESC 对齐；
            # 满分同分时不再取 rowid 顺序，验证的 top10 = 实盘执行的 top10
            if tiebreak:
                items.sort(key=lambda x: (x[1], tiebreak.get(x[0], 0.0)), reverse=True)
            else:
                items.sort(key=lambda x: x[1], reverse=True)
            top = [r for _, _, r in items[:10]]
            return round(sum(top) / len(top), 3) if top else None

        fwd10_top_3f = top10_ret(recs['f3f'], strong_set=f3f_strong, tiebreak=f3f_flow)
        fwd10_top_cmmr = top10_ret(recs['cmmr'], positive=True)
        # CMMR 20日窗口 top10（2026-09-06 新增：观察列，等权口径同10d，不改执行）
        fwd20_top_cmmr = top10_ret(recs['cmmr'], positive=True, rets_off=20) if 20 in rets else None
        fwd10_top_cmmrf = top10_ret(recs['cmmrf'], positive=True, pct85=True)
        # CMMR+ 20/40 日窗口 top10（2026-08-23 新增：观察列，不改执行；验证窗口错配是否值得延重评窗口）
        fwd20_top_cmmrf = top10_ret(recs['cmmrf'], positive=True, pct85=True, rets_off=20) if 20 in rets else None
        fwd40_top_cmmrf = top10_ret(recs['cmmrf'], positive=True, pct85=True, rets_off=40) if 40 in rets else None
        fwd10_top_center = top10_ret(recs['center'], strong_set=center_strong)
        # fusion_dual 组合分 top10（2026-08-10 新增：组合分 DESC 无二级排序，与执行侧一致；ST/北交所已滤）
        fwd10_top_dual = top10_ret(recs['dual'])
        # 主账户三模型 top10（2026-08-28 新增：fusion_score DESC 前10只等权，与主账户买入执行同口径——
        # 主账户 watchlist=融合分百分位 top10%，这里取其头部10只；ST/北交所过滤与其他账户一致）
        fwd10_top_main = top10_ret(recs['fusion'])
        fwd20_top_main = top10_ret(recs['fusion'], rets_off=20) if 20 in rets else None
        fwd40_top_main = top10_ret(recs['fusion'], rets_off=40) if 40 in rets else None

        state.execute("""
            INSERT OR REPLACE INTO ic_window
            (signal_date, calc_date, n, ic_reg10_w10, ic_reg20_w20, ic_reg40_w40,
             ic_fusion_w10, ic_fusion_w20, ic_fusion_w40,
             ic_3f_w10, ic_cmmr_w10, ic_cmmrf_w10, ic_center_w10, ic_dual_w10,
             fwd10_top, fwd20_top, fwd40_top,
             fwd10_top_3f, fwd10_top_cmmr, fwd20_top_cmmr, fwd10_top_cmmrf, fwd20_top_cmmrf, fwd40_top_cmmrf,
             fwd10_top_center, fwd10_top_dual, fwd10_top_main, fwd20_top_main, fwd40_top_main)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (sd, datetime.now().strftime('%Y%m%d'), n, ic_reg10_w10, ic_reg20_w20, ic_reg40_w40,
              ic_fusion_w10, ic_fusion_w20, ic_fusion_w40,
              ic_3f_w10, ic_cmmr_w10, ic_cmmrf_w10, ic_center_w10, ic_dual_w10,
              fwd10_top, fwd20_top, fwd40_top,
              fwd10_top_3f, fwd10_top_cmmr, fwd20_top_cmmr, fwd10_top_cmmrf, fwd20_top_cmmrf, fwd40_top_cmmrf,
              fwd10_top_center, fwd10_top_dual, fwd10_top_main, fwd20_top_main, fwd40_top_main))
        updated += 1
        print(f'  ✅ {sd}: reg10w10={ic_reg10_w10} reg20w20={ic_reg20_w20} reg40w40={ic_reg40_w40} '
              f'fusion_w10={ic_fusion_w10} w20={ic_fusion_w20} w40={ic_fusion_w40} '
              f'3f_w10={ic_3f_w10} cmmr_w10={ic_cmmr_w10} cmmrf_w10={ic_cmmrf_w10} center_w10={ic_center_w10} dual_w10={ic_dual_w10} fwd10top={fwd10_top}')

    state.commit()
    state.close()
    tushare.close()
    print(f'\n✅ ic_window 回填完成: {updated} 行（已到期信号日的真窗口 IC）')

if __name__ == '__main__':
    main()
