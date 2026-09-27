# Findings: 双轨OBV级别差为锚点差而非口径漂移 (2026-09-25 双轨对比监督)

## 现象
20260924 双轨对比: Top10 重合 10/10, fusion 秩相关 1.000000, 5166 票。
逐值对拍 (extra JSON `_bfq` 键 vs indicator_bfq, 23 字段 x 5510 票) 仅 1 个字段有差异:
`obv_bfq`, 3 票超 0.5% 容差: 600018.SH (差 401.8), 000537.SZ (差 2317.5), 000601.SZ (差 5044.3)。

## 核实过程 (scripts/_verify_selfind_source_0925{,b,c,d,e,f,g}.py, 全部只读)
1. 0925.py: 直接列名对比 common cols=0 —— 无效率 (真值在 extra JSON, 直接列恒 0, 见 feat_tushare.py 08-01 修复注释)。
2. 0925c.py: 走正确路径 (extra `_bfq` 键, 与 _get_self_factor 映射一致): 20 键可比, 仅 obv 3 票差异。
3. 0925d.py: 3 票均不在任一 Top10。
4. 0925f.py: 9 月逐日 delta 对比 —— 两轨 obv 每日增量与 K 线 signed volume 逐日一致 (误差仅浮点舍入)。
   → 两侧每日计算口径完全相同, 无缺日/无停牌处理差 (pct_chg=0 日两侧都记 0 增量)。
5. 0925g.py: 全历史对拍 (各 ~2600 个共同交易日) —— offset 恒定无跳变。
   自算 obv 按 compute_indicators.py 注释"上市首日起点"全历史累加; tushare stk_factor 的 obv
   回溯覆盖不到上市首日, 其最早可得日自带一个基数 (即 tushare 侧起算点比上市首日晚)。

## 结论
- OBV 级别差 = **积分常数差 (tushare 回看窗口起点 ≠ 上市首日)**, 非任一侧口径漂移。
- 每日增量两侧逐日全等 → 对横截面排名类衍生 (scoring.py GTJA 用 rankdata 百分位) 影响为零。
- Top10 与 fusion 秩相关 1.0 与该解释一致。双轨对比口径干净, 维持"✅ 正常"。
- 注意: 若模型把 obv_bfq 当**原始绝对值**特征用 (core/features.py L392 有直取路径),
  两轨 3/5510 票存在恒定级差 (最大 000601 约 5044/万手)。当前融合排序无影响;
  如需绝对值口径统一, 须先明确哪侧为权威源 (涉及训练/推理对齐, 未动)。
