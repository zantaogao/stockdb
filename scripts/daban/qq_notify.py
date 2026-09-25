"""
打板信号 QQ 通知模块
====================
读取 signal_history 里的新信号，格式化成消息发到QQ。

用法：
    from scripts.daban.qq_notify import notify_qq
    notify_qq(signals_list)        # signals_list = [{'code': '000001', 'name': '平安银行', ...}]
    
或直接调：
    python3 -m scripts.daban.qq_notify --test
"""

import json, os, urllib.request, sys


def format_signal_msg(signals):
    """格式化打板信号消息"""
    if not signals:
        return "无新信号"
    
    from datetime import datetime
    lines = [f"⚡ 盘中打板信号 ({datetime.now().strftime('%H:%M')})"]
    lines.append(f"📊 今日 {len(signals)} 只信号")
    lines.append("")
    
    for i, s in enumerate(signals[:10], 1):
        code = s.get('code', '') or s.get('stock_code', '')
        name = s.get('name', '') or s.get('stock_name', '')
        score = s.get('score', s.get('final_score', 0)) or 0
        pct = s.get('change_pct', s.get('pct_chg', 0)) or 0
        price = s.get('current_price', 0) or 0
        scan_time = s.get('scan_time', '') or ''
        
        if 'ST' in str(name) or '*' in str(name):
            continue
            
        tag = s.get('industry', '')
        tag_label = '方案B' if 'B' in tag else '方案A'
        
        reasons_str = ''
        if 'reasons' in s and s['reasons']:
            reasons_str = ' | '.join(s['reasons'])
        
        # 清理名称里的标签
        clean_name = name.replace('[池]', '').replace('[打]', '')
        
        time_str = f' {scan_time}' if scan_time else ''
        price_str = f' @{price:.2f}' if price > 0 else ''
        
        lines.append(f"  [{score:>3.0f}] {code} {clean_name:<8} +{pct:.1f}%{time_str}{price_str} {tag_label}")
        if reasons_str:
            lines.append(f"     {reasons_str}")
    
    lines.append("")
    lines.append("📌 分数=涨停强度 | 盘中参考，注意风险")
    
    return '\n'.join(lines)


def send_qq(message):
    """发QQ消息 — 直接调用 hermes CLI (最稳)"""
    # 方案1：hermes send -t qqbot (推荐，直接用CLI发)
    try:
        import subprocess
        result = subprocess.run(
            ['hermes', 'send', '-t', 'qqbot', message],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0:
            return True
    except Exception:
        pass

    # 方案2：写文件，让 cron job 兜底
    notify_file = os.path.expanduser('~/.hermes/stockdb/scripts/daban/qq_pending.txt')
    try:
        with open(notify_file, 'a') as f:
            f.write(message + '\n')
        return True
    except Exception:
        pass

    # 方案3：打印到终端
    print(message)
    return True


def notify_qq(signals):
    """主入口"""
    msg = format_signal_msg(signals)
    send_qq(msg)
    return msg


if __name__ == '__main__':
    # 测试模式：读signal_history最新数据发QQ
    import duckdb, os
    
    con = duckdb.connect(os.path.expanduser('~/.hermes/stockdb/tushare.db'), read_only=True)
    
    today_str = None
    for d in ['2026-07-08', '2026-07-07', '2026-07-06']:
        try:
            rows = con.execute("SELECT date, stock_code, stock_name, industry, final_score "
                               "FROM signal_history WHERE date=? ORDER BY final_score DESC LIMIT 5", [d]).fetchall()
            if rows:
                today_str = d
                break
        except: pass
    
    if today_str:
        signals = []
        for r in con.execute("""
            SELECT stock_code, stock_name, industry, final_score 
            FROM signal_history WHERE date=? AND final_score >= 75
        """, [today_str]).fetchall():
            signals.append({
                'code': r[0], 'name': r[1], 
                'industry': f"{r[2]} {r[3]}", 'score': float(r[3]),
                'pct_chg': 9.8, 'change_pct': 9.8,
            })
        
        msg = format_signal_msg(signals)
        print(f"\n[{today_str}] 模拟QQ推送:")
        print(msg)

    con.close()
