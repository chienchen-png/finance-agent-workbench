"""Tool title/icon/summary rendering — Phase 16 (UX 掌控感).

Converts raw tool-call payloads into human-readable verb phrases so the
frontend can show "读取 data/2026Q2.xlsx · 对账单" instead of raw JSON
(`{"file": "2026Q2_流水.xlsx"}`), and turns raw tool results into short
summaries ("返回 128 行 / 5 列") instead of str(dict)[:300].

Design principles (from 项目架构文档 §4.2 对话与智能体运行):
  P1 人类可读动词短语优先
  P6 终态只留最终答案 — summaries are short, details live in the drawer

All functions are pure & defensive: unknown tools fall back to the raw
name/args, and a missing key never raises.
"""

from __future__ import annotations

from typing import Any

# ------------------------------------------------------------------
# Tool metadata: icon + category + verb template
# ------------------------------------------------------------------
TOOL_META: dict[str, dict[str, str]] = {
    # ── 计划与交互 ──
    "ask_user":          {"icon": "❓", "category": "交互", "verb": "询问", "template": "询问用户"},
    "plan_task":         {"icon": "📋", "category": "计划", "verb": "规划", "template": "生成执行计划"},

    # ── 文件操作 ──
    "read_file":         {"icon": "📄", "category": "文件", "verb": "读取", "template": "读取 {path}"},
    "list_directory":    {"icon": "📂", "category": "文件", "verb": "浏览", "template": "浏览目录 {path}"},
    "search_files":      {"icon": "🔍", "category": "文件", "verb": "搜索", "template": "搜索 {pattern}"},
    "write_file":        {"icon": "✍️", "category": "文件", "verb": "写入", "template": "写入 {path}"},
    "create_directory":  {"icon": "📁", "category": "文件", "verb": "创建", "template": "创建目录 {path}"},
    "delete_path":       {"icon": "🗑️", "category": "文件", "verb": "删除", "template": "删除 {path}"},
    "move_path":         {"icon": "↪️", "category": "文件", "verb": "移动", "template": "移动 {source} → {destination}"},
    "copy_path":         {"icon": "📑", "category": "文件", "verb": "复制", "template": "复制 {source} → {destination}"},

    # ── 命令执行 ──
    "run_command":       {"icon": "⌨️", "category": "命令", "verb": "运行", "template": "运行 {command}"},

    # ── Python 环境 ──
    "get_python_version":        {"icon": "🐍", "category": "环境", "verb": "查看", "template": "查看 Python 版本"},
    "get_python_executable":     {"icon": "🐍", "category": "环境", "verb": "查看", "template": "查看 Python 解释器"},
    "get_installed_packages":    {"icon": "📦", "category": "环境", "verb": "列出", "template": "列出已安装的 Python 包"},
    "configure_python_environment": {"icon": "🛠️", "category": "环境", "verb": "配置", "template": "配置 Python 环境"},

    # ── Excel 操作 ──
    "read_excel":        {"icon": "📊", "category": "表格", "verb": "读取", "template": "读取 {path}"},
    "get_sheet_info":    {"icon": "📑", "category": "表格", "verb": "查看", "template": "查看表结构 {path}"},
    "write_excel":       {"icon": "✏️", "category": "表格", "verb": "写入", "template": "写入表格 {path}"},
    "analyze_excel":     {"icon": "🔬", "category": "表格", "verb": "分析", "template": "分析表格 {path}"},
    "compare_excel_sheets": {"icon": "⚖️", "category": "表格", "verb": "对比",
                             "template": "对比 {file1} 与 {file2}"},

    # ── 项目数据库 ──
    "import_excel_to_db": {"icon": "📥", "category": "数据库", "verb": "导入",
                           "template": "导入 {path} 到项目数据库"},
    "query_table":       {"icon": "🗃️", "category": "数据库", "verb": "查询", "template": "查询 {file}"},
    "table_stats":       {"icon": "📈", "category": "数据库", "verb": "统计", "template": "统计 {file}"},
    "join_tables":       {"icon": "🔗", "category": "数据库", "verb": "关联",
                          "template": "关联 {left_file} 与 {right_file}"},
    "update_rows":       {"icon": "🔄", "category": "数据库", "verb": "更新", "template": "更新 {file} 数据"},
    "insert_rows":       {"icon": "➕", "category": "数据库", "verb": "插入", "template": "向 {file} 插入行"},
    "delete_rows":       {"icon": "➖", "category": "数据库", "verb": "删除", "template": "删除 {file} 中符合条件的行"},
    "export_project_data": {"icon": "📤", "category": "数据库", "verb": "导出", "template": "回写 {path}"},
}

# Fallback icon/category for unknown tools
_FALLBACK_META = {"icon": "🔧", "category": "工具", "verb": "调用"}


def _meta(name: str) -> dict[str, str]:
    return TOOL_META.get(name, _FALLBACK_META)


