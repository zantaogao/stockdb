#!/usr/bin/env python3
"""
推荐分析 → 经验总结 → 选股手冊生成器

每月/每季度运行一次，分析推荐记录中的成功/失败模式，
生成结构化经验手册，指导后续选股决策。

用法:
  python3 scripts/lesson_learner.py                  # 生成总结报告
  python3 scripts/lesson_learner.py --save-skill     # 生成并另存为skill
  python3 scripts/lesson_learner.py --min-samples 10 # 设定最少样本量(默认15)
"""

import json
import os
import sys
import argparse
from datetime import datetime, timedelta
from collections import Counter, defaultdict

LOG_PATH = os.path.expanduser("~/.hermes/stockdb/recommendations_log.json")
SKILL_DIR = os.path.expanduser("~/.hermes/skills")


def load_log():
    if not os.path.exists(LOG_PATH):
        return {"recommendations": []}
    with open(LOG_PATH, "r") as f:
        return json.load(f)


def analyze_patterns(recs, min_samples=15):
    """分析推荐记录，提取模式和经验教训"""
    total = len(recs)
    resolved = [r for r in recs if r["outcome"] in ("正确", "错误")]
    
    if len(resolved) < min_samples:
        return None, f"样本不足：已结算{len(resolved)}条，需要≥{min_samples}条才能得出有统计意义的结论"
    
    print(f"\n📊 分析 {len(resolved)} 条已结算推荐...\n")
    
    lessons = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "total_recommendations": total,
        "resolved_count": len(resolved),
        "correct_count": sum(1 for r in resolved if r["outcome"] == "正确"),
        "wrong_count": sum(1 for r in resolved if r["outcome"] == "错误"),
        "by_score_bracket": {},
        "by_category": {},
        "by_direction": {},
        "lessons_learned": [],
        "statements": []
    }
    
    correct = lessons["correct_count"]
    wrong = lessons["wrong_count"]
    total_resolved = len(resolved)
    accuracy = correct / total_resolved if total_resolved > 0 else 0
    lessons["overall_accuracy"] = round(accuracy * 100, 1)
    
    print(f"总推荐: {total} | 已结算: {len(resolved)} | 正确: {correct} | 错误: {wrong}")
    print(f"总体准确率: {lessons['overall_accuracy']}%")
    
    # === 按评分段分析 ===
    brackets = [("0-49", 0, 49), ("50-69", 50, 69), ("70-79", 70, 79), ("80-89", 80, 89), ("90-100", 90, 100)]
    for label, lo, hi in brackets:
        items = [r for r in resolved if r["score"] is not None and lo <= r["score"] <= hi]
        if items:
            c = sum(1 for r in items if r["outcome"] == "正确")
            w = sum(1 for r in items if r["outcome"] == "错误")
            acc = c / (c + w) * 100 if (c + w) > 0 else 0
            avg_pnl = sum(r["pnl_pct"] for r in items if r["pnl_pct"] is not None) / max(len(items), 1)
            lessons["by_score_bracket"][label] = {
                "count": len(items),
                "correct": c,
                "wrong": w,
                "accuracy_pct": round(acc, 1),
                "avg_pnl_pct": round(avg_pnl, 2)
            }
            print(f"  {label}分: {c}/{len(items)}={acc:.1f}% | 平均盈亏:{avg_pnl:+.2f}%")
    
    # === 按推荐类别分析 ===
    cat_items = defaultdict(list)
    for r in resolved:
        cat = r.get("category") or "未分类"
        cat_items[cat].append(r)
    
    for cat, items in sorted(cat_items.items()):
        c = sum(1 for r in items if r["outcome"] == "正确")
        w = sum(1 for r in items if r["outcome"] == "错误")
        if len(items) >= 3:  # 至少3条才有统计意义
            acc = c / (c + w) * 100 if (c + w) > 0 else 0
            avg_pnl = sum(r["pnl_pct"] for r in items if r["pnl_pct"] is not None) / max(len(items), 1)
            lessons["by_category"][cat] = {
                "count": len(items),
                "correct": c,
                "wrong": w,
                "accuracy_pct": round(acc, 1),
                "avg_pnl_pct": round(avg_pnl, 2)
            }
            print(f"  类别[{cat}]: {c}/{len(items)}={acc:.1f}% | 平均盈亏:{avg_pnl:+.2f}%")
    
    # === 按方向分析 ===
    for direction in ["介入", "观察", "不参与"]:
        items = [r for r in resolved if r["direction"] == direction]
        if items:
            c = sum(1 for r in items if r["outcome"] == "正确")
            w = sum(1 for r in items if r["outcome"] == "错误")
            acc = c / (c + w) * 100 if (c + w) > 0 else 0
            avg_pnl = sum(r["pnl_pct"] for r in items if r["pnl_pct"] is not None) / max(len(items), 1)
            lessons["by_direction"][direction] = {
                "count": len(items),
                "correct": c,
                "wrong": w,
                "accuracy_pct": round(acc, 1),
                "avg_pnl_pct": round(avg_pnl, 2)
            }
    
    # === 生成经验教训 ===
    # 1. 评分阈值的有效性
    bracket_lessons = []
    for label, info in lessons["by_score_bracket"].items():
        if info["count"] >= 3:
            if info["accuracy_pct"] >= 70:
                bracket_lessons.append(f"✅ {label}分段准确率{info['accuracy_pct']}% — 阈值有效，继续保持")
            elif info["accuracy_pct"] >= 50:
                bracket_lessons.append(f"⚠️ {label}分段准确率{info['accuracy_pct']}% — 处于随机水平，需关注")
            else:
                bracket_lessons.append(f"❌ {label}分段准确率{info['accuracy_pct']}% — 低于随机，需要调整权重")
    
    if bracket_lessons:
        lessons["lessons_learned"].append("阈值有效性: " + "; ".join(bracket_lessons))
    
    # 2. 类别有效性
    for cat, info in lessons["by_category"].items():
        if info["count"] >= 3:
            if info["accuracy_pct"] >= 70:
                lessons["statements"].append(f"「{cat}」类推荐准确率{info['accuracy_pct']}%，属于强项，后续可重点挖掘")
            elif info["accuracy_pct"] < 40:
                lessons["statements"].append(f"「{cat}」类推荐准确率{info['accuracy_pct']}%，属于弱项，后续应更谨慎或避免")
    
    # 3. 典型失败案例
    bad_cases = [r for r in resolved if r["outcome"] == "错误"]
    if bad_cases:
        bad_cases_sorted = sorted(bad_cases, key=lambda r: r["pnl_pct"] or 0)
        top_failures = bad_cases_sorted[:3]
        for r in top_failures:
            lessons["lessons_learned"].append(
                f"失败案例: {r['name']}({r['code']}) 亏损{r['pnl_pct']:+.1f}% — {r['rationale'][:60]}"
            )
    
    # 4. 归因总结
    if lessons["overall_accuracy"] >= 65:
        lessons["statements"].append(f"总体准确率{lessons['overall_accuracy']}%，选股体系有效，可继续使用")
    elif lessons["overall_accuracy"] >= 50:
        lessons["statements"].append(f"总体准确率{lessons['overall_accuracy']}%，略优于随机，需要持续优化")
    else:
        lessons["statements"].append(f"总体准确率{lessons['overall_accuracy']}%，低于随机，建议全面复盘评分体系")
    
    return lessons, None


