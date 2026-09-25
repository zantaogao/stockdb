#!/usr/bin/env python3
"""
盘中交易执行脚本 + QQ 推送
===========================
每5分钟运行一次（9:30-15:00），调用 /api/execute 执行所有信号。
有新交易或新信号时通过 server API 推送到QQ。

Cron 配置：
  */5 9-14 * * 1-5   (每5分钟，9:30-14:55)
  0 15 * * 1-5        (15:00 收盘前最后一次)
"""
import urllib.request
import urllib.error
import json
import sys, os
from datetime import datetime

SERVER_URL = "http://localhost:8081/api/execute"
NOTIFY_URL = "http://localhost:8081/api/send_qq"
ACCOUNT_ID = "main"
DRY_RUN = False


def send_qq_notify(message):
    """通过 hermes send CLI 发QQ通知"""
    import subprocess
    try:
        # 直接调hermes send发QQ
        result = subprocess.run(
            ['python3', os.path.expanduser('~/.local/bin/hermes'), 'send', '-t', 'qqbot', message],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            return True
    
    except Exception:
        pass

    # 兜底：写文件到qq_pending，gateway读文件发QQ
    try:
        notify_file = os.path.expanduser('~/.hermes/stockdb/scripts/daban/qq_pending.txt')
        with open(notify_file, 'a', encoding='utf-8') as f:
            f.write(f"[{datetime.now().strftime('%H:%M')}] {message}\n")
    except Exception:
        pass

    return True


def main():
    now = datetime.now()

    # 只在交易时段执行（统一口径: 9:30-11:30 / 13:00-15:00，见 core/trading_time.py）
    from core.trading_time import in_trading_session
    if not in_trading_session(now):
        print(f"SKIP: {now.strftime('%H:%M')} 不在交易时段")
        sys.exit(0)

    # 检查服务器是否在线
    try:
        status_req = urllib.request.Request("http://localhost:8081/api/status")
        with urllib.request.urlopen(status_req, timeout=5) as resp:
            pass
    except Exception as e:
        print(f"ERROR: 服务器不可达 - {e}")
        sys.exit(1)

    # 调用 /api/execute 执行所有信号
    payload = json.dumps({
        "account_id": ACCOUNT_ID,
        "dry_run": DRY_RUN,
        "all_signals": True,
    }).encode("utf-8")

    req = urllib.request.Request(
        SERVER_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read().decode("utf-8"))

        summary = result.get("summary", {})
        executed = summary.get("executed", 0)
        skipped = summary.get("skipped", 0)
        errors = summary.get("errors", 0)

        print(f"EXECUTE {now.strftime('%H:%M')}: executed={executed} skipped={skipped} errors={errors}")

        qq_msg = None

        if executed > 0:
            trades_lines = []
            for r in result.get("results", []):
                if r.get("status") == "EXECUTED":
                    line = f"{r.get('action')} {r.get('code')} {r.get('name')} " \
                           f"{r.get('shares', 0)}股 @ {r.get('price', 0):.2f}"
                    trades_lines.append(line)
                    print(f"  {line}")

            qq_msg = f"⚡ 盘中执行: {now.strftime('%H:%M')}\n" + "\n".join(trades_lines[:5])

        # 查新信号（打板相关）
        try:
            sig_req = urllib.request.Request("http://localhost:8081/api/signals")
            with urllib.request.urlopen(sig_req, timeout=5) as resp:
                sig_data = json.loads(resp.read().decode("utf-8"))

            # 过滤打板信号（分数>=75）
            daban_signals = [s for s in (sig_data.get("signals", {}).get("new_candidates", [])) if float(s.get('score', 0)) >= 75]

            if daban_signals:
                signal_lines = []
                for s in daban_signals[:5]:
                    name = s.get('name', '')
                    score = s.get('score', 0)
                    signal_lines.append(f"  [{score:>3}] {s.get('code','')} {name}")

                if qq_msg:
                    qq_msg += f"\n📊 打板信号 ({len(daban_signals)}只):\n" + "\n".join(signal_lines[:3])
                else:
                    qq_msg = f"📊 盘中扫描: {now.strftime('%H:%M')} | {len(daban_signals)}只高分信号\n" + "\n".join(signal_lines[:5])

        except Exception as e:
            pass

        if errors > 0:
            for r in result.get("results", []):
                if r.get("status") == "ERROR":
                    print(f"  ERROR {r.get('code')} {r.get('error', '')}")
                    if qq_msg:
                        qq_msg += f"\n⚠️ {r.get('code')} {r.get('error', '')}"

        # QQ推送
        if qq_msg:
            send_qq_notify(qq_msg)

    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        print(f"HTTP {e.code}: {body}")
        sys.exit(1)
    except Exception as e:
        print(f"ERROR: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
