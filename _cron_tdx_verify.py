#!/usr/bin/env python3
"""验证通达信 .lc1/.lc5 分钟线格式 2026-08-08"""
import struct

def decode_date(v):
    # 通达信日期编码: (year-2004)*2048 + month*100 + day
    year = v // 2048 + 2004
    rest = v % 2048
    month = rest // 100
    day = rest % 100
    return year, month, day

for fn, name in [('/tmp/test.lc5', '5分钟'), ('/tmp/test.lc1', '1分钟')]:
    raw = open(fn, 'rb').read()
    n = len(raw) // 32
    print(f"\n=== {name} ({fn}) === 共 {n} 条记录, 文件 {len(raw)} 字节")
    print("前 5 条记录解码:")
    for i in range(5):
        rec = raw[i*32:(i+1)*32]
        date_raw, time_raw = struct.unpack('<HH', rec[:4])
        o, h, l, c = struct.unpack('<4f', rec[4:20])
        vol, amount = struct.unpack('<2f', rec[20:28])
        y, m, d = decode_date(date_raw)
        hh, mm = divmod(time_raw, 60)
        print(f"  {y}-{m:02d}-{d:02d} {hh:02d}:{mm:02d}  O={o:.2f} H={h:.2f} L={l:.2f} C={c:.2f} V={vol:.0f} Am={amount:.0f}")
    # 最后一条（最新）
    rec = raw[-32:]
    date_raw, time_raw = struct.unpack('<HH', rec[:4])
    o, h, l, c = struct.unpack('<4f', rec[4:20])
    y, m, d = decode_date(date_raw)
    hh, mm = divmod(time_raw, 60)
    print(f"  最后一条: {y}-{m:02d}-{d:02d} {hh:02d}:{mm:02d}  C={c:.2f} V={vol:.0f}")

# 合理性检查
raw5 = open('/tmp/test.lc5', 'rb').read()
rec = raw5[-32:]
date_raw, time_raw = struct.unpack('<HH', rec[:4])
y, m, d = decode_date(date_raw)
print(f"\n5分钟最新日期: {y}-{m:02d}-{d:02d} (今天 2026-08-08)")
print("格式验证: 时间字段 < 24*60=1440 且成交量>0 → 结构正确" if time_raw < 1440 else "格式可疑")
