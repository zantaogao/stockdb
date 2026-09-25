#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""盘前核查：给指定票算 5日涨幅 / 距20日新高 / 近3日累计 / 连涨天数。tushare.db 只读。"""
import duckdb
import sys

CODES = [
    # 主账户持仓
    ("688636", "智明达(持)"), ("301557", "常友科技(持)"), ("301237", "和顺科技(持)"),
    ("688093", "世华科技(持)"), ("002454", "松芝股份(持)"), ("603966", "法兰泰克(持+融合榜1)"),
    ("301093", "华兰股份(持)"), ("603202", "天有为(持)"), ("601615", "明阳智能(持)"),
    ("688186", "广大特材(持)"), ("001332", "锡装股份(持+融合榜)"), ("300658", "延江股份(持)"),
    ("301110", "青木科技(持)"), ("300986", "志特新材(持)"), ("605598", "上海港湾(持)"),
    # 融合榜其余
    ("688377", "迪威尔(融合)"), ("688576", "西山科技(融合)"), ("688081", "兴图新科(融合)"),
    ("688191", "智洋创新(融合)"), ("300812", "易天股份(融合)"), ("301413", "安培龙(融合)"),
    ("300680", "隆盛科技(融合)"),
    # 中枢+三模型榜
    ("603811", "诚意药业(双)"), ("301338", "凯格精机(双)"), ("688021", "奥福科技(双)"),
    ("300274", "阳光电源(双)"), ("300176", "鸿特科技(双)"), ("002864", "盘龙药业(双)"),
    ("300971", "博亚精工(双)"), ("688410", "山外山(双)"), ("300724", "捷佳伟创(双)"),
    ("301601", "惠通科技(双)"),
    # 中枢版榜
    ("301103", "何氏眼科(中)"), ("600658", "电子城(中)"), ("000599", "青岛双星(中)"),
    ("600322", "津投城开(中)"), ("688733", "壹石通(中)"), ("301032", "新柴股份(中)"),
    ("300158", "振东制药(中)"), ("600116", "三峡水利(中)"), ("300318", "博晖创新(中)"),
    ("301508", "中机认检(中)"),
    # 10d 独立榜
    ("600076", "康欣新材(10d)"), ("300328", "宜安科技(10d)"), ("603090", "宏盛股份(10d)"),
    ("688073", "毕得医药(10d)"), ("600785", "新华百货(10d)"), ("300864", "南大环境(10d)"),
    ("688062", "迈威生物(10d)"), ("002346", "柘中股份(10d)"), ("002491", "通鼎互联(10d)"),
    ("300839", "博汇股份(10d)"),
]

con = duckdb.connect("/Users/zantao/.hermes/stockdb/tushare.db", read_only=True)
maxd = con.execute("SELECT MAX(trade_date) FROM daily").fetchone()[0]
print("最新交易日:", maxd)
print()
print(f"{'名称':22s} {'现价':>8s} {'5日%':>7s} {'3日%':>7s} {'20日高':>8s} {'距高%':>7s} {'连涨':>4s} {'20日位置%':>8s}")
rows_out = []
for code, name in CODES:
    q = """
    WITH t AS (
      SELECT trade_date, close, high, low
      FROM daily WHERE ts_code LIKE ? || '%' AND trade_date <= ?
      ORDER BY trade_date DESC LIMIT 25
    )
    SELECT trade_date, close, high, low FROM t ORDER BY trade_date
    """
    try:
        df = con.execute(q, [code, maxd]).fetchdf()
    except Exception as e:
        print(f"{name:22s} 查询失败 {e}")
        continue
    if len(df) < 6:
        print(f"{name:22s} 数据不足({len(df)}行)")
        continue
    closes = df["close"].tolist()
    highs = df["high"].tolist()
    last = closes[-1]
    c5 = (last / closes[-6] - 1) * 100
    c3 = (last / closes[-4] - 1) * 100
    hi20 = max(highs[-21:] if len(highs) >= 21 else highs)
    dist_hi = (hi20 - last) / last * 100
    # 连涨天数
    up = 0
    for i in range(len(closes) - 1, 0, -1):
        if closes[i] > closes[i - 1]:
            up += 1
        else:
            break
    lo20 = min(closes[-21:] if len(closes) >= 21 else closes)
    pos = (last - lo20) / (hi20 - lo20) * 100 if hi20 > lo20 else 0
    print(f"{name:22s} {last:8.2f} {c5:+7.2f} {c3:+7.2f} {hi20:8.2f} {dist_hi:+7.2f} {up:4d} {pos:8.1f}")
    rows_out.append((code, name, last, c5, c3, dist_hi, up, pos))

con.close()
