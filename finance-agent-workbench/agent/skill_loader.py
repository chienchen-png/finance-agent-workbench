"""skill_loader — Skill/Agent 声明式加载器（智能体优化 3.0 阶段 B）。

对齐 VS Code Copilot 的 Progressive Loading 三层模型：
  L0 常驻：agent.md（角色 + 工具原则 + skill 清单触发词，<300 token）
  L1 按需：SKILL.md（read_skill 工具读取正文进上下文）
  L2 资源：references/ assets/（用时才读）

模块函数：
- list_skills()            → [{name, description, path}]（~100 token/个）
- read_skill(name)         → SKILL.md 正文（L1 按需）
- read_skill_resource(skill, path) → references/ 子文件正文（L2 按需，防路径穿越）
- extract_trigger_words()  → 从 description 提取触发关键词
- build_skill_index()      → L0 注入的 skill 清单文本
- read_agent_md()          → .github/agents/general-agent.agent.md 正文
- validate_agent_tools()   → 铁律 0：agent.md tools 白名单 vs 注册工具比对
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

# 仓库根目录（skill_loader.py 位于 agent/ 下，向上两级）
ROOT_DIR = Path(__file__).resolve().parent.parent
AGENTS_DIR = ROOT_DIR / ".github" / "agents"
SKILLS_DIR = ROOT_DIR / ".github" / "skills"

# 默认智能体定义文件
DEFAULT_AGENT_MD = AGENTS_DIR / "general-agent.agent.md"

# frontmatter 解析（--- 包裹的 YAML 头）
_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?", re.DOTALL)


def _parse_frontmatter(text: str) -> dict:
    """Parse YAML-ish frontmatter (name/description/user-invocable/tools)."""
    m = _FRONTMATTER_RE.match(text or "")
    if not m:
        return {}
    meta: dict = {}
    for line in m.group(1).splitlines():
        line = line.strip()
        if not line or ":" not in line:
            continue
        key, _, val = line.partition(":")
        key = key.strip().lower()
        val = val.strip()
        # 引号包裹的值
        if val and val[0] in "\"'" and val[-1] == val[0]:
            val = val[1:-1]
        if key == "name":
            meta["name"] = val
        elif key == "description":
            meta["description"] = val
        elif key == "user-invocable":
            meta["user_invocable"] = val.lower() in ("true", "yes", "1")
        elif key == "tools":
            # [a, b, c] 或逗号分隔
            items = re.findall(r"[a-zA-Z_][\w._-]*", val)
            meta["tools"] = items
    return meta


def list_skills() -> list[dict]:
    """扫描 .github/skills/*/SKILL.md，解析 frontmatter。

    Returns: [{name, description, path}]（~100 token/个）
    """
    results: list[dict] = []
    if not SKILLS_DIR.exists():
        return results
    for sk_dir in sorted(SKILLS_DIR.iterdir()):
        if not sk_dir.is_dir():
            continue
        skill_md = sk_dir / "SKILL.md"
        if not skill_md.exists():
            continue
        try:
            text = skill_md.read_text(encoding="utf-8")
        except Exception:  # noqa: BLE001
            continue
        meta = _parse_frontmatter(text)
        if not meta.get("name"):
            meta["name"] = sk_dir.name
        meta["path"] = str(skill_md)
        results.append(meta)
    return results


def read_skill(name: str) -> str:
    """读取 .github/skills/<name>/SKILL.md 正文（L1 按需）。

    AI 用 read_skill 工具调用；返回完整 markdown（含 frontmatter 摘要）。
    """
    safe = (name or "").strip().replace("..", "").replace("/", "").replace("\\", "")
    if not safe:
        return "未指定 skill 名称"
    skill_md = SKILLS_DIR / safe / "SKILL.md"
    if not skill_md.exists():
        available = [s.get("name", p.name) for p, s in
                     ((d, _parse_frontmatter((d / "SKILL.md").read_text(encoding="utf-8")))
                      for d in SKILLS_DIR.iterdir() if (d / "SKILL.md").exists())]
        return f"未找到 skill「{safe}」；可用: {', '.join(available) or '无'}"
    try:
        return skill_md.read_text(encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        return f"读取 skill 失败: {e}"


def read_skill_resource(skill: str, path: str) -> str:
    """读取 .github/skills/<skill>/references/<path> 正文（L2 按需）。

    financial-modeling skill 的 references/ 含 models/（32 个模型规则）与
    charts/（16 个图表模板选型）。AI 从 SKILL.md 索引得知「有什么」后，
    需要细节时用本函数按需读取（防一次上下文注入过度）。

    Security：skill 名去路径分隔符（防越级读其他目录）；path 用 resolve()
    校验必须落在该 skill 的 references/ 目录内（防目录穿越 ../）。
    """
    safe_skill = (skill or "").strip().replace("..", "").replace("/", "").replace("\\", "")
    if not safe_skill:
        return "未指定 skill 名称"
    ref_dir = (SKILLS_DIR / safe_skill / "references").resolve()
    if not ref_dir.exists():
        return f"skill「{safe_skill}」没有 references/ 资源目录"
    raw = (path or "").strip().lstrip("/").lstrip("\\")
    if not raw:
        # 无路径 → 返回目录清单
        return _list_ref_dir(ref_dir)
    target = (ref_dir / raw).resolve()
    # 防目录穿越：目标必须仍在 references/ 内
    if ref_dir != target and not str(target).startswith(str(ref_dir) + chr(92)) and \
            not str(target).startswith(str(ref_dir) + "/"):
        return f"路径越界被拒绝：{raw}（只能访问 references/ 内文件）"
    if not target.exists() or not target.is_file():
        return f"未找到资源「{raw}」；可用: {_list_ref_dir(ref_dir)}"
    try:
        return target.read_text(encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        return f"读取资源失败: {e}"


def _list_ref_dir(ref_dir: Path) -> str:
    """列出 references/ 下的资源文件（含子目录相对路径）。"""
    if not ref_dir.exists():
        return "（无资源）"
    items = []
    for p in sorted(ref_dir.rglob("*.md")):
        items.append(str(p.relative_to(ref_dir)).replace("\\", "/"))
    return "\n".join(items) if items else "（无资源）"


def extract_trigger_words(description: str) -> list[str]:
    """从 description 自动提取触发关键词（如『核对/对不上/差异/比对』）。"""
    if not description:
        return []
    # 触发词：通常在「触发词：」后跟 [..] 或 顿号/逗号分隔
    m = re.search(r"触发词[:：]\s*[\[【]?\s*([^\]】\n]+)", description)
    if m:
        raw = m.group(1)
        words = re.split(r"[、,，/|]+", raw)
        words = [w.strip() for w in words if w.strip()]
        if words:
            return words
    # 兜底：提取中文字符串中的财务特征词
    fallback = [w for w in ("核对", "对账", "对不上", "差异", "比对", "分级",
                            "查询", "统计", "修改", "写回", "回款", "提成")
                if w in description]
    return fallback


def build_skill_index() -> str:
    """生成 L0 注入的 skill 清单文本（name + description 触发词，~100 token/skill）。

    ```
    [可用 Skill]
    - data-reconcile: 触发词 [核对, 对不上, 差异, 比对, 分级]。财务数据核对方法论
      （含核对后填充修正与写回闭环）。
      当任务命中触发词时，用 read_skill 工具读取对应 SKILL.md，按其流程执行。
    ```
    """
    skills = list_skills()
    if not skills:
        return ""
    lines = ["[可用 Skill]"]
    for s in skills:
        desc = (s.get("description") or "").strip()
        trig = extract_trigger_words(desc)
        trig_txt = ("触发词 [" + ", ".join(trig) + "]。") if trig else ""
        lines.append(f"- {s.get('name')}: {trig_txt}{desc}")
    lines.append("当任务命中触发词时，用 read_skill 工具读取对应 SKILL.md，按其流程执行。")
    return "\n".join(lines)


def read_agent_md(path: str | None = None) -> str:
    """读取 agent.md 正文（L0 常驻）。"""
    p = Path(path) if path else DEFAULT_AGENT_MD
    if not p.exists():
        return ""
    try:
        return p.read_text(encoding="utf-8")
    except Exception:  # noqa: BLE001
        return ""


def validate_agent_tools(agent_md_path: str | None = None,
                         registered_tools: list[str] | None = None) -> list[str]:
    """铁律 0：比对 agent.md 的 tools 白名单与已注册工具。

    agent.md 的 tools 是**能力描述**（供 AI 了解可选工具）；真正能否调用由
    TOOL_CLASSES 注册决定。这里返回「白名单未覆盖的已注册工具」（发现 L0
    描述遗漏 → 启动时 WARNING 提示补全），不影响工具调用。

    Args:
        agent_md_path: agent.md 路径（默认 general-agent.agent.md）
        registered_tools: 已注册工具名列表（如 [t.name for t in TOOL_CLASSES]）

    Returns:
        白名单未覆盖的已注册工具名列表（空 = 全覆盖）
    """
    text = read_agent_md(agent_md_path)
    if not text:
        return list(registered_tools or [])
    meta = _parse_frontmatter(text)
    whitelist = set(meta.get("tools") or [])
    missing = [t for t in (registered_tools or []) if t not in whitelist]
    return missing
