#!/usr/bin/env python3
"""CLI：派生显示层重导出（薄封装 core.derived_export，2026-09-17 建立）。

  python3 -B scripts/sync_derived_json.py --dry-run
  python3 -B scripts/sync_derived_json.py
  python3 -B scripts/sync_derived_json.py --verify      # 有漂移 exit 1
  python3 -B scripts/sync_derived_json.py --accounts fusion3f,fusion_dual
"""
import os
import sys

_SCRIPT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

from core.derived_export import main  # noqa: E402

if __name__ == '__main__':
    main()
