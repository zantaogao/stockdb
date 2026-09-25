"""
DuckDB 文件锁 — 防损坏/防 stale
===================================
用法：
    from core.db_lock import FileLock
    with FileLock('/path/to/db.lock'):
        conn = duckdb.connect('tushare.db', read_only=True)
        ...

Stale 锁检测：锁文件超过 30 分钟自动视为 stale，强制释放。
写锁超时 30 秒（更新脚本），读锁超时 10 秒（评分/IC）。
"""
import fcntl
import os
import time
from pathlib import Path
from contextlib import contextmanager

BASE = Path.home() / '.hermes' / 'stockdb'
LOCK_FILE = BASE / 'tushare.db.lock'
_STALE_TIMEOUT = 1800  # 30分钟，超过此时间的锁视为 stale


def _check_stale():
    """检查锁文件是否 stale（进程崩溃后遗留的锁）"""
    if not os.path.exists(LOCK_FILE):
        return
    try:
        mtime = os.path.getmtime(LOCK_FILE)
        if time.time() - mtime > _STALE_TIMEOUT:
            # 文件超过 30 分钟没更新 → 进程已死，释放
            with open(LOCK_FILE, 'w') as f:
                pass
    except OSError:
        pass


@contextmanager
def tushare_write_lock(timeout=30):
    """获取 tushare.db 写锁（用于更新脚本）"""
    _check_stale()
    lock_file = open(LOCK_FILE, 'w')
    try:
        start = time.time()
        while True:
            try:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                yield
                break
            except BlockingIOError:
                if time.time() - start > timeout:
                    raise TimeoutError("tushare.db 写锁超时（可能被评分或 IC 计算占用）")
                time.sleep(0.5)
    finally:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
        lock_file.close()


def start_hard_watchdog(minutes, label=''):
    """进程级硬超时：无论卡死在哪（HTTP无超时挂起、锁死循环等），
    超过 minutes 分钟直接 SIGKILL 自杀并打印错误。
    防止僵尸进程霸占 tushare.db.lock（2026-09-01 事故：16:00/22:00
    两个更新进程无超时挂死 40-78 分钟，卡死全链数据更新）。
    用 SIGKILL：卡死线程连 except/finally 都走不到，只能外部杀。"""
    import threading, signal
    def _kill():
        print(f"⛔ [看门狗] {label} 超过 {minutes} 分钟未完成，自杀退出（防霸锁）",
              flush=True)
        os.kill(os.getpid(), signal.SIGKILL)
    t = threading.Timer(minutes * 60, _kill)
    t.daemon = True
    t.start()
    return t


class PhasedWatchdog:
    """分相硬看门狗（2026-09-14 事故后加）：一刀切总时限在 09-14 把
    "拉取已全部完成、只剩全表强读校验"的正常进程 SIGKILL 在换库前
    （70G 校验被 16:10 双任务+实验下载拖慢，撞 40min 线）。
    分相后每相独立限时：enter_phase() 重计时，前相未完成即超时会杀，
    防卡死霸锁的原始目的保留。"""

    def __init__(self, label=''):
        self.label = label
        self._timer = None

    def enter_phase(self, minutes, phase=''):
        import threading, signal
        if self._timer is not None:
            try:
                self._timer.cancel()
            except Exception:
                pass

        def _kill():
            print(f"⛔ [看门狗] {self.label} 相位[{phase}] 超过 {minutes} "
                  f"分钟未完成，自杀退出（防霸锁）", flush=True)
            os.kill(os.getpid(), signal.SIGKILL)
        self._timer = threading.Timer(minutes * 60, _kill)
        self._timer.daemon = True
        self._timer.start()



@contextmanager
def tushare_read_lock(timeout=10):
    """获取 tushare.db 读锁（用于评分、IC 计算等读取操作）"""
    _check_stale()
    lock_file = open(LOCK_FILE, 'w')
    try:
        start = time.time()
        while True:
            try:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_SH | fcntl.LOCK_NB)
                yield
                break
            except BlockingIOError:
                if time.time() - start > timeout:
                    raise TimeoutError("tushare.db 读锁超时（可能被更新脚本占用）")
                time.sleep(0.2)
    finally:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
        lock_file.close()
