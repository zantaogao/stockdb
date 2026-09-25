#!/usr/bin/env python3
"""策略账户迁移：sim_accounts/*.json → state.db（一次性，幂等）

迁移内容：
  - strategy_accounts_meta + strategy_positions（经 AccountStore.save 写入，事务原子）
  - NAV 历史已在 strategy_accounts 表（run_day 写入），此处校验一致性
  - 交易流水已在 trade_log（run_day 写入），此处校验一致性

迁移前备份全部 JSON 到 sim_accounts/bak_pre_db_<ts>/。
"""
import json, shutil, sqlite3, sys
from datetime import datetime
from pathlib import Path

BASE = Path.home() / '.hermes' / 'stockdb'
sys.path.insert(0, str(BASE))
from core.unified_account import AccountStore, Account

ACCOUNTS_DIR = BASE / 'sim_accounts'
STATE_DB = BASE / 'state.db'

def main():
    store = AccountStore()
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    bak_dir = ACCOUNTS_DIR / f'bak_pre_db_{ts}'
    bak_dir.mkdir(exist_ok=True)

    conn = sqlite3.connect(str(STATE_DB), timeout=30)
    json_files = sorted(ACCOUNTS_DIR.glob('*.json'))
    migrated, skipped = [], []
    for f in json_files:
        aid = f.stem
        if aid == 'main' or '.old' in f.name or '.corrupt' in f.name or f.name.endswith('.json.tmp'):
            skipped.append(f.name)
            continue
        # 1. 备份原始 JSON
        shutil.copy2(f, bak_dir / f.name)
        # 2. 解析
        try:
            data = json.loads(f.read_text(encoding='utf-8'))
        except Exception as e:
            print(f'  ❌ {aid}: JSON 解析失败，跳过迁移（{e}）')
            continue
        acct = Account.from_dict(data)
        # 3. 写 DB（meta + positions，事务原子）
        try:
            store.save(acct)
        except Exception as e:
            print(f'  ❌ {aid}: DB 写入失败: {e}')
            continue
        # 4. 校验 NAV 历史（strategy_accounts 表）
        db_nav = conn.execute(
            "SELECT COUNT(*), MAX(date) FROM strategy_accounts WHERE account_id=?", (aid,)).fetchone()
        json_nav = acct.nav_history
        json_nav_n = len(json_nav)
        # 5. 校验交易流水（trade_log）
        db_trades = conn.execute(
            "SELECT COUNT(*) FROM trade_log WHERE strategy=?", (aid,)).fetchone()[0]
        json_trades_n = len(acct.trades)
        # 6. 持仓数
        db_pos = conn.execute(
            "SELECT COUNT(*) FROM strategy_positions WHERE account_id=?", (aid,)).fetchone()[0]
        status = (f'✅ {aid}: DB持仓{db_pos}只(JSON {len(acct.positions)}) | '
                  f'NAV {db_nav[0]}条(JSON {json_nav_n}, 最新{db_nav[1]}) | '
                  f'流水 {db_trades}条(JSON {json_trades_n})')
        if db_pos != len(acct.positions) or db_nav[0] != json_nav_n or db_trades != json_trades_n:
            status += '  ⚠️ 数量不一致！'
        print(' ', status)
        migrated.append(aid)

    conn.commit()
    conn.close()
    print(f'\n迁移完成: {len(migrated)} 个账户 → DB，备份在 {bak_dir}')
    if skipped:
        print(f'跳过: {skipped}')

    # 验证：从 DB 重新 load 对比
    print('\n=== 从 DB load 验证 ===')
    for aid in migrated:
        acct = store.load(aid)
        nav = acct.cash + sum(p.shares * p.avg_cost for p in acct.positions)
        print(f'  {aid}: {acct.name} | 现金 {acct.cash:,.0f} | 持仓 {len(acct.positions)} 只 | '
              f'NAV≈{nav:,.0f} | trades {len(acct.trades)} | nav_history {len(acct.nav_history)}')

if __name__ == '__main__':
    main()