def _fmt(value: Any) -> str:
    """Compact single-value formatter for template args."""
    if value is None:
        return ""
    s = str(value).strip()
    if not s:
        return ""
    if len(s) > 48:
        return s[:45] + "…"
    return s


def humanize_tool_call(name: str, args: dict | None) -> dict:
    """Build {title, icon, category} for a tool_started event.

    title is a human-readable verb phrase, e.g.
      read_file({"path": "data/2026Q2.xlsx", "start_line": 100, "end_line": 200})
        → "读取 data/2026Q2.xlsx L100–200"
      query_table({"file": "2026Q2_流水.xlsx", "sheet": "对账单"})
        → "查询 2026Q2_流水.xlsx · 对账单"
    Unknown tools fall back to "调用 read_file".
    """
    meta = _meta(name)
    args = args or {}
    template = meta.get("template", "调用 {name}")

    try:
        title = template.format(name=name, **_map_template_args(name, args))
    except (KeyError, IndexError, ValueError):
        title = f"{meta.get('verb', '调用')} {name}"

    return {
        "title": title,
        "icon": meta.get("icon", _FALLBACK_META["icon"]),
        "category": meta.get("category", _FALLBACK_META["category"]),
    }


def _map_template_args(name: str, args: dict) -> dict[str, str]:
    """Map tool-specific args into generic template keys (path/file/...)."""
    out: dict[str, str] = {}

    # Path-like keys
    for key in ("path", "file", "left_file", "right_file", "source", "destination",
                "pattern", "command", "file1", "file2"):
        if key in args:
            out[key] = _fmt(args[key])

    # query_table / table_stats: append sheet + limit context
    if name in ("query_table", "table_stats", "update_rows", "insert_rows", "delete_rows"):
        sheet = _fmt(args.get("sheet", ""))
        if sheet:
            out["file"] = f"{out.get('file', '')} · {sheet}".strip(" ·")
        limit = args.get("limit")
        if limit:
            out["file"] = f"{out.get('file', '')}（限 {limit} 行）".strip()

    # read_file: line range suffix
    if name == "read_file" and out.get("path"):
        start = args.get("start_line")
        end = args.get("end_line")
        if start or end:
            out["path"] = f"{out['path']} L{start or 1}–{end or '末'}"

    # run_command: keep command inline
    if name == "run_command" and out.get("command"):
        out["command"] = _fmt(args.get("command", "")).replace("`", "")

    # compare_excel_sheets: sheet hints
    if name == "compare_excel_sheets":
        s1 = _fmt(args.get("sheet1", ""))
        s2 = _fmt(args.get("sheet2", ""))
        if s1:
            out["file1"] = f"{out.get('file1', '')}:{s1}".strip(":")
        if s2:
            out["file2"] = f"{out.get('file2', '')}:{s2}".strip(":")

    return out


# ------------------------------------------------------------------
# Output summarizers — turn raw tool results into one-line summaries
# ------------------------------------------------------------------
def summarize_output(name: str, result: dict | Any) -> str:
    """One-line human summary of a tool result.

    Handles the common result shapes returned by tool implementations:
      {"success": True, "rows": [...], "row_count": n, ...}
      {"success": True, "columns": [...], ...}
      {"success": True, "output": "..."}  (run_command)
      {"success": False, "error": "..."}
    Falls back to a compact string of the raw result.
    """
    if isinstance(result, dict):
        if result.get("success") is False:
            return f"失败: {_fmt(result.get('error') or result.get('message') or '执行出错')}"

        # Row / column summaries (query_table / read_excel / compare)
        row_count = result.get("row_count") or result.get("total_rows")
        rows = result.get("rows") or result.get("data")
        if isinstance(rows, list) and not row_count:
            row_count = len(rows)
        columns = result.get("columns")
        if isinstance(columns, list) and columns and not isinstance(columns[0], str):
            columns = [c.get("name") for c in columns if isinstance(c, dict)]

        parts = []
        if row_count:
            parts.append(f"{row_count} 行")
        if columns:
            parts.append(f"{len(columns)} 列")
        if parts:
            return f"返回 {(' / '.join(parts))}"

        # run_command / file writes
        out = result.get("output")
        if isinstance(out, str) and out.strip():
            tail = out.strip().splitlines()
            tail = tail[-1] if tail else ""
            return f"完成 · {_fmt(tail)}"

        matched = result.get("matched_count") or result.get("match_count")
        if matched is not None:
            return f"匹配 {matched} 条"

        updated = result.get("updated_count") or result.get("affected_rows")
        if updated is not None:
            return f"已更新 {updated} 条"

        ok = result.get("ok") or result.get("status")
        if ok:
            return f"成功（{_fmt(ok)}）"

        # Fallback: compact repr
        return _fmt(str(result))[:80]

    s = str(result or "").strip()
    return _fmt(s)[:80]