def format_report(lessons):
    """格式化为可读报告"""
    lines = []
    lines.append(f"# 📊 推荐验证月度报告")
    lines.append(f"生成时间: {lessons['generated_at']}")
    lines.append(f"")
    lines.append(f"## 总体统计")
    lines.append(f"- 总推荐: {lessons['total_recommendations']} 条")
    lines.append(f"- 已结算: {lessons['resolved_count']} 条")
    lines.append(f"- 正确: {lessons['correct_count']}")
    lines.append(f"- 错误: {lessons['wrong_count']}")
    lines.append(f"- **总体准确率: {lessons['overall_accuracy']}%**")
    lines.append(f"")
    
    # 按评分段
    if lessons["by_score_bracket"]:
        lines.append(f"## 评分段表现")
        lines.append(f"| 评分段 | 数量 | 正确 | 错误 | 准确率 | 平均盈亏 |")
        lines.append(f"|--------|------|------|------|--------|---------|")
        for label, info in sorted(lessons["by_score_bracket"].items()):
            lines.append(f"| {label} | {info['count']} | {info['correct']} | {info['wrong']} | {info['accuracy_pct']}% | {info['avg_pnl_pct']:+.2f}% |")
        lines.append(f"")
    
    # 按类别
    if lessons["by_category"]:
        lines.append(f"## 类别表现")
        lines.append(f"| 类别 | 数量 | 正确 | 错误 | 准确率 | 平均盈亏 |")
        lines.append(f"|------|------|------|------|--------|---------|")
        for cat, info in sorted(lessons["by_category"].items()):
            lines.append(f"| {cat} | {info['count']} | {info['correct']} | {info['wrong']} | {info['accuracy_pct']}% | {info['avg_pnl_pct']:+.2f}% |")
        lines.append(f"")
    
    # 经验教训
    if lessons["lessons_learned"]:
        lines.append(f"## 经验教训")
        for l in lessons["lessons_learned"]:
            lines.append(f"- {l}")
        lines.append(f"")
    
    if lessons["statements"]:
        lines.append(f"## 结论与建议")
        for s in lessons["statements"]:
            lines.append(f"- {s}")
        lines.append(f"")
    
    return "\n".join(lines)


