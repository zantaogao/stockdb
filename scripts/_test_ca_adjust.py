#!/usr/bin/env python3
"""adjust_corporate_action 除权调整单测（隔离环境，不碰生产库/生产 json）
场景：10送10 + 10派5（stk_div=1.0, cash_div=0.5）持股 1000 股 成本 20 → 
  送转 2000 股、现金 1000×0.5×(1-tax)、成本摊薄、价格类按 (v-0.5)/2 下调
运行：cd ~/.hermes/stockdb && python3 -B scripts/_test_ca_adjust.py
"""
import os, sys, json, sqlite3, tempfile, shutil
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import adjust_corporate_action as ca

# ⚠️ 写库硬护栏（2026-09-11 事故教训：MacBook 单测直连生产 ledger.db，
# 把 holdings/position_peaks 清空、account_balance 覆盖成假值）。
# 路径含 state.db / ledger.db 一律拒绝连接 —— 单测只许用 :memory: 或临时目录库。
_ORIG_CONNECT = sqlite3.connect


def _guarded_connect(path, *a, **k):
    s = str(path)
    if 'state.db' in s or 'ledger.db' in s:
        raise RuntimeError(f'单测禁止连接生产库：{s}（改用 :memory: 或临时目录）')
    return _ORIG_CONNECT(path, *a, **k)


sqlite3.connect = _guarded_connect

PASS = 0


def ok(name, cond, detail=''):
    global PASS
    print(f"  {'✅' if cond else '❌'} {name} {detail}")
    if cond:
        PASS += 1


def make_db(path):
    c = sqlite3.connect(path)
    c.execute("CREATE TABLE holdings (code TEXT, name TEXT, shares REAL, avg_cost REAL, buy_date TEXT, "
              "status TEXT, latest_price REAL, update_time TEXT, target_price REAL, stop_loss REAL)")
    c.execute("CREATE TABLE account_balance (account_id TEXT, cash_balance REAL, total_value REAL, last_update TEXT)")
    c.execute("CREATE TABLE position_peaks (code TEXT, peak_price REAL, updated_at TEXT)")
    c.execute("CREATE TABLE ca_adjustments (code TEXT NOT NULL, ex_date TEXT NOT NULL, account TEXT NOT NULL, "
              "factor REAL DEFAULT 1.0, cash_div REAL DEFAULT 0.0, tax_rate REAL DEFAULT 0.0, "
              "shares_add INTEGER DEFAULT 0, net_div REAL DEFAULT 0.0, "
              "created_at TEXT DEFAULT (datetime('now','localtime')), PRIMARY KEY (code, ex_date, account))")
    c.execute("CREATE TABLE ca_run_log (run_date TEXT PRIMARY KEY, status TEXT, n_ex INTEGER, n_hit INTEGER, "
              "detail TEXT, created_at TEXT DEFAULT (datetime('now','localtime')))")
    c.execute("INSERT INTO holdings VALUES ('300001', '测试股', 1000, 20.0, '2026-08-10', 'hold', "
              "25.0, '2026-09-03 15:00', 30.0, 17.6)")
    c.execute("INSERT INTO account_balance VALUES ('main', 100000.0, 0, '2026-09-03 15:00')")
    c.execute("INSERT INTO position_peaks VALUES ('300001', 26.0, '2026-09-03 15:00')")
    c.commit()
    return c


