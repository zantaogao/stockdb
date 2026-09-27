#!/usr/bin/env python3
"""生成 A股交易日历 → data/trade_cal.json（2026-09-26 新增）

用途：health_check_scores.py 推算"最近交易日"时使用**真实交易日历**（含法定节假日），
      替代原来只跳周末的近似 → 消除周末/节假日假 FAIL（2026-09-25 中秋休市误报 3 表 FAIL）。

⚠️ 关键设计：日历独立于被检查的库（state.db/tushare.db）——不能用 daily 的 MAX 日期当基准，
   否则"数据更新链整体断掉"时预期会跟着塌到昨天 → 漏报真实断链。

用法：python3 -B scripts/gen_trade_cal.py [起始年] [结束年]      # 默认 2024-2028
建议：每年 12 月重跑一次（覆盖下一年），或发现"超出范围"告警时重跑。
"""
import json
import sys
from datetime import datetime
from pathlib import Path

BASE = Path.home() / '.hermes' / 'stockdb'
CONFIG = BASE / 'config.json'
OUT = BASE / 'data' / 'trade_cal.json'


def main():
    y0 = int(sys.argv[1]) if len(sys.argv) > 1 else 2024
    y1 = int(sys.argv[2]) if len(sys.argv) > 2 else 2028
    try:
        import tushare as ts
    except ImportError:
        print("❌ 需要 tushare（用 PATH 里的 python3）")
        sys.exit(1)
    try:
        token = json.load(open(CONFIG)).get('tushare_token', '')
    except Exception as e:
        print(f"❌ 读 config.json 失败: {e}")
        sys.exit(1)
    if not token or token == 'YOUR_TOKEN':
        print("❌ config.json 未配置 tushare_token")
        sys.exit(1)

    ts.set_token(token)
    pro = ts.pro_api()
    df = pro.trade_cal(exchange='SSE', start_date=f'{y0}0101', end_date=f'{y1}1231')
    opens = sorted(df[df['is_open'] == 1]['cal_date'].astype(str).tolist())
    if not opens:
        print("❌ trade_cal 返回空（接口权限/网络？）")
        sys.exit(1)

    payload = {
        'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'source': f'tushare trade_cal(exchange=SSE) {y0}-{y1}',
        'range': [opens[0], opens[-1]],
        'n': len(opens),
        'is_open_dates': opens,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, 'w') as f:
        json.dump(payload, f, ensure_ascii=False, indent=0)
    print(f"✅ {OUT}")
    print(f"   共 {len(opens)} 个交易日，范围 {opens[0]} ~ {opens[-1]}，生成于 {payload['generated_at']}")
    for d in ['20260924', '20260925', '20260926', '20260928', '20261001', '20261008']:
        print(f"   {d}: {'交易日' if d in opens else '休市'}")


if __name__ == '__main__':
    main()
