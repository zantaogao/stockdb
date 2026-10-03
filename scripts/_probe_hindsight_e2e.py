"""Hindsight 上线验收: retain→recall 端到端 (bank=aquant). 事实取自 OPS_FACTS 真实口径."""
from hindsight_client import Hindsight
import time

c = Hindsight(base_url="http://127.0.0.1:8899")
BANK = "aquant"
for txt in [
    "用户拍板：fusion 融合公式 2026-09-27 晚 v8 上线后 Mac 生产改为 0.25*reg10 + 0.75*reg40，reg20 剔除出融合但字段照落库观察。",
    "全量 LightGBM 训练(700万行级)禁止在 Mac 上直接跑，会炸内存。分工是 Mac 建样本 parquet，PC(192.168.3.168) 负责训练。Mac 只跑特征/IC级脚本(<100万行)。",
    "用户铁律：kill/restart/切换模型必须先问；训练前备份 .bak；删除任何文件或任务须用户同意；交易时段 9:30-15:00 禁止外部交易操作。",
]:
    r = c.retain(bank_id=BANK, content=txt)
    print("retain ->", r, flush=True)
time.sleep(40)  # 异步抽取等 LLM
for q in ["融合公式现在用的什么权重",
          "为什么大训练不在笔记本上跑",
          "我想删文件之前得先做什么"]:
    res = c.recall(bank_id=BANK, query=q, max_tokens=600)
    print(f"\nQ: {q}")
    got = False
    for it in (getattr(res, "results", None) or getattr(res, "items", None) or []):
        txt = getattr(it, "text", None) or getattr(it, "content", None) or getattr(it, "observation", None) or str(it)
        print("  A:", str(txt)[:200]); got = True
    if not got:
        print("  RAW:", str(res)[:500])