def test_run_flow():
    """run() 集成：mock 除权命中 → 每股写各账户行（main/策略）、幂等、无 pending 残留"""
    print("== run() 账户行写入与幂等（mock 环境）==")
    import tempfile, shutil
    tmpdir = tempfile.mkdtemp()
    # 假策略账户 json
    acct = {"initial_capital": 1000000.0, "cash": 5000.0, "config": {"last_rebalance_date": "20260901"},
            "positions": [{"code": "300001", "name": "测试", "shares": 1000, "avg_cost": 20.0,
                           "buy_date": "20260903", "peak_price": 25.0, "stop_loss": 17.6, "target": 0.0}],
            "trades": [], "nav_history": []}
    json.dump(acct, open(os.path.join(tmpdir, 'fusion3f.json'), 'w'), ensure_ascii=False, indent=2)
    # 假 center_dual 账户（验证动态发现覆盖新账户：2026-09-04 修复）
    acct2 = {"initial_capital": 1000000.0, "cash": 9000.0, "config": {},
             "positions": [{"code": "300001", "name": "测试", "shares": 500, "avg_cost": 20.0,
                            "buy_date": "20260902", "peak_price": 24.0, "stop_loss": 17.6, "target": 0.0}],
             "trades": [], "nav_history": []}
    json.dump(acct2, open(os.path.join(tmpdir, 'center_dual.json'), 'w'), ensure_ascii=False, indent=2)
    # 非账户文件（过滤校验）
    json.dump({"trades": []}, open(os.path.join(tmpdir, 'auto_trade_log.json'), 'w'))
    # 假 db（main 持仓同股，买日 2026-08-10 → 25天 → 税 20%）
    dbp = os.path.join(tmpdir, 't.db')
    c = make_db(dbp)
    old_conn = ca.get_conn
    old_sim = ca.SIM_DIR
    old_div = ca.get_ex_divs
    try:
        ca.get_conn = lambda: (c, '')
        ca.SIM_DIR = Path(tmpdir)
        ca.get_ex_divs = lambda pro, td: {'300001': {'stk_div': 1.0, 'stk_bo': 0.0, 'cash_div': 0.5, 'stk_co': 0.0}}
        out1 = ca.run(None, '20260904')
        print("  首跑输出:", out1)
        c.close()  # run() 内部会 close 传入连接 → 重新打开查询
        c = sqlite3.connect(dbp)
        rows = c.execute("SELECT code, ex_date, account, factor, tax_rate, shares_add, net_div "
                         "FROM ca_adjustments ORDER BY account").fetchall()
        print("  ca 行:", rows)
        accts = {r[2]: r for r in rows}
        ok("main 行写入 (tax 0.2, +1000股, 净息400)", 'main' in accts and accts['main'][4] == 0.2
           and accts['main'][5] == 1000 and abs(accts['main'][6] - 400) < 0.01, f"实际 {accts.get('main')}")
        # fusion3f buy 20260903 → 1天 → 税 20% → 净息 400（1000×0.5×0.8）
        ok("fusion3f 行写入", 'fusion3f' in accts and accts['fusion3f'][5] == 1000
           and abs(accts['fusion3f'][6] - 400) < 0.01, f"实际 {accts.get('fusion3f')}")
        # center_dual buy 20260902 → 2天 → 税 20% → 净息 500×0.5×0.8=200
        ok("center_dual 行写入（动态发现覆盖）", 'center_dual' in accts
           and accts['center_dual'][5] == 500 and abs(accts['center_dual'][6] - 200) < 0.01,
           f"实际 {accts.get('center_dual')}")
        ok("auto_trade_log 被过滤（非账户文件）", 'auto_trade_log' not in accts)
        ok("无 pending 残留", all(r[2] != '__pending__' for r in rows))
        # 幂等：再跑一次 → 跳过
        out2 = ca.run(None, '20260904')
        c = sqlite3.connect(dbp)  # run 又 close 了连接 → 重开
        n2 = c.execute("SELECT COUNT(*) FROM ca_adjustments").fetchone()[0]
        ok("幂等（重跑不重复写入）", n2 == len(rows) and any('已调整过' in l for l in out2), f"行数 {n2} {out2}")
        # main 持仓已被送转（run 里 adjust_main 执行）→ 验证
        sh = c.execute("SELECT shares FROM holdings WHERE code='300001'").fetchone()[0]
        ok("main 持仓已送转 2000", sh == 2000, f"实际 {sh}")
    finally:
        ca.get_conn = old_conn
        ca.SIM_DIR = old_sim
        ca.get_ex_divs = old_div
        shutil.rmtree(tmpdir)


