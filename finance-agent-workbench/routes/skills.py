"""Skills API — Skill 目录静态展示（2026-08-19 新增）。

对齐智能体优化 3.0 的 Skill 架构（L0 agent.md 触发词 → L1 SKILL.md 按需）：
提供只读的 skill 清单 + 详情（含解析出的工作流步骤），供前端
「AI 功能配置 → Skill 配置」页展示。用户无修改权限（静态展示）。

数据源：`.github/skills/*/SKILL.md`（frontmatter + 正文 markdown）。
"""

from __future__ import annotations

import re
from flask import Blueprint

from routes._utils import error, success

skills_bp = Blueprint("skills_api", __name__, url_prefix="/api/skills")


def _parse_skill_md(text: str) -> dict:
    """解析 SKILL.md：frontmatter + 职责 + 步骤（含分支）+ 约束 + 能力。

    Returns:
        {name, description, user_invocable, purpose, steps, constraints, capabilities}
        steps: [{n, title, summary, branch_point, branches}]
            branch_point: 步骤标题含 ★ → True
            branches: [{key, title, summary}]（#### 分支 X：... 子级，无则空）
        capabilities: {models: [...], stats: [...], charts: [...]}
    """
    # frontmatter（--- 包裹）
    name = ""
    description = ""
    user_invocable = True
    fm = re.search(r"^---\s*\n(.*?)\n---\s*\n?", text, re.DOTALL)
    if fm:
        for line in fm.group(1).splitlines():
            line = line.strip()
            if not line or ":" not in line:
                continue
            key, _, val = line.partition(":")
            key = key.strip().lower()
            val = val.strip()
            if val and val[0] in "\"'" and val[-1] == val[0]:
                val = val[1:-1]
            if key == "name":
                name = val
            elif key == "description":
                description = val
            elif key == "user-invocable":
                user_invocable = val.lower() in ("true", "yes", "1")
    body = text[fm.end():] if fm else text

    # 职责（## 职责 到下一个 ## 之间的段落）
    purpose = ""
    m = re.search(r"##\s*职责\s*\n(.*?)(?=\n##\s|\Z)", body, re.DOTALL)
    if m:
        purpose = m.group(1).strip().replace("\n", " ")

    # 步骤（### 步骤 N：标题 + #### 分支 + 首段摘要）
    steps: list[dict] = []
    for m in re.finditer(r"###\s*步骤\s*(\d+)[:：]\s*([^\n]+)\n(.*?)(?=\n###\s|\n##\s|\Z)", body, re.DOTALL):
        n = int(m.group(1))
        title = m.group(2).strip()
        block = m.group(3)
        branch_point = "★" in title
        # 分支（#### 分支 X：标题 + 首段摘要）
        branches: list[dict] = []
        for bm in re.finditer(r"####\s*分支\s*(\S+)[:：]\s*([^\n]+)\n(.*?)(?=\n####\s|\n###\s|\n##\s|\Z)", block, re.DOTALL):
            key = bm.group(1).strip()
            btitle = bm.group(2).strip()
            bfirst = next((p.strip() for p in bm.group(3).splitlines() if p.strip()), "")
            bfirst = re.sub(r"[#*`>]+|^[-*]\s*", "", bfirst).strip()
            branches.append({"key": key, "title": btitle, "summary": bfirst[:100]})
        # 主摘要：去掉分支块后取第一段
        main_block = re.sub(r"####\s*分支.*?(?=\n###\s|\n##\s|\Z)", "", block, flags=re.DOTALL)
        first_para = next((p.strip() for p in main_block.splitlines() if p.strip()), "")
        first_para = re.sub(r"[#*`>]+|^[-*]\s*", "", first_para).strip()
        steps.append({
            "n": n,
            "title": title.replace("★", "").strip(),
            "summary": first_para[:120],
            "branch_point": branch_point,
            "branches": branches,
        })
    steps.sort(key=lambda s: s["n"])

    # 约束（## 约束 段落）
    constraints = ""
    m = re.search(r"##\s*约束\s*\n(.*?)(?=\n##\s|\Z)", body, re.DOTALL)
    if m:
        constraints = m.group(1).strip()

    return {
        "name": name,
        "description": description,
        "user_invocable": user_invocable,
        "purpose": purpose,
        "steps": steps,
        "constraints": constraints,
        "capabilities": _parse_capabilities(body),
    }


