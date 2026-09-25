#!/usr/bin/env python3
"""派生显示层重导出（2026-09-17 建立；MacBook v2 架构专用工具）。

架构事实（MacBook）：
  策略账户权威源 = ledger.db（strategy_accounts_meta + strategy_positions + trade_log + strategy_accounts）
  sim_accounts/<aid>.json = AccountStore.save() 导出的**派生显示层**（面板 /api/dashboard 持仓页读它）
  core/unified_account.py::AccountStore.load(aid) 对策略账户是 DB 优先（cash/positions/nav_history/trades 全从 DB 取），
  save(aid) 走 DB 单事务 + JSON 导出 → **load→save 即等价于"按 DB 重生成 JSON"**。

  ⚠️ 主账户（main）例外：权威源 = ledger.db 的 holdings/account_balance（exec_agent._load_main_from_db），
     sim_accounts/main.json 是 2026-08-03 停用后的退役件（mtime 停在 8/3 14:12），本模块**禁止读写它**。

为什么需要这个工具（2026-09-16 事故）：
  手动碎仓清理脚本绕过 AccountStore.save，直写 trade_log/strategy_positions/strategy_accounts_meta →
  fusion3f(5 笔)/fusion_dual(12 笔) 的 JSON 滞后 → 面板这两个账户多显示 17 只已卖票、现金少记 32,590 元
  （账本本身自洽、无资损）。修复=把 JSON 从 DB 重导出。

用法：
  python3 -B scripts/sync_derived_json.py --dry-run        # 只看漂移，不写
  python3 -B scripts/sync_derived_json.py                  # 重导出所有漂移账户（.bak + 复检）
  python3 -B scripts/sync_derived_json.py --verify         # 只复检（有漂移则 exit 1）
  python3 -B scripts/sync_derived_json.py --accounts fusion3f,fusion_dual
自动自愈：scripts/strategy_accounts_daily.py 每轮收尾会调 resync_all()（2026-09-17 挂接）。
"""
import argparse
import datetime
import json
import os
import shutil
import sys

_SCRIPT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

from core.db import connect_ledger                      # noqa: E402
from core.unified_account import AccountStore           # noqa: E402

BASE = _SCRIPT_DIR
SIM = os.path.join(BASE, 'sim_accounts')
SKIP = {'main'}      # 退役件：主账户 JSON 不可读写（见模块 docstring）
CASH_EPS = 0.01


def _db_truth(conn, aid):
    meta = conn.execute("SELECT cash FROM strategy_accounts_meta WHERE account_id=?", (aid,)).fetchone()
    pos = {r[0]: int(r[1] or 0)
           for r in conn.execute("SELECT code, shares FROM strategy_positions WHERE account_id=?", (aid,)).fetchall()}
    ntr = conn.execute("SELECT COUNT(*) FROM trade_log WHERE strategy=?", (aid,)).fetchone()[0]
    return (float(meta[0]) if meta else None), pos, int(ntr)


def _json_state(aid):
    p = os.path.join(SIM, f'{aid}.json')
    if not os.path.exists(p):
        return None
    d = json.load(open(p, encoding='utf-8'))
    pos = {x.get('code'): int(x.get('shares') or 0) for x in d.get('positions', []) if x.get('code')}
    return d.get('cash'), pos, len(d.get('trades', [])), p


