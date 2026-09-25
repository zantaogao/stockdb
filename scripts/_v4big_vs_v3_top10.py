#!/usr/bin/env python3
"""v4_big vs v3 三份名单对比 (2026-09-04)
v3三份: fusion_score(三模型融合) / fusion_score_cmmr(cmmr+) / fusion_center_signals(中枢版)
v4_big: shadow_v4big_scores.score
输出: 每份v3名单的top10 + 该票在v4_big里的排名 + 两份名单重合度(Spearman/交集)
"""
import sqlite3, os
D = os.path.expanduser('~/.hermes/stockdb')
sig = sqlite3.connect(f'{D}/signals.db')
D0 = '20260904'

def v3_top10(sql):
    rows = sig.execute(sql, (D0,)).fetchall()
    return [(r[0], r[1], float(r[2])) for r in rows[:10]]

v4 = sig.execute("""SELECT code, score FROM shadow_v4big_scores
    WHERE date=? ORDER BY score DESC""", (D0,)).fetchall()
v4_rank = {c: i+1 for i, (c, s) in enumerate(v4)}
v4_name = dict(sig.execute("SELECT stock_code, stock_name FROM signal_history WHERE date=?", (D0,)).fetchall())

lists = {
    '三模型融合(v3 fusion)': v3_top10("""SELECT stock_code, stock_name, fusion_score FROM signal_history
        WHERE REPLACE(date,'-','')=? AND fusion_score IS NOT NULL ORDER BY fusion_score DESC"""),
    'cmmr+(fusion_score_cmmr)': v3_top10("""SELECT stock_code, stock_name, fusion_score_cmmr FROM signal_history
        WHERE REPLACE(date,'-','')=? AND fusion_score_cmmr IS NOT NULL AND fusion_score_cmmr>0
        ORDER BY fusion_score_cmmr DESC"""),
    '中枢版(fusion_center)': v3_top10("""SELECT stock_code, stock_name, score FROM fusion_center_signals
        WHERE REPLACE(date,'-','')=? ORDER BY score DESC"""),
}

print(f"=== v4_big 自身 top10 (date={D0}, 共{len(v4)}票) ===")
for c, s in v4[:10]:
    print(f"  {v4_rank[c]:>2}. {c} {v4_name.get(c,'?'):<6} score={s:.4f}")

for name, top in lists.items():
    codes_v3 = [c for c, _, _ in top]
    v4_top10 = set(c for c, _ in v4[:10])
    inter = [c for c in codes_v3 if c in v4_top10]
    ranks = [v4_rank.get(c) for c in codes_v3]
    print(f"\n=== {name} top10 → 在v4_big里的排名 ===")
    for (c, n, s), r in zip(top, ranks):
        rr = f"v4排名#{r}" if r else "未入v4池"
        mark = " ★重合" if r and r <= 10 else ""
        print(f"  {c} {n:<6} v3分={s:.2f} → {rr}{mark}")
    print(f"  top10重合数: {len(inter)}/10  |  v3top10在v4里的平均排名: "
          f"{sum(r for r in ranks if r)/max(1,len([r for r in ranks if r])):.1f}")