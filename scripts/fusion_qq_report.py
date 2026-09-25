#!/usr/bin/env python3
"""融合三因子评分 QQ 推送 — 读取 fusion_3f_signals 最新数据并发送"""
import sqlite3, subprocess, sys
from pathlib import Path

BASE = Path.home() / '.hermes' / 'stockdb'
STATE_DB = BASE / 'signals.db'  # v2温层

def format_fusion_report():
    conn = sqlite3.connect(str(STATE_DB))
    
    # 取最新日期
    row = conn.execute(
        "SELECT date FROM fusion_3f_signals ORDER BY REPLACE(date, '-', '') DESC LIMIT 1"
    ).fetchone()
    if not row:
        print("fusion_3f_signals 无数据")
        return None
    
    target_date = row[0]
    date_clean = target_date.replace('-', '')
    
    # 取 top 10 强买（过滤北交所和ST）
    rows = conn.execute("""
        SELECT s.stock_code, s.reg10, s.ma_decay, s.flow_alpha, 
               s.vol_adj, s.fusion_3f_score, s.signal,
               COALESCE(b.name, '') as name, COALESCE(b.industry, '') as industry
        FROM fusion_3f_signals s
        LEFT JOIN stock_basic b ON b.stock_code = s.stock_code
        WHERE REPLACE(s.date, '-', '') = ?
          AND (b.name IS NULL OR (b.name NOT LIKE '%ST%' AND b.name NOT LIKE '%退%'))
          AND (b.market IS NULL OR b.market != '北交所')
          AND s.stock_code NOT LIKE '8%'
          AND s.stock_code NOT LIKE '4%'
          AND s.stock_code NOT LIKE '92%'
        ORDER BY s.fusion_3f_score DESC, s.flow_alpha DESC, s.reg10 ASC
        LIMIT 10
    """, (date_clean,)).fetchall()
    
    # 统计
    total = conn.execute(
        "SELECT COUNT(*) FROM fusion_3f_signals WHERE REPLACE(date, '-', '') = ?",
        (date_clean,)
    ).fetchone()[0]
    
    strong_buy = conn.execute(
        "SELECT COUNT(*) FROM fusion_3f_signals WHERE REPLACE(date, '-', '') = ? AND signal = '强买'",
        (date_clean,)
    ).fetchone()[0]
    
    conn.close()
    
    if not rows:
        print(f"{target_date} 无融合评分数据")
        return None
    
    # 格式化推送消息
    y, m, d = date_clean[:4], date_clean[4:6], date_clean[6:8]
    lines = [f"🧬 {y}-{m}-{d} 三因子融合10d评分"]
    lines.append(f"全市场 {total} 只 | 强买 {strong_buy} 只")
    lines.append("")
    
    for i, r in enumerate(rows, 1):
        code, reg10, ma_decay, flow, vol, score, signal, name, ind = r
        # 简化显示：融合分、信号、代码+名称
        sig_tag = "🟢" if signal == '强买' else "🟡" if signal == '买' else "⚪" if signal == '持' else "🔴"
        lines.append(
            f"  {i:2d}. [{score:>3.0f}] {sig_tag} {code} {name:<8}"
        )
    
    lines.append("")
    lines.append("📌 三因子融合(MA衰减+资金流+波动) | 仅供参考")
    
    return '\n'.join(lines)

QQ_TARGETS = [
    'qqbot:2D719CDE220EEDA98203CE4E41B2141D',                          # 主 bot（主人）
    'qqbot2:D6CF5B5C0BFA5471D98710F2868FB49A',                         # 小rayray（家人1）
    'qqbot3:7490895ABF28C64978A51DDA23A2F6BF',                                  # 家人2（待回填，2026-08-13）
]

def send_qq(msg):
    ok = True
    for target in QQ_TARGETS:
        if 'PENDING_OPENID' in target:
            continue  # openid 未回填，跳过
        try:
            r = subprocess.run(['hermes', 'send', '-t', target, msg],
                capture_output=True, text=True, timeout=30)
            if r.returncode == 0:
                print(f"✅ QQ推送成功 ({target})")
            else:
                print(f"⚠️ QQ推送失败({target}): {r.stderr[:100]}")
                ok = False
        except Exception as e:
            print(f"⚠️ QQ推送异常({target}): {e}")
            ok = False
    
    # fallback: 打印到 stdout（cron 捕获输出）
    if not ok:
        print(msg)
    return ok

if __name__ == '__main__':
    msg = format_fusion_report()
    if msg:
        send_qq(msg)