def drift_report(aids=None, verbose=True):
    """返回漂移账户列表；每个元素给出 DB/JSON 两侧差异明细。无漂移 → []"""
    conn = connect_ledger(read_only=True)
    try:
        ids = [r[0] for r in conn.execute(
            "SELECT account_id FROM strategy_accounts_meta ORDER BY account_id").fetchall()]
        out = []
        for aid in ids:
            if aid in SKIP or (aids and aid not in aids):
                continue
            cash_db, pos_db, ntr_db = _db_truth(conn, aid)
            js = _json_state(aid)
            if js is None:
                out.append({'aid': aid, 'missing_json': True, 'cash_db': cash_db, 'cash_json': None,
                            'pos_diff_db': pos_db, 'pos_diff_json': {}, 'ntrade_db': ntr_db, 'ntrade_json': None})
                continue
            cash_js, pos_js, ntr_js, path = js
            pos_diff_db = {k: v for k, v in pos_db.items() if pos_js.get(k, 0) != v}
            pos_diff_json = {k: v for k, v in pos_js.items() if pos_db.get(k, 0) != v}
            drifted = (abs((cash_db or 0) - (cash_js or 0)) > CASH_EPS
                       or bool(pos_diff_db) or bool(pos_diff_json) or ntr_db != ntr_js)
            if drifted:
                out.append({'aid': aid, 'missing_json': False, 'cash_db': cash_db, 'cash_json': cash_js,
                            'pos_diff_db': pos_diff_db, 'pos_diff_json': pos_diff_json,
                            'ntrade_db': ntr_db, 'ntrade_json': ntr_js})
        if verbose:
            if not out:
                print('[derived] 派生层与 DB 一致：0 漂移')
            for d in out:
                print(f"[derived] ⚠️ {d['aid']} 漂移：现金 DB={d['cash_db']} / JSON={d['cash_json']} | "
                      f"9/16 后 DB 有 JSON 无的持仓 {d['pos_diff_db']} | JSON 多余持仓 {d['pos_diff_json']} | "
                      f"流水 DB={d['ntrade_db']} / JSON={d['ntrade_json']}")
        return out
    finally:
        conn.close()


def resync(aid, dry=False):
    """把单个账户的 JSON 从 DB 重导出（load→save）。返回 (是否动作, 备份路径)"""
    if aid in SKIP:
        raise ValueError(f'{aid} 是退役件，禁止重导出')
    path = os.path.join(SIM, f'{aid}.json')
    bak = None
    if not dry and os.path.exists(path):
        bak = f'{path}.bak.{datetime.datetime.now().strftime("%Y%m%d_%H%M%S")}.derivedsync'
        shutil.copy2(path, bak)
    if dry:
        return True, None
    store = AccountStore()
    acct = store.load(aid)      # 策略账户：DB 优先（meta/positions/nav_history/trade_log）
    store.save(acct)            # DB 单事务（同内容幂等）+ 导出 JSON
    return True, bak


def resync_all(aids=None, dry=False, verbose=True):
    """重导出所有漂移账户；返回处理数。幂等：无漂移则不动文件。"""
    drift = drift_report(aids=aids, verbose=verbose)
    n = 0
    for d in drift:
        aid = d['aid']
        changed, bak = resync(aid, dry=dry)
        if changed:
            n += 1
            if verbose:
                tag = '(dry-run)' if dry else (os.path.basename(bak) if bak else '无备份')
                print(f'[derived] ✅ {aid} 已按 DB 重导出 JSON {tag}')
    if verbose and n and not dry:
        left = drift_report(aids=aids, verbose=False)
        print(f"[derived] 复检：剩余漂移 {len(left)} 个账户 {'（全部一致）' if not left else left}")
        return n
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true', help='只报告漂移，不写文件')
    ap.add_argument('--accounts', default='', help='只处理这些账户（逗号分隔）')
    ap.add_argument('--force', action='store_true', help='无视漂移，全部账户强制重导出（日期/字段归一化用）')
    ap.add_argument('--verify', action='store_true', help='只复检；有漂移 exit 1（cron 用）')
    a = ap.parse_args()
    aids = [x.strip() for x in a.accounts.split(',') if x.strip()] or None
    if a.verify:
        drift = drift_report(aids=aids, verbose=True)
        sys.exit(1 if drift else 0)
    if a.force and not a.dry_run:
        n = 0
        for _aid in (aids or [r[0] for r in connect_ledger(read_only=True).execute(
                'SELECT account_id FROM strategy_accounts_meta ORDER BY account_id').fetchall()]):
            if _aid in SKIP:
                continue
            resync(_aid, dry=False); n += 1
        print(f"[derived] --force 重导出 {n} 个账户")
        drift_report(aids=aids, verbose=True)
    else:
        n = resync_all(aids=aids, dry=a.dry_run, verbose=True)
    print(f"[derived] 处理完成：{'dry-run 未写入' if a.dry_run else f'重导出 {n} 个账户'}")


if __name__ == '__main__':
    main()
