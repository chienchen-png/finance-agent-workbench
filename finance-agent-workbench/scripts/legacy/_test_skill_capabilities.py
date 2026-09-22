# -*- coding: utf-8 -*-
"""P5-④ 收尾：Skill 能力全景解析测试（SKILL.md → capabilities）。

验证：
  1. 模型矩阵 7 类 32 模型
  2. 统计能力非空
  3. 图表模板 21 个（含 P5-③ 新类型 treemap/graph/parallel/error-bar/calendar）
  4. 变体说明行不被误解析为模板名（P5 变体清单兼容）

运行: python scripts/_test_skill_capabilities.py
"""
from __future__ import annotations

import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from routes.skills import _parse_capabilities, _read  # noqa: E402

FAIL = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(("PASS" if ok else "FAIL"), label, detail)
    if not ok:
        FAIL.append(label)


def main() -> None:
    body = _read(os.path.join(ROOT, ".github", "skills", "financial-modeling", "SKILL.md"))
    assert body, "SKILL.md 读取失败"
    caps = _parse_capabilities(body)

    # 1. 模型矩阵
    models = caps["models"]
    check("模型矩阵 7 类", len(models) == 7, f"{len(models)} 类")
    total = sum(m["count"] for m in models)
    check("模型总数 32", total == 32, f"{total} 个")

    # 2. 统计能力
    check("统计能力非空", len(caps["stats"]) > 0, f"{len(caps['stats'])} 项")

    # 3. 图表模板 24 个（含 P5-③ 新类型 + P6-② 3D/联动）
    charts = caps["charts"]
    check("图表模板 24 个", len(charts) == 24, f"{len(charts)} 个: {charts}")
    check("含 P5-③ 新类型", all(t in charts for t in ["treemap", "graph", "parallel", "error-bar", "calendar"]),
          f"缺失: {[t for t in ['treemap','graph','parallel','error-bar','calendar'] if t not in charts]}")
    check("含 P6-② 3D/联动", all(t in charts for t in ["scatter3d", "bar3d", "histogram-4grid"]),
          f"缺失: {[t for t in ['scatter3d','bar3d','histogram-4grid'] if t not in charts]}")

    # 4. 变体说明行不污染（不应解析出 line（smooth 默认 之类）
    check("无变体说明污染", not any("（" in c or "默认" in c for c in charts),
          f"污染项: {[c for c in charts if '（' in c or '默认' in c]}")

    print("\n失败项:", FAIL if FAIL else "无")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