def test_main():
    print("== 主账户（holdings/account_balance/peaks）==")
    tmp = tempfile.mktemp(suffix='.db')
    c = make_db(tmp)
    par = {'stk_div': 1.0, 'stk_bo': 0.0, 'cash_div': 0.5, 'stk_co': 0.0}
    # 买入 2026-08-10，除权 2026-09-04 → 25 天 ≤30 → 税 20%
    r = ca.adjust_main(c, '', '300001', '20260904', par)
    ok("返回调整记录", r is not None and r[1])
    sh = c.execute("SELECT shares FROM holdings WHERE code='300001'").fetchone()[0]
    ok("送转 1000→2000 股", sh == 2000, f"实际 {sh}")
    cash = c.execute("SELECT cash_balance FROM account_balance").fetchone()[0]
    ok("现金 +400 (1000×0.5×0.8)", abs(cash - 100400.0) < 0.01, f"实际 {cash}")
    ac = c.execute("SELECT avg_cost FROM holdings WHERE code='300001'").fetchone()[0]
    # (20000-400)/2000 = 9.8
    ok("成本摊薄 (20000-400)/2000=9.8", abs(ac - 9.8) < 0.001, f"实际 {ac}")
    sl = c.execute("SELECT stop_loss FROM holdings WHERE code='300001'").fetchone()[0]
    ok("止损线下调 (17.6-0.5)/2=8.55", abs(sl - 8.55) < 0.01, f"实际 {sl}")
    tg = c.execute("SELECT target_price FROM holdings WHERE code='300001'").fetchone()[0]
    ok("目标价下调 (30-0.5)/2=14.75", abs(tg - 14.75) < 0.01, f"实际 {tg}")
    pk = c.execute("SELECT peak_price FROM position_peaks WHERE code='300001'").fetchone()[0]
    ok("峰值下调 (26-0.5)/2=12.75", abs(pk - 12.75) < 0.01, f"实际 {pk}")
    ok("返回 main 税率 0.2（25天≤30）", abs(r[2] - 0.2) < 0.001, f"实际 {r[2]}")
    # ca_adjustments 由 run 层统一写（本函数不写，防占位与实调税率不一致）
    rec = c.execute("SELECT COUNT(*) FROM ca_adjustments").fetchone()[0]
    ok("函数层不直接写 ca（run 管理）", rec == 0, f"实际 {rec} 行")
    c.close()
    os.unlink(tmp)


def test_pure_div():
    print("== 纯派息（无送转 factor=1）==")
    tmp = tempfile.mktemp(suffix='.db')
    c = make_db(tmp)
    par = {'stk_div': 0.0, 'stk_bo': 0.0, 'cash_div': 0.5, 'stk_co': 0.0}
    ca.adjust_main(c, '', '300001', '20260904', par)
    sh = c.execute("SELECT shares FROM holdings WHERE code='300001'").fetchone()[0]
    ok("股数不变 1000", sh == 1000)
    cash = c.execute("SELECT cash_balance FROM account_balance").fetchone()[0]
    ok("现金 +400", abs(cash - 100400.0) < 0.01)
    ac = c.execute("SELECT avg_cost FROM holdings WHERE code='300001'").fetchone()[0]
    ok("成本回收 (20000-400)/1000=19.6", abs(ac - 19.6) < 0.01, f"实际 {ac}")
    sl = c.execute("SELECT stop_loss FROM holdings WHERE code='300001'").fetchone()[0]
    ok("止损线下调 (17.6-0.5)=17.1", abs(sl - 17.1) < 0.01, f"实际 {sl}")
    c.close()
    os.unlink(tmp)


def test_long_hold_tax0():
    print("== 长期持有免税（>365 天）==")
    tmp = tempfile.mktemp(suffix='.db')
    c = make_db(tmp)
    c.execute("UPDATE holdings SET buy_date='2025-01-10' WHERE code='300001'")
    c.commit()
    par = {'stk_div': 0.0, 'stk_bo': 0.0, 'cash_div': 0.5, 'stk_co': 0.0}
    ca.adjust_main(c, '', '300001', '20260904', par)
    cash = c.execute("SELECT cash_balance FROM account_balance").fetchone()[0]
    ok("现金 +500 (免税)", abs(cash - 100500.0) < 0.01, f"实际 {cash}")
    c.close()
    os.unlink(tmp)


