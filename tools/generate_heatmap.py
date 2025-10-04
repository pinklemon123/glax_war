#!/usr/bin/env python3
"""
基于编年史（Markdown）事件行，生成“战场热度图”（事件密度统计）。

用法：
  python tools/generate_heatmap.py <input_md> <output_md>

统计的事件类型（聚焦冲突强度）：
  - planet_conquered（占领了 X）
  - defense_success（成功保卫了 X）
  - combat（在 X 发生战斗）
  - colonization_contested（在争夺 X 时不敌更强的势力）

注意：本脚本只依赖标准库，可在容器内直接执行。
"""
from __future__ import annotations
import sys
import re
from collections import defaultdict, Counter
from typing import Dict, Tuple


PATTERNS = {
    "combat": re.compile(r"在\s*(?P<loc>[^\s]+)\s*发生战斗"),
    "planet_conquered": re.compile(r"占领了\s*(?P<loc>[^\s]+)\s*$"),
    "defense_success": re.compile(r"成功保卫了\s*(?P<loc>[^\s]+)\s*$"),
    "colonization_contested": re.compile(r"在争夺\s*(?P<loc>[^\s]+)\s*时不敌"),
}


def norm_loc(s: str) -> str:
    # 规范化地名：去掉尾部标点与多余空白
    return (s or "").strip().strip("，。,.！!；;：:")


def parse_heatmap(md_lines: list[str]) -> Tuple[Dict[str, Counter], Counter]:
    per_loc: Dict[str, Counter] = defaultdict(Counter)
    totals: Counter = Counter()

    for line in md_lines:
        text = line.strip()
        if not text or not text.startswith("- 回合"):
            continue
        for etype, pat in PATTERNS.items():
            m = pat.search(text)
            if not m:
                continue
            loc = norm_loc(m.group("loc"))
            if not loc:
                continue
            per_loc[loc][etype] += 1
            totals[loc] += 1
            break  # 一行只计一次（按优先匹配的事件类型）

    return per_loc, totals


def render_bar(n: int, max_n: int, width: int = 20) -> str:
    if max_n <= 0:
        return ""
    filled = int(round(width * (n / max_n)))
    return "█" * filled + "·" * (width - filled)


def write_output(per_loc: Dict[str, Counter], totals: Counter, out_path: str):
    lines: list[str] = []
    lines.append("# 战场热度图（事件密度统计）")
    lines.append("")
    lines.append("说明：基于编年史事件中与战斗/据点争夺直接相关的条目，统计各星体的事件密度。")
    lines.append("包含事件：占领、成功防守、战斗发生、殖民争夺失败（视作战场竞争）。")
    lines.append("")

    if not totals:
        lines.append("（无可统计事件）")
    else:
        max_n = max(totals.values())
        lines.append("## Top 热点战场（前 30）")
        lines.append("")
        lines.append("| # | 星体 | 总事件 | 占领 | 防守 | 战斗 | 殖民争夺 | 热度柱状 |")
        lines.append("|---:|:-----|------:|----:|----:|----:|----------:|:---------|")
        for rank, (loc, total) in enumerate(totals.most_common(30), start=1):
            c = per_loc[loc]
            bar = render_bar(total, max_n)
            lines.append(
                f"| {rank} | {loc} | {total} | {c.get('planet_conquered', 0)} | {c.get('defense_success', 0)} | {c.get('combat', 0)} | {c.get('colonization_contested', 0)} | {bar} |"
            )

        lines.append("")
        lines.append("### 事件类型分布（总览）")
        sum_counts = Counter()
        for c in per_loc.values():
            sum_counts.update(c)
        lines.append("- 占领：%d" % sum_counts.get("planet_conquered", 0))
        lines.append("- 防守：%d" % sum_counts.get("defense_success", 0))
        lines.append("- 战斗：%d" % sum_counts.get("combat", 0))
        lines.append("- 殖民争夺：%d" % sum_counts.get("colonization_contested", 0))

    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def main():
    if len(sys.argv) < 3:
        print("用法: python tools/generate_heatmap.py <input_md> <output_md>")
        sys.exit(2)
    in_path, out_path = sys.argv[1], sys.argv[2]
    with open(in_path, "r", encoding="utf-8") as f:
        lines = f.readlines()
    per_loc, totals = parse_heatmap(lines)
    write_output(per_loc, totals, out_path)
    print(f"已生成: {out_path}")


if __name__ == "__main__":
    main()
