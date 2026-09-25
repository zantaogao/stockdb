"""
信号历史存储（JSON 文件）
替代 tushare.db 里的 signal_history 表，避免数据库写入。
"""
import json
from pathlib import Path
from datetime import date, datetime

BASE = Path.home() / '.hermes' / 'stockdb'
SIGNAL_FILE = BASE / 'score_results.json'


def _load_all() -> list[dict]:
    """加载全部信号"""
    if SIGNAL_FILE.exists():
        with open(SIGNAL_FILE, 'r') as f:
            return json.load(f)
    return []


def _save_all(signals: list[dict]):
    """写入文件"""
    with open(SIGNAL_FILE, 'w') as f:
        json.dump(signals, f, ensure_ascii=False, indent=2)


def add_signals(signals: list[dict]):
    """
    批量添加/替换信号。按 (date, stock_code) 去重替换。
    """
    existing = _load_all()
    # 构建索引
    idx = {}
    for s in existing:
        key = (s.get('date'), s.get('stock_code'))
        idx[key] = s
    for s in signals:
        key = (s.get('date'), s.get('stock_code'))
        idx[key] = s
    _save_all(list(idx.values()))


def delete_signals(date_str: str = None, stock_codes: list[str] = None):
    """删除指定日期的信号"""
    existing = _load_all()
    if not date_str and not stock_codes:
        _save_all([])
        return
    kept = []
    for s in existing:
        if date_str and str(s.get('date')) != date_str:
            kept.append(s)
            continue
        if stock_codes and s.get('stock_code') in stock_codes:
            continue
        kept.append(s)
    _save_all(kept)


def get_latest_date() -> str:
    """返回最新信号日期"""
    signals = _load_all()
    if not signals:
        return None
    dates = [str(s.get('date', '')) for s in signals if s.get('date')]
    return max(dates) if dates else None


def get_by_date(date_str: str) -> list[dict]:
    """获取指定日期的所有信号"""
    return [s for s in _load_all() if str(s.get('date')) == date_str]


def get_top_scored(date_str: str = None, limit: int = 200, min_score: float = 25) -> list[dict]:
    """
    获取高分信号，按 final_score 降序。
    默认取最新日期的信号。
    """
    signals = _load_all()
    if date_str:
        signals = [s for s in signals if str(s.get('date')) == date_str]
    else:
        latest = get_latest_date()
        if latest:
            signals = [s for s in signals if str(s.get('date')) == latest]
    # 过滤 ST
    signals = [s for s in signals
               if (not s.get('stock_name') or '%ST%' not in s.get('stock_name', ''))]
    # 按 final_score 降序
    signals.sort(key=lambda x: float(x.get('final_score', 0) or 0), reverse=True)
    return signals[:limit]


def get_by_stocks(date_str: str, stock_codes: list[str]) -> list[dict]:
    """获取指定股票在指定日期的信号"""
    return [s for s in _load_all()
            if str(s.get('date')) == date_str and s.get('stock_code') in stock_codes]


def count_by_date(date_str: str) -> int:
    """统计指定日期的信号数"""
    return len(get_by_date(date_str))
