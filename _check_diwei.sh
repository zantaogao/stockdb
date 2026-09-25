#!/bin/bash
cd ~/.hermes/cron/output/2e55e47d3ccd
for f in 2026-09-07_10*.md 2026-09-07_11*.md; do
  echo "=== $f"
  awk '/## Script Output/,/监督任务/' "$f" | grep -E '大盘|迪威尔|688377|订单|SELL|pending' | head -8
done