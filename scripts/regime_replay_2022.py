#!/usr/bin/env python3
"""满仓运作环境分层回放（09-12 立项）
问题：非大跌市满仓是否合适——需要跨年、分环境（大跌/温和跌/平/涨）的 top10 收益证据。
做法：对每个历史交易日用当前模型链全市场评分（as_of 防泄漏），存每日 top50 +
中证1000当日涨跌幅环境标签；收益 T+1/T+5/T+10 用复权价（adj_factor）后算，分析阶段做。
输出：~/.hermes/stockdb/replay/regime_replay.duckdb  replay_top50 表（幂等，可断点续跑）
注意：当前模型训练含 2022-2026 样本内，早期年份回放是 in-sample——只用于分环境的
相对对比，不当无偏 IC 用。分析时报告里注明。
用法：nice python3 -B scripts/regime_replay_2022.py [start_YYYYMMDD] [end_YYYYMMDD]
"""
import os, sys, time
sys.path.insert(0, os.path.expanduser('~/.hermes/stockdb'))

START_DEFAULT = '20220104'
END_DEFAULT = '20260911'
OUT = os.path.expanduser('~/.hermes/stockdb/replay/regime_replay.duckdb')
N_WORKERS = 8  # 09-13 用户定：mlx 停掉后回 8。mlx-serve 在跑时脚本自动降到 4
               # （09-12 教训：8 worker + mlx-serve 78G 顶满 128G → 缺页风暴 → 看门狗 panic 重启）
TOP_KEEP = 50  # 每天留前50名，分析时可切top10/top20

def _mlx_running():
    """mlx-serve 是否在跑：它常驻 ~78G，和 8 worker 抢内存会诱发看门狗 panic。"""
    import subprocess
    try:
        return bool(subprocess.run(['pgrep', '-f', 'mlx-serve'],
                                   capture_output=True, text=True).stdout.strip())
    except Exception:
        return False

def _effective_workers():
    if N_WORKERS > 4 and _mlx_running():
        print(f"[guard] mlx-serve 在跑 → worker {N_WORKERS} 自动降为 4（09-12 panic 教训）",
              flush=True)
        return 4
    return N_WORKERS

_G = {}

def _init_worker():
    from core.scoring import _load_models
    import duckdb
    _load_models()
    conn = duckdb.connect(os.path.expanduser('~/.hermes/stockdb/tushare.db'), read_only=True)
    # 09-13 加固：DuckDB 默认 memory_limit=物理内存80%，4 个 worker 各自膨胀会顶爆 128G
    # （09-12 就是这么触发看门狗 panic 的），单 worker 限 3G + 限线程。
    conn.execute("SET memory_limit='3GB'")
    conn.execute("SET threads=2")
    _G['conn'] = conn

def _score_one(args):
    ts, date = args
    conn = _G['conn']
    from core.scoring import score_stock
    code = ts.split('.')[0]
    try:
        rows = conn.execute(
            "SELECT trade_date, close, open, high, low, pct_chg, vol, amount FROM daily "
            f"WHERE ts_code='{ts}' AND trade_date <= '{date}' ORDER BY trade_date DESC LIMIT 200"
        ).fetchall()
        if len(rows) < 120:
            return (date, None)
        s = score_stock(code, rows, conn=conn, as_of_date=date)
        if not s:
            return (date, None)
        return (date, (date, ts, s.get('reg10_pred'), s.get('reg_pred'),
                s.get('reg40_pred'), s.get('fusion_v9'), s.get('final_score')))
    except Exception:
        return (date, None)

def main():
    start = sys.argv[1] if len(sys.argv) > 1 else START_DEFAULT
    end = sys.argv[2] if len(sys.argv) > 2 else END_DEFAULT
    import duckdb
    from multiprocessing import Pool

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    out = duckdb.connect(OUT)
    out.execute("""CREATE TABLE IF NOT EXISTS replay_top50 (
        date VARCHAR, ts_code VARCHAR, reg10 DOUBLE, reg20 DOUBLE, reg40 DOUBLE,
        fusion REAL, final_score REAL,
        PRIMARY KEY (date, ts_code))""")
    done = {r[0] for r in out.execute("SELECT DISTINCT date FROM replay_top50").fetchall()}

    src = duckdb.connect(os.path.expanduser('~/.hermes/stockdb/tushare.db'), read_only=True)
    src.execute("SET memory_limit='4GB'")
    src.execute("SET threads=2")
    days = [r[0] for r in src.execute(
        f"SELECT DISTINCT trade_date FROM daily WHERE trade_date BETWEEN '{start}' AND '{end}' ORDER BY 1"
    ).fetchall()]
    todo = [d for d in days if d not in done]
    print(f"交易日 {len(days)}，已完成 {len(days)-len(todo)}，本轮 {len(todo)}", flush=True)

    t0 = time.time()
    tasks = []
    day_universe = {}
    for d in todo:
        day_universe[d] = [r[0] for r in src.execute(
            f"SELECT ts_code FROM daily WHERE trade_date='{d}' AND (ts_code LIKE '%.SH' OR ts_code LIKE '%.SZ')"
        ).fetchall()]
        tasks.extend((ts, d) for ts in day_universe[d])
    n_workers = _effective_workers()
    print(f"总任务 {len(tasks)} 票×日，{n_workers} 进程", flush=True)

    by_day = {d: [] for d in todo}
    n_tasks_day = {d: len(v) for d, v in day_universe.items()}
    seen = {d: 0 for d in todo}
    with Pool(n_workers, initializer=_init_worker) as pool:
        for day, r in pool.imap_unordered(_score_one, tasks, chunksize=50):
            if r is not None:
                by_day[day].append(r)
            seen[day] += 1
            if seen[day] >= n_tasks_day[day]:  # 该日全部票已评完
                res = by_day[day]
                res.sort(key=lambda x: (x[5] if x[5] is not None else -999), reverse=True)
                out.executemany("INSERT OR REPLACE INTO replay_top50 VALUES (?,?,?,?,?,?,?)", res[:TOP_KEEP])
                out.commit()
                done.add(day)
                el = time.time() - t0
                rate = len(done) / el
                eta = (len(todo) - len(done)) / rate / 3600
                print(f"[{len(done)}/{len(todo)}] {day}: scored {len(res)} "
                      f"top1={res[0][1] if res else '-'} | ETA {eta:.1f}h", flush=True)
    out.close()

if __name__ == '__main__':
    main()