def test_strategy():
    print("== 策略账户（sim json）==")
    tmpdir = tempfile.mkdtemp()
    old = ca.SIM_DIR
    ca.SIM_DIR = Path(tmpdir)
    acct = {"initial_capital": 1000000.0, "cash": 5000.0, "config": {"last_rebalance_date": "20260901"},
            "positions": [{"code": "688999", "name": "测试", "shares": 500, "avg_cost": 40.0,
                           "buy_date": "20260901", "peak_price": 44.0, "stop_loss": 35.2, "target": 0.0}],
            "trades": [], "nav_history": []}
    json.dump(acct, open(os.path.join(tmpdir, 'fusion3f.json'), 'w'), ensure_ascii=False, indent=2)
    par = {'stk_div': 1.0, 'stk_bo': 0.0, 'cash_div': 0.5, 'stk_co': 0.0}  # 10送10+10派5
    # 2026-09-21 修复：签名已改为 (conn, p, aid, code, ex_date, par)（9/11 DB-first 重写），
    # 单测未同步 → 自 9/11 起本测试实际一直失败。传内存库 + 空前缀 = M2 纯 JSON 路径。
    c = sqlite3.connect(':memory:')
    r = ca.adjust_strategy(c, '', 'fusion3f', '688999', '20260904', par)
    c.close()
    ok("返回调整记录", r is not None)
    d = json.load(open(os.path.join(tmpdir, 'fusion3f.json')))
    pos = d['positions'][0]
    ok("送转 500→1000 股", pos['shares'] == 1000, f"实际 {pos['shares']}")
    # buy 20260901 → 3 天 ≤30 → 税 20% → 净息 500×0.5×0.8=200
    ok("现金 +200", abs(d['cash'] - 5200.0) < 0.01, f"实际 {d['cash']}")
    # 成本 (500×40-200)/1000 = 19.8
    ok("成本 19.8", abs(pos['avg_cost'] - 19.8) < 0.01, f"实际 {pos['avg_cost']}")
    ok("峰值 (44-0.5)/2=21.75", abs(pos['peak_price'] - 21.75) < 0.01, f"实际 {pos['peak_price']}")
    ok("止损 (35.2-0.5)/2=17.35", abs(pos['stop_loss'] - 17.35) < 0.01, f"实际 {pos['stop_loss']}")
    ok("buy_date 保留", pos['buy_date'] == '20260901')
    shutil.rmtree(tmpdir)
    ca.SIM_DIR = old


def test_strategy_db_first():
    """DB-first 机器（MacBook v2）：has_db=True → DB 权威写 + JSON 派生层同步。
    2026-09-21 新增：9/11 重写后此路径无单测覆盖，而两台日常走的都是它。"""
    print("== 策略账户 DB-first（ledger 表 + JSON 派生）==")
    tmpdir = tempfile.mkdtemp()
    old = ca.SIM_DIR
    ca.SIM_DIR = Path(tmpdir)
    acct = {"initial_capital": 1000000.0, "cash": 5000.0, "config": {},
            "positions": [{"code": "688999", "name": "测试", "shares": 500, "avg_cost": 40.0,
                           "buy_date": "20260901", "peak_price": 44.0, "stop_loss": 35.2, "target": 0.0}],
            "trades": [], "nav_history": []}
    json.dump(acct, open(os.path.join(tmpdir, 'fusion3f.json'), 'w'), ensure_ascii=False, indent=2)
    c = sqlite3.connect(os.path.join(tmpdir, 'db_first.db'))
    c.execute("CREATE TABLE strategy_positions (account_id TEXT, code TEXT, name TEXT, shares REAL, "
              "avg_cost REAL, buy_date TEXT, peak_price REAL, stop_loss REAL, target REAL, updated_at TEXT)")
    c.execute("CREATE TABLE strategy_accounts_meta (account_id TEXT, cash REAL, updated_at TEXT)")
    c.execute("INSERT INTO strategy_positions VALUES ('fusion3f','688999','测试',500,40.0,'20260901',"
              "44.0,35.2,0.0,'')")
    c.execute("INSERT INTO strategy_accounts_meta VALUES ('fusion3f',5000.0,'')")
    c.commit()
    par = {'stk_div': 1.0, 'stk_bo': 0.0, 'cash_div': 0.5, 'stk_co': 0.0}  # 10送10+10派5
    r = ca.adjust_strategy(c, '', 'fusion3f', '688999', '20260904', par)
    ok("返回调整记录", r is not None)
    sh = c.execute("SELECT shares FROM strategy_positions WHERE code='688999'").fetchone()[0]
    ok("DB 持仓 500→1000", abs(sh - 1000) < 0.01, f"实际 {sh}")
    cash = c.execute("SELECT cash FROM strategy_accounts_meta WHERE account_id='fusion3f'").fetchone()[0]
    ok("DB 现金 +200 → 5200", abs(cash - 5200.0) < 0.01, f"实际 {cash}")
    ac = c.execute("SELECT avg_cost FROM strategy_positions WHERE code='688999'").fetchone()[0]
    ok("DB 成本 (20000-200)/1000=19.8", abs(ac - 19.8) < 0.01, f"实际 {ac}")
    d = json.load(open(os.path.join(tmpdir, 'fusion3f.json')))
    ok("JSON 派生层同步（shares/cash）", d['positions'][0]['shares'] == 1000
       and abs(d['cash'] - 5200.0) < 0.01, f"实际 {d['positions'][0]['shares']} / {d['cash']}")
    c.close()
    shutil.rmtree(tmpdir)
    ca.SIM_DIR = old