def save_as_skill(lessons):
    """将经验总结保存为skill文件"""
    skill_content = f"""---
name: stock-picking-lessons
description: "根据历史推荐验证数据自动生成的选股经验手册，指导后续选股决策。"
version: 1.0.0
author: Recommendation Learner
tags: [finance, stock, lessons]
---

# 选股经验手册

生成时间: {lessons['generated_at']}

## 总体表现

- 总体准确率: **{lessons['overall_accuracy']}%**
- 已结算推荐: {lessons['resolved_count']} 条

## 评分段准确率

| 评分段 | 准确率 | 建议 |
|--------|--------|------|
"""
    for label, info in sorted(lessons["by_score_bracket"].items()):
        if info["accuracy_pct"] >= 70:
            advice = "✅ 可信，大胆使用"
        elif info["accuracy_pct"] >= 50:
            advice = "⚠️ 参考，需结合其他因素"
        else:
            advice = "❌ 不可信，需调整"
        skill_content += f"| {label} | {info['accuracy_pct']}% | {advice} |\n"
    
    skill_content += f"""
## 类别表现

"""
    for cat, info in sorted(lessons["by_category"].items()):
        skill_content += f"- **{cat}**: {info['accuracy_pct']}%准确率, 平均盈亏{info['avg_pnl_pct']:+.2f}%\n"
    
    skill_content += f"""
## 经验教训总结

"""
    for l in lessons["lessons_learned"]:
        skill_content += f"- {l}\n"
    
    skill_content += f"""
## 操作指南

"""
    for s in lessons["statements"]:
        skill_content += f"- {s}\n"
    
    skill_content += """
## 使用说明

本skill由 `lesson_learner.py` 自动生成，每次运行会覆盖更新。
建议每月运行一次，或在积累20+条已结算推荐后运行。
"""
    
    skill_path = os.path.join(SKILL_DIR, "stock-picking-lessons", "SKILL.md")
    os.makedirs(os.path.dirname(skill_path), exist_ok=True)
    with open(skill_path, "w") as f:
        f.write(skill_content)
    
    print(f"\n✅ 选股经验已保存为skill: stock-picking-lessons")
    print(f"   路径: {skill_path}")
    return skill_path


def main():
    parser = argparse.ArgumentParser(description="选股经验学习器")
    parser.add_argument("--save-skill", action="store_true", help="保存为skill")
    parser.add_argument("--min-samples", type=int, default=15, help="最小样本量(默认15)")
    parser.add_argument("--report", action="store_true", help="只输出报告不保存")
    args = parser.parse_args()
    
    data = load_log()
    recs = data["recommendations"]
    
    lessons, error = analyze_patterns(recs, args.min_samples)
    
    if error:
        print(f"⚠️ {error}")
        return
    
    report = format_report(lessons)
    print(f"\n{report}")
    
    if args.save_skill or not args.report:
        save_as_skill(lessons)


if __name__ == "__main__":
    main()
