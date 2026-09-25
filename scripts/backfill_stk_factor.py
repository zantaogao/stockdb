#!/usr/bin/env python3
"""周六 stk_factor 缺口补拉（2026-08-08 新增，当日修复：原子交换版）。
背景: tushare stk_factor_pro 当天因子延迟数小时~1天（08-07 实盘: 16:00 返回空）。
周五 16:00 主更新拉不到 → 周末信号用滞后1天因子 → 周一盘中决策受影响。

⚠️ 08-08 双份事故修复: 原版直接调 update_stk_factor(pro) → 进程内 _ACTIVE_DB 初始=活库 →
   get_db_writable() 绕过 main() 的原子交换直接打开活库可写（违反 tushare.db 只读铁律）；
   且无写锁，与 16:00 更新（main）并发时共享 TEMP_DB 路径(tushare.db.new)互相踩踏。
修复: 完整走 tushare_write_lock + 克隆活库→TEMP_DB + set_active_db(TEMP_DB) +
      update_stk_factor + CHECKPOINT + 校验 + os.replace 原子交换，与 main() 同架构。
"""
import os, sys, subprocess
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

from core.db_lock import tushare_write_lock, start_hard_watchdog
import update_tushare_api as ut

start_hard_watchdog(25, label='backfill_stk_factor')  # 2026-09-01 防霸锁
import duckdb

with tushare_write_lock(timeout=600):
    print("=" * 60)
    print("周末 stk_factor 补拉（原子交换版）")
    print("=" * 60)

    # 0. C' 前置：stk_factor/index_daily_raw 已最新 → 直接退出不克隆（2026-08-24）
    #    背景: 16:00 主更新拉到今天数据后，17:40 补拉仍无条件克隆 65G → 白写白校验。
    #    基准日: 工作日=今天, 周六=周五, 周日=周五（节假日多跑一次无害，增量 0 行）。
    import datetime
    _today = datetime.date.today()
    _wd = _today.weekday()
    _base = _today - datetime.timedelta(days=_wd - 4) if _wd >= 5 else _today
    _base_s = _base.strftime('%Y%m%d')
    try:
        _rc = duckdb.connect(str(ut.TUSHARE_DB), read_only=True)
        _mx_sf = str(_rc.execute("SELECT MAX(trade_date) FROM stk_factor").fetchone()[0] or '')
        _mx_ix = str(_rc.execute("SELECT MAX(trade_date) FROM index_daily_raw").fetchone()[0] or '')
        _rc.close()
        _mx_sf = _mx_sf.replace('-', '')
        _mx_ix = _mx_ix.replace('-', '')
        if _mx_sf >= _base_s and _mx_ix >= _base_s:
            print(f"✅ 已最新（stk_factor={_mx_sf} index_daily_raw={_mx_ix} ≥ 基准{_base_s}），无缺口，跳过补拉不克隆")
            sys.exit(0)
        print(f"  有缺口: stk_factor={_mx_sf or '无'} index_daily_raw={_mx_ix or '无'} 基准={_base_s} → 继续补拉")
    except Exception as e:
        print(f"⚠️ C' 检查失败（继续补拉）: {str(e)[:100]}")

    # 1. 清理残留 + 克隆活库 → 临时库（APFS CoW）
    if ut.TEMP_DB.exists():
        ut.TEMP_DB.unlink()
    _tmp_wal = Path(str(ut.TEMP_DB) + '.wal')
    if _tmp_wal.exists():
        # 2026-08-24 事故：16:00 更新中途被杀留下损坏 .new.wal，
        # 克隆后 replay 直接 Corrupt → 必须一并清理
        print(f"⚠️ 清理残留临时库 WAL: {_tmp_wal.name}")
        _tmp_wal.unlink()
    # 2026-08-24 加固：克隆前先 CHECKPOINT 活库合并 WAL（否则 cp -c 只复制主文件丢 WAL 数据）
    try:
        vc = duckdb.connect(str(ut.TUSHARE_DB), read_only=False)
        vc.execute("CHECKPOINT")
        vc.close()
        print("✅ 活库 CHECKPOINT 完成（WAL 已合并）")
    except Exception as e:
        print(f"⚠️ 活库 CHECKPOINT 失败: {str(e)[:100]}")
    r = subprocess.run(['cp', '-c', str(ut.TUSHARE_DB), str(ut.TEMP_DB)], capture_output=True)
    if r.returncode != 0:
        import shutil
        shutil.copy2(str(ut.TUSHARE_DB), str(ut.TEMP_DB))
    print("✅ 克隆到临时库")

    # 2. 写入目标切换到临时库（所有读写走 TEMP_DB，活库全程只读）
    ut.set_active_db(ut.TEMP_DB)

    # 3. 执行 stk_factor 增量 + 14 天缺口回补 + 重试（逻辑同 update_tushare_api main）
    pro = ut.get_pro()
    n = ut.update_stk_factor(pro)
    print(f"update_stk_factor 返回: {n}")

    # 3.5 index_daily_raw 增量（2026-08-24 用户拍板：纳入 17:40 补拉窗口）
    #    背景: 8/21 指数上游 16:00 未算完 → 本机 index 停 8/20，无补拉机制残留缺口
    #    （M2 迁移后增量恰好补上）。update_index_daily 逐 ts_code 增量，秒级，
    #    走 get_db_writable（set_active_db 后即 TEMP_DB，与 stk_factor 同库同交换）。
    try:
        n_idx = ut.update_index_daily(pro)
        print(f"update_index_daily 返回: {n_idx}")
    except Exception as e:
        print(f"⚠️ update_index_daily 失败（不阻断 stk_factor 交换）: {str(e)[:100]}")

    # 4. CHECKPOINT（WAL 合并）+ 校验临时库
    vc = duckdb.connect(str(ut.TEMP_DB), read_only=False)
    vc.execute("CHECKPOINT")
    vc.close()
    vc = duckdb.connect(str(ut.TEMP_DB), read_only=True)
    mx = vc.execute("SELECT MAX(trade_date) FROM stk_factor").fetchone()[0]
    nmx = vc.execute("SELECT COUNT(*) FROM stk_factor WHERE trade_date=?", (mx,)).fetchone()[0]
    tot = vc.execute("SELECT COUNT(*) FROM stk_factor").fetchone()[0]
    mx_idx = vc.execute("SELECT MAX(trade_date) FROM index_daily_raw").fetchone()[0]
    vc.close()
    print(f"✅ 临时库校验: stk_factor MAX={mx} ({nmx} 行), 总 {tot} 行 | index_daily_raw MAX={mx_idx}")

    # 5. 原子交换
    os.replace(str(ut.TEMP_DB), str(ut.TUSHARE_DB))
    ut.set_active_db(ut.TUSHARE_DB)
    print("✅ 原子交换完成")

    # 6. 复验活库
    vc = duckdb.connect(str(ut.TUSHARE_DB), read_only=True)
    mx2 = vc.execute("SELECT MAX(trade_date) FROM stk_factor").fetchone()[0]
    nmx2 = vc.execute("SELECT COUNT(*) FROM stk_factor WHERE trade_date=?", (mx2,)).fetchone()[0]
    mx_idx2 = vc.execute("SELECT MAX(trade_date) FROM index_daily_raw").fetchone()[0]
    vc.close()
    print(f"✅ 活库复验: stk_factor MAX={mx2} ({nmx2} 行) | index_daily_raw MAX={mx_idx2}")