def test_no_db_table_m2():
    """M2 语义：库里没有 strategy_positions/strategy_accounts_meta → 纯 JSON 写，
    绝不许抛 no such table（2026-09-21 修复的第二个 bug）。"""
    print("== M2 语义（无 DB 表 → 纯 JSON，不报 no such table）==")
    tmpdir = tempfile.mkdtemp()
    old = ca.SIM_DIR
    ca.SIM_DIR = Path(tmpdir)
    json.dump({"cash": 5000.0, "positions": [{"code": "688999", "shares": 500, "avg_cost": 40.0,
                                              "buy_date": "20260901", "peak_price": 44.0,
                                              "stop_loss": 35.2, "target": 0.0}]},
              open(os.path.join(tmpdir, 'fusion3f.json'), 'w'), ensure_ascii=False)
    c = sqlite3.connect(os.path.join(tmpdir, 'm2_like.db'))
    c.execute("CREATE TABLE holdings (code TEXT)")   # 只有主账户表，无策略表
    c.commit()
    par = {'stk_div': 1.0, 'stk_bo': 0.0, 'cash_div': 0.5, 'stk_co': 0.0}
    try:
        r = ca.adjust_strategy(c, '', 'fusion3f', '688999', '20260904', par)
        err = None
    except Exception as e:      # noqa: BLE001
        r, err = None, e
    ok("不抛异常（原 no such table: strategy_positions）", err is None, f"实际 {err}")
    ok("返回调整记录", r is not None)
    d = json.load(open(os.path.join(tmpdir, 'fusion3f.json')))
    ok("JSON 持仓 500→1000 / 现金 +200", d['positions'][0]['shares'] == 1000
       and abs(d['cash'] - 5200.0) < 0.01, f"实际 {d['positions'][0]['shares']} / {d['cash']}")
    c.close()
    shutil.rmtree(tmpdir)
    ca.SIM_DIR = old


def test_window():
    """运行窗口边界 + 「# cron-window 声明」与生效常量一致性（2026-09-21 加）。

    判据被 ~/.hermes/scripts/check_cron_window_alignment.py 复用（cron × 窗口交叉核对），
    所以边界值必须钉死；声明行与常量脱节会让核对器用错基准 → 也要单测锁住。"""
    print("== 运行窗口边界 + 声明一致性 ==")
    for t, exp in (('06:59', False), ('07:00', True), ('09:15', True), ('09:16', False),
                   ('12:00', False), ('15:29', False), ('15:30', True), ('23:59', True),
                   ('00:00', False)):
        ok(f"is_in_window({t}) == {exp}", ca.is_in_window(t) is exp)
    import re
    src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            'adjust_corporate_action.py')).read()
    m = re.search(r'^# cron-window:\s*(\S+)\s*$', src, re.M)
    ok("存在 # cron-window 声明行", m is not None)
    if m:
        declared = tuple(tuple(x.split('-')) for x in m.group(1).split(','))
        actual = ca.PRE_WINDOWS + ca.POST_WINDOWS
        ok("声明与生效常量一致", declared == actual, f"声明={declared} 常量={actual}")


