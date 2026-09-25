#!/usr/bin/env python3
"""成交实时推送 QQ（2026-08-03）。
执行脚本（exec_agent.py / strategy_accounts_daily.py）成交后调用，不阻塞、失败静默。
用法: notify_trade.py <账户名> <BUY|SELL> <code> <name> <shares> <price> <amount> [reason]

2026-08-19 修复：重评日 71 笔成交并发 Popen → 213 次 hermes send 并发轰炸 QQ API
→ 大量限流失败（用户反馈"只有个别有推送"）。加进程间文件锁（fcntl.flock）串行化：
同一时刻只允许一个 notify_trade 进程发送，其余等待；每笔发送间再 sleep 0.3s 缓冲。
"""
import subprocess, sys, time, os, fcntl

# 三 bot 推送目标（2026-08-13 用户要求：交易明细推全部 qqbot）
QQ_TARGETS = [
    'qqbot:3A9EE9C3C40A3E1DE81CF01F5BC42616',                           # 新 bot（1904169556）主人，2026-08-23 配对
]

# 2026-09-11 用户拍板：CMMR 系账户成交不再推送 QQ（账户照常交易，只是不再推）
# 2026-09-17 用户拍板：恢复 cmmr 系推送，清空跳过名单（保留机制供以后再停推）
PUSH_SKIP_ACCOUNTS = set()

# 进程间串行锁（2026-08-19）：/tmp/notify_trade.lock，flock 排他
_LOCK_PATH = '/tmp/notify_trade.lock'
_SEND_INTERVAL = 0.3  # 每笔 hermes send 间隔（秒），限速缓冲

def notify(account, action, code, name, shares, price, amount, reason='', pnl=''):
    if account in PUSH_SKIP_ACCOUNTS:
        print(f"  [push] skip（账户 {account} 为 CMMR 系，2026-09-11 起停推）")
        return
    tag = '🔴卖出' if action == 'SELL' else '🟢买入'
    msg = (f"{tag}【{account}】{code} {name} {shares}股 @{price} 金额{amount:,.2f}")
    if pnl and action in ('SELL', 'REDUCE'):
        msg += f"\n盈亏: {pnl}"  # 2026-09-14 用户要求：每笔卖出推送带盈亏
    if reason:
        msg += f"\n原因: {reason}"
    # 串行锁：并发 Popen 场景下排队发送，避免 QQ API 限流
    with open(_LOCK_PATH, 'a') as lockf:
        try:
            fcntl.flock(lockf, fcntl.LOCK_EX)
        except Exception:
            pass  # 锁不可用（如 Windows）退化为无锁
        try:
            for target in QQ_TARGETS:
                if 'PENDING_OPENID' in target:
                    continue  # openid 未回填，跳过
                try:
                    r = subprocess.run(['hermes', 'send', '-t', target, msg],
                                       capture_output=True, timeout=30)
                    print(f"  [push] {'OK' if r.returncode == 0 else 'FAIL'} {target} {msg[:40]}...")
                except Exception as e:
                    print(f"  [push] 失败({target}): {e}")
                time.sleep(_SEND_INTERVAL)  # 限速缓冲
        finally:
            try:
                fcntl.flock(lockf, fcntl.LOCK_UN)
            except Exception:
                pass

if __name__ == '__main__':
    if len(sys.argv) < 8:
        print("用法: notify_trade.py <账户> <BUY|SELL> <code> <name> <shares> <price> <amount> [reason]")
        sys.exit(1)
    notify(sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4],
           sys.argv[5], float(sys.argv[6]), float(sys.argv[7]),
           sys.argv[8] if len(sys.argv) > 8 else '',
           sys.argv[9] if len(sys.argv) > 9 else '')