def _parse_capabilities(body: str) -> dict:
    """解析能力全景：模型矩阵 / 统计能力 / 图表能力（从 SKILL.md 索引段提取）。

    Returns: {models: [{category, name, count, items}], stats: [...], charts: [...]}
    """
    models: list[dict] = []
    # 模型索引（A-G 段落）：`- **A 报表预测**：A1 三表联动 / A2 ...`
    # 项分隔符用「空格+/+空格」；模型内部「名称/别名」用紧邻斜杠（如 本量利/盈亏平衡）
    msec = re.search(r"##\s*模型索引[^\n]*\n(.*?)(?=\n##\s|\Z)", body, re.DOTALL)
    if msec:
        for line in msec.group(1).splitlines():
            mm = re.match(r"-\s*\*\*([A-G])\s*([^\*]+)\*\*[:：]\s*(.+)", line.strip())
            if mm:
                cat = mm.group(1).strip()
                cname = mm.group(2).strip()
                items = [it.strip() for it in re.split(r"\s+/\s+", mm.group(3).strip()) if it.strip()]
                models.append({"category": cat, "name": cname, "count": len(items), "items": items})
    # 统计能力（分析工具段：首行工具清单 + 注释行）
    stats: list[str] = []
    ssec = re.search(r"##\s*分析工具[^\n]*\n(.*?)(?=\n##\s|\Z)", body, re.DOTALL)
    if ssec:
        tool_line = ""
        for line in ssec.group(1).splitlines():
            line = line.strip()
            if not line or line.startswith(">"):
                # 空行 / `>` 引用注释（如「> L1 无对应 → run_python_code」）不算工具
                continue
            if line.startswith("-"):
                txt = re.sub(r"[`*#]+", "", line.lstrip("- ")).strip()
                if txt:
                    stats.append(txt[:80])
            elif tool_line == "":
                tool_line = line
        if tool_line:
            # 拆出工具名（取括号前 + 空格分隔）
            parts = re.split(r"\s*/\s*", tool_line)
            names = []
            for p in parts:
                nm = re.sub(r"\s*\(.*?\).*$", "", p).strip()
                if nm:
                    names.append(nm)
            stats = names + stats
    # 图表能力（图表模板索引段：只收集「纯模板名行」——英文+斜杠，不含中文/括号/变体说明）
    charts: list[str] = []
    csec = re.search(r"##\s*图表模板索引[^\n]*\n(.*?)(?=\n##\s|\Z)", body, re.DOTALL)
    if csec:
        raw = ""
        for line in csec.group(1).splitlines():
            line = line.strip()
            if not line or line.startswith("-"):
                continue
            # 跳过变体说明行（含中文「默认」或括号（…））——P5 变体清单
            if re.search(r"[\u4e00-\u9fff]|[（(]", line):
                continue
            raw += " " + line
        charts = [c.strip() for c in re.split(r"\s*/\s*", raw) if c.strip()]
    return {"models": models, "stats": stats, "charts": charts}


def _strip_trigger_tail(desc: str) -> str:
    """剥离 description 末尾的『触发词：…』部分——主体描述单独展示，
    触发词由 trigger_words chips 单独渲染（避免重复冗杂）。"""
    if not desc:
        return desc
    m = re.search(r"触发词[:：]", desc)
    if m:
        return desc[:m.start()].rstrip("。；;，, \t")
    return desc


# ------------------------------------------------------------------
# GET /api/skills — 全部 skill 清单（含触发词/步骤数，供列表展示）
# ------------------------------------------------------------------
@skills_bp.get("")
def list_skills():
    """返回全部 skill 的静态目录。"""
    from agent.skill_loader import extract_trigger_words, list_skills as scan
    try:
        items = []
        for s in scan():
            desc = s.get("description") or ""
            items.append({
                "name": s.get("name", ""),
                "description": _strip_trigger_tail(desc),
                "trigger_words": extract_trigger_words(desc),
                "step_count": len(_parse_skill_md(_read(s.get("path", "")))["steps"])
                if s.get("path") else 0,
                "path": s.get("path", ""),
            })
        return success({"skills": items})
    except Exception as e:  # noqa: BLE001
        return error(f"加载 skill 清单失败: {e}")


# ------------------------------------------------------------------
# GET /api/skills/<name> — 单个 skill 详情（含工作流步骤）
# ------------------------------------------------------------------
@skills_bp.get("/<skill_name>")
def get_skill(skill_name: str):
    """返回单个 skill 详情（名称/描述/触发词/职责/工作流步骤/约束）。"""
    from agent.skill_loader import extract_trigger_words, read_skill
    try:
        content = read_skill(skill_name)
        if content.startswith("未找到 skill"):
            return error(content, 404)
        parsed = _parse_skill_md(content)
        return success({
            "name": parsed["name"] or skill_name,
            "description": _strip_trigger_tail(parsed["description"]),
            "user_invocable": parsed["user_invocable"],
            "trigger_words": extract_trigger_words(parsed["description"]),
            "purpose": parsed["purpose"],
            "steps": parsed["steps"],
            "constraints": parsed["constraints"],
            "capabilities": parsed["capabilities"],
            "content": content,
        })
    except Exception as e:  # noqa: BLE001
        return error(f"加载 skill 详情失败: {e}")


def _read(path: str) -> str:
    """读取 SKILL.md 文本（容错）。"""
    try:
        from pathlib import Path
        p = Path(path)
        return p.read_text(encoding="utf-8") if p.exists() else ""
    except Exception:  # noqa: BLE001
        return ""