def test_attached_schema():
    """ATTACH 前缀（MacBook 的 'led.'）下表探测必须查 <p>sqlite_master（2026-09-21 修复）。

    回归用例：修复前 has_db 用裸 sqlite_master 探测 → 只看到 main schema → MacBook 侧
    误判「无 DB 表」→ 除权调整只写 JSON 派生层、ledger.db（权威源）不更新 →
    下一轮 AccountStore.save 用 DB 旧值重导 JSON，派息被静默回滚（9/21 实盘命中）。"""
    print("== ATTACH schema（led.）表探测与 DB 权威写 ==")
    tmpdir = tempfile.mkdtemp()
    old = ca.SIM_DIR
    ca.SIM_DIR = Path(tmpdir)
    json.dump({"cash": 5000.0, "positions": [{"code": "688999", "shares": 500, "avg_cost": 40.0,
                                              "buy_date": "20260901", "peak_price": 44.0,
                                              "stop_loss": 35.2, "target": 0.0}]},
              open(os.path.join(tmpdir, 'fusion3f.json'), 'w'), ensure_ascii=False)
    c = sqlite3.connect(os.path.join(tmpdir, 'main_attach.db'))
    c.execute("CREATE TABLE holdings (code TEXT)")            # main schema 里没有策略表
    c.execute("ATTACH DATABASE ? AS led", (os.path.join(tmpdir, 'led_attach.db'),))
    c.execute("CREATE TABLE led.strategy_positions (account_id TEXT, code TEXT, name TEXT, shares REAL, "
              "avg_cost REAL, buy_date TEXT, peak_price REAL, stop_loss REAL, target REAL, updated_at TEXT)")
    c.execute("CREATE TABLE led.strategy_accounts_meta (account_id TEXT, cash REAL, updated_at TEXT)")
    c.execute("INSERT INTO led.strategy_positions VALUES ('fusion3f','688999','测试',500,40.0,"
              "'20260901',44.0,35.2,0.0,'')")
    c.execute("INSERT INTO led.strategy_accounts_meta VALUES ('fusion3f',5000.0,'')")
    c.commit()
    ok("探测到 led.strategy_positions（修复点）",
       'led.strategy_positions' in ca.table_names(c, 'led.'))
    par = {'stk_div': 1.0, 'stk_bo': 0.0, 'cash_div': 0.5, 'stk_co': 0.0}
    r = ca.adjust_strategy(c, 'led.', 'fusion3f', '688999', '20260904', par)
    ok("返回调整记录", r is not None)
    sh = c.execute("SELECT shares FROM led.strategy_positions WHERE code='688999'").fetchone()[0]
    ok("led 持仓 500→1000（DB 权威写真的生效）", abs(sh - 1000) < 0.01, f"实际 {sh}")
    cash = c.execute("SELECT cash FROM led.strategy_accounts_meta WHERE account_id='fusion3f'").fetchone()[0]
    ok("led 现金 5000→5200", abs(cash - 5200.0) < 0.01, f"实际 {cash}")
    c.close()
    shutil.rmtree(tmpdir)
    ca.SIM_DIR = old


def test_tax_mid():
    print("== 持有 31-365 天 10% 税 ==")
    ok("31天→10%", abs(ca.div_tax_rate('20260801', '20260901') - 0.10) < 0.001)
    ok("30天→20%", abs(ca.div_tax_rate('20260802', '20260901') - 0.20) < 0.001)
    ok("366天→0%", abs(ca.div_tax_rate('20250801', '20260901') - 0.0) < 0.001)
    ok("缺失→20%", abs(ca.div_tax_rate(None, '20260901') - 0.20) < 0.001)


if __name__ == '__main__':
    test_run_flow()
    test_main()
    test_pure_div()
    test_long_hold_tax0()
    test_strategy()
    test_strategy_db_first()
    test_no_db_table_m2()
    test_window()
    test_attached_schema()
    test_tax_mid()
    TOTAL = 55
    print(f"\n结果: {PASS}/{TOTAL} 通过")
    sys.exit(0 if PASS == TOTAL else 1)
