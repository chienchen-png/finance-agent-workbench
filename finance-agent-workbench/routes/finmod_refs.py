"""finmod_refs — 财务建模应用 references 解析（P1 元数据层，2026-08-21 新增）。

数据源：`.github/skills/financial-modeling/references/`（financial-modeling skill 的
L2 按需加载资源）：
  - models/<编号>-<slug>.md   32 个模型规则/公式/变量表/适用场景
  - charts/<模板名>.md        24 个图表模板选型/数据结构/变体/档位

本模块把上述 markdown 资产解析为结构化 JSON，供应用二（财务建模与分析）的
元数据层端点使用：
  - GET /api/apps/finmod/meta           模型目录（A-G 分类）+ 图表目录（L1/L2/L3 档位）
  - GET /api/apps/finmod/models/<id>    单模型详情（目的/公式/变量表/适用场景）
  - GET /api/apps/finmod/charts/<id>    单图表模板详情（用途/数据结构/选型/变体）

静态缓存：解析结果按 lru_cache 缓存（references 为静态资产，运行期不变化）。

架构对齐：应用一的核对逻辑（reconcile_variables）放 tools/、路由放 routes/apps.py；
此处同样把「references 解析」与「端点」分离——本模块只做纯解析，端点注册在 apps.py。
"""

from __future__ import annotations

import logging
import re
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger(__name__)

# 仓库根（finmod_refs.py 位于 routes/ 下，向上两级 = finance-agent-workbench）
ROOT_DIR = Path(__file__).resolve().parent.parent
REF_DIR = ROOT_DIR / ".github" / "skills" / "financial-modeling" / "references"
MODELS_DIR = REF_DIR / "models"
CHARTS_DIR = REF_DIR / "charts"

# 模型分类（A-G，与 SKILL.md「模型索引」一致）
MODEL_CATEGORIES = {
    "A": "报表预测",
    "B": "预算预测",
    "C": "成本盈利",
    "D": "绩效比率",
    "E": "资本决策",
    "F": "营运资金",
    "G": "统计量化",
}

# 图表复杂度档位（与 SKILL.md「复杂度分级」一致）
CHART_LEVELS = {
    "L1": "简单",
    "L2": "中等",
    "L3": "复杂",
}

# 模型文件命名：<编号>-<slug>（如 a1-three-statement，扫描时传入 stem 不含扩展名）
_MODEL_FILE_RE = re.compile(r"^([a-g]\d+)-(.*)$", re.IGNORECASE)
# 文档一级标题：# A1 三表联动模型 / # 图表模板：line（折线图）
_TITLE_RE = re.compile(r"^#\s+(.+?)\s*$")
# 二级标题：## 目的
_SECTION_RE = re.compile(r"^##\s+(.+?)\s*$")
# 复杂度档位引用行：> **复杂度档位：L1 简单**（...）
_LEVEL_RE = re.compile(r"复杂度档位[：:]\s*([L1L2L3]{2})")
# 表格分隔行：| --- | --- |
_TABLE_SEP_RE = re.compile(r"^\s*\|?[\s:|-]+\|?\s*$")
# 列表项：- xxx / * xxx
_LIST_ITEM_RE = re.compile(r"^\s*[-*+]\s+(.+?)\s*$")
# $$ 公式块（跨行）
_FORMULA_RE = re.compile(r"\$\$(.+?)\$\$", re.DOTALL)


# ----------------------------------------------------------------------
# markdown 解析辅助
# ----------------------------------------------------------------------

def _strip_md(text: str) -> str:
    """去除行首尾空白（保留 markdown 语法，供前端 react-markdown 渲染）。"""
    return (text or "").strip()


def _split_sections(text: str) -> list[tuple[str, str]]:
    """按 `## 标题` 分节，返回 [(heading, content), ...]。

    文档头（`# 一级标题` 与引言）不属任何小节，被丢弃（标题单独解析）。
    """
    lines = (text or "").splitlines()
    sections: list[tuple[str, str]] = []
    cur_heading: str | None = None
    cur_buf: list[str] = []
    for line in lines:
        m = _SECTION_RE.match(line)
        if m:
            if cur_heading is not None:
                sections.append((cur_heading, _strip_md("\n".join(cur_buf))))
            cur_heading = m.group(1).strip()
            cur_buf = []
        else:
            cur_buf.append(line)
    if cur_heading is not None:
        sections.append((cur_heading, _strip_md("\n".join(cur_buf))))
    return sections


def _extract_formulas(text: str) -> list[str]:
    """提取 `$$...$$` 块级公式（含跨行），返回公式原文列表。"""
    out: list[str] = []
    for m in _FORMULA_RE.finditer(text or ""):
        out.append(m.group(1).strip())
    return out


def _extract_code_blocks(text: str) -> list[str]:
    """提取 ``` 围栏代码块内容（用于图表数据结构示例）。"""
    blocks = re.findall(r"```[^\n]*\n(.*?)```", text or "", re.DOTALL)
    return [b.strip() for b in blocks]


def _extract_list_items(text: str) -> list[str]:
    """提取列表项（- / * / + 开头），去前导符号。"""
    items: list[str] = []
    for line in (text or "").splitlines():
        m = _LIST_ITEM_RE.match(line)
        if m:
            items.append(_strip_md(m.group(1)))
    return items


def _parse_table(text: str) -> list[dict[str, str]]:
    """解析 markdown 表格 → [{表头: 单元格, ...}, ...]。

    兼容无表头分隔行（此时第一行即表头）、列数不等（缺列补空）。
    """
    lines = [ln.strip() for ln in (text or "").splitlines()
             if ln.strip() and not ln.strip().startswith(">")]
    if not lines:
        return []
    rows: list[list[str]] = []
    for ln in lines:
        if not ln.startswith("|"):
            continue
        cells = [c.strip() for c in ln.strip("|").split("|")]
        rows.append(cells)
    if not rows:
        return []
    if len(rows) >= 2 and _TABLE_SEP_RE.match(rows[1][0] if rows[1] else ""):
        headers, body = rows[0], rows[2:]
    else:
        headers, body = rows[0], rows[1:]
    if not headers:
        return []
    out: list[dict[str, str]] = []
    for r in body:
        row: dict[str, str] = {}
        for i, h in enumerate(headers):
            row[h] = r[i] if i < len(r) else ""
        out.append(row)
    return out


# ----------------------------------------------------------------------
# 模型变量「方向/类型」识别（v2.0 V1：变量映射升级）
# ----------------------------------------------------------------------
# 模型 references 变量含义表里的变量分三类：
#   - 输入（input）：需用户从表里选列（如 净利润、x_i、销售额）
#   - 统计量（statistic）：由输入列算出（如 n 样本量、x̄ 均值、s 标准差、R²）
#   - 输出（output）：模型计算结果，非输入（如 G3 回归的 a/b_i/ε、G5 的 α）
# 统计量/输出变量不应占用用户映射——`_finmod_varmap` 只让用户映射 input。

# 统计量变量特征（变量名 或 含义 命中 → statistic）
_STAT_VAR_RE = re.compile(
    r"(均值|标准差|方差|样本量|变异系数|中位数|众数|峰度|偏度|"
    r"拟合优度|显著性|残差|^n$|^x̄$|^s$|^CV$|^R²$|^R2$|^p\s*值$|^ε$|^e$|^α$|^a\b|^b\b|"
    r"截距|斜率|系数|指数$|趋势|季节|分量)"
)

# 输出/中间量特征（含义命中 → output）
_OUTPUT_VAR_RE = re.compile(
    r"(结果|输出|预测值|拟合值|分量$|系数$|指数$|截距|斜率|显著性|拟合优度|"
    r"周转率|周转天数|占比|差异|偏差|盈亏|保本|平衡点|边际贡献|杠杆|倍数|"
    r"敏感度|情景|区间|网格|指标$|同期|对比期|累计)"
)


def _classify_model_var(var_name: str, meaning: str) -> str:
    """变量方向分类：input / statistic / output（确定性规则，无 LLM）。

    references 变量表缺「方向」列时的兜底；命中统计量/输出特征 → 该分类，
    否则默认 input。模型 detail 直接带「方向」列时优先使用。
    """
    name = (var_name or "").strip()
    meaning = (meaning or "").strip()
    if _STAT_VAR_RE.search(name) or _STAT_VAR_RE.search(meaning):
        return "statistic"
    if _OUTPUT_VAR_RE.search(meaning):
        return "output"
    return "input"


def _norm_heading(h: str) -> str:
    """小节名规范化：去掉括号注释（如「变体清单（P5-②，template 传…）」→「变体清单」）。"""
    for sep in ("（", "("):
        h = h.split(sep)[0]
    return h.strip()


def _section_content(sections: list[tuple[str, str]], *names: str) -> str:
    """按小节名（可多个别名）取内容；找不到返回空串。"""
    targets = {_norm_heading(n) for n in names}
    for heading, content in sections:
        if _norm_heading(heading) in targets:
            return content
    return ""


# ----------------------------------------------------------------------
# 扫描：模型目录 / 图表目录（meta）
# ----------------------------------------------------------------------

def _parse_model_file(stem: str, text: str) -> dict | None:
    """解析单个模型 md：编号/名称/分类。返回 None 表示文件不匹配命名规范。"""
    m = _MODEL_FILE_RE.match(stem)
    if not m:
        return None
    code_raw = m.group(1)
    code = code_raw.upper()
    category = code[0]
    # 名称优先取一级标题（# A1 三表联动模型 → 去掉编号前缀）；否则用 slug
    name = ""
    for line in (text or "").splitlines():
        tm = _TITLE_RE.match(line)
        if tm:
            title = tm.group(1).strip()
            t = re.sub(r"^[A-Ga-g]\d+\s*", "", title)
            name = t.strip() or title
            break
    if not name:
        name = m.group(2).replace("-", " ")
    return {
        "id": stem,
        "code": code,
        "name": name,
        "category": category,
        "category_label": MODEL_CATEGORIES.get(category, ""),
    }


@lru_cache(maxsize=1)
def scan_models() -> list[dict]:
    """扫描 models/ 目录 → 32 个模型元信息（按编号排序）。"""
    out: list[dict] = []
    if not MODELS_DIR.exists():
        logger.warning("references/models 目录不存在: %s", MODELS_DIR)
        return out
    for p in sorted(MODELS_DIR.glob("*.md")):
        try:
            text = p.read_text(encoding="utf-8")
        except Exception:  # noqa: BLE001
            logger.warning("读取模型文件失败: %s", p)
            continue
        meta = _parse_model_file(p.stem, text)
        if meta:
            out.append(meta)
    out.sort(key=lambda x: (x["code"][0], int(re.sub(r"\D", "", x["code"]) or 0)))
    return out


def _parse_chart_file(stem: str, text: str) -> dict | None:
    """解析单个图表 md：名称/档位/变体。"""
    if not stem or not text.strip():
        return None
    name = ""
    for line in text.splitlines():
        tm = _TITLE_RE.match(line)
        if tm:
            title = tm.group(1).strip()
            # 去掉「图表模板：xxx（」前缀 → 括号内为中文名（如 折线图）
            inner = re.search(r"（(.+?)）", title)
            if inner:
                name = inner.group(1).strip()
            else:
                name = re.sub(r"^图表模板[：:]\s*", "", title)
            break
    if not name:
        name = stem
    level = "L1"
    lm = _LEVEL_RE.search(text)
    if lm:
        level = lm.group(1).upper()
        if level not in CHART_LEVELS:
            level = "L1"
    # 变体：从「变体清单」节表格解析（第一列表格单元含 `模板-变体` 名）
    variants: list[str] = []
    for heading, content in _split_sections(text):
        if _norm_heading(heading) != "变体清单":
            continue
        for row in _parse_table(content):
            for v in row.values():
                for tok in re.split(r"[、,，/\s]+", v):
                    tok = tok.strip().strip("`")
                    if tok.startswith(stem) and tok not in variants:
                        variants.append(tok)
        break
    return {
        "id": stem,
        "name": name,
        "level": level,
        "level_label": CHART_LEVELS.get(level, ""),
        "variants": variants,
    }


@lru_cache(maxsize=1)
def scan_charts() -> list[dict]:
    """扫描 charts/ 目录 → 24 个图表模板元信息（按名称排序）。"""
    out: list[dict] = []
    if not CHARTS_DIR.exists():
        logger.warning("references/charts 目录不存在: %s", CHARTS_DIR)
        return out
    for p in sorted(CHARTS_DIR.glob("*.md")):
        try:
            text = p.read_text(encoding="utf-8")
        except Exception:  # noqa: BLE001
            logger.warning("读取图表文件失败: %s", p)
            continue
        meta = _parse_chart_file(p.stem, text)
        if meta:
            out.append(meta)
    out.sort(key=lambda x: x["name"])
    return out


def get_meta() -> dict:
    """模型目录（A-G 分组）+ 图表目录（L1/L2/L3 分组）。"""
    models = scan_models()
    charts = scan_charts()
    model_categories = [
        {"key": key, "label": label,
         "models": [m for m in models if m["category"] == key]}
        for key, label in MODEL_CATEGORIES.items()
        if any(m["category"] == key for m in models)
    ]
    chart_levels = [
        {"key": key, "label": label,
         "charts": [c for c in charts if c["level"] == key]}
        for key, label in CHART_LEVELS.items()
        if any(c["level"] == key for c in charts)
    ]
    return {
        "model_categories": model_categories,
        "models": models,
        "chart_levels": chart_levels,
        "charts": charts,
        "counts": {"models": len(models), "charts": len(charts)},
    }


# ----------------------------------------------------------------------
# 详情：单模型 / 单图表
# ----------------------------------------------------------------------

def _resolve_model_file(model_id: str) -> Path | None:
    """把 <id> 映射到 models/ 下 md 文件。

    支持两种 id 形态：
      - 完整文件名：a1-three-statement / a1-three-statement.md
      - 编号前缀：a1（经扫描结果匹配 code 小写）
    """
    raw = (model_id or "").strip().lstrip("/").lower()
    if not raw:
        return None
    if raw.endswith(".md"):
        raw = raw[:-3]
    # 直接命中文件
    direct = MODELS_DIR / f"{raw}.md"
    if direct.exists():
        return direct
    # 编号前缀（如 a1 → a1-three-statement.md）
    for meta in scan_models():
        if meta["code"].lower() == raw:
            return MODELS_DIR / f"{meta['id']}.md"
    return None


def _resolve_chart_file(chart_id: str) -> Path | None:
    raw = (chart_id or "").strip().lstrip("/").lower()
    if not raw:
        return None
    if raw.endswith(".md"):
        raw = raw[:-3]
    p = CHARTS_DIR / f"{raw}.md"
    return p if p.exists() else None


@lru_cache(maxsize=64)
def get_model_detail(model_id: str) -> dict | None:
    """解析单模型详情（结构化字段 + 完整分节 + raw）。"""
    path = _resolve_model_file(model_id)
    if path is None:
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        logger.warning("读取模型详情失败 %s: %s", path, e)
        return None
    stem = path.stem
    meta = _parse_model_file(stem, text) or {}
    sections = _split_sections(text)
    sec = lambda *names: _section_content(sections, *names)  # noqa: E731
    return {
        **meta,
        # 结构化字段（常见小节映射，缺失则空）
        "purpose": sec("目的", "用途"),
        "formulas": _extract_formulas(sec("关键公式", "公式", "核心公式")),
        "variables": _parse_model_variables(sec("变量含义", "变量", "变量表")),
        "scenarios": _extract_list_items(sec("适用场景", "应用场景")),
        "notes": _extract_list_items(sec("注意事项", "注意")),
        "sections": [{"heading": h, "content": c} for h, c in sections],
        "raw": text,
    }


def _parse_model_variables(raw: str) -> list[dict]:
    """解析变量含义表 → 每变量 {变量, 含义, 单位, 方向, 类型}。

    - 方向：references 表里带「方向」列则用之；否则 `_classify_model_var` 兜底
      （input=需映射 / statistic=统计量 / output=模型输出）
    - 类型：references 表里带「类型」列则用之；否则按单位/含义启发式
      （金额→数值、因子/类/编号→分类、期/年/月→期间、其余→数值）
    """
    rows = _parse_table(raw)
    out: list[dict] = []
    for r in rows:
        var = str(r.get("变量") or r.get("变量名") or "").strip()
        if not var:
            continue
        meaning = str(r.get("含义") or r.get("meaning") or "")
        unit = str(r.get("单位") or r.get("unit") or "")
        direction = str(r.get("方向") or "").strip().lower()
        if not direction:
            direction = _classify_model_var(var, meaning)
        else:
            direction = direction if direction in ("input", "statistic", "output") else "input"
        vtype = str(r.get("类型") or "").strip().lower()
        if not vtype:
            vtype = _infer_var_type(var, meaning, unit)
        out.append({
            "var_name": var,
            "var_meaning": meaning,
            "var_unit": unit,
            "direction": direction,     # input | statistic | output
            "var_type": vtype,          # numeric | category | period
        })
    return out


def _infer_var_type(var_name: str, meaning: str, unit: str) -> str:
    """启发式推断变量类型：numeric / category / period（无 LLM）。"""
    blob = f"{var_name} {meaning} {unit}"
    if re.search(r"(日期|时间|期间|月份|年月|年度|^t$|第\s*[t]?\s*期)", blob):
        return "period"
    if re.search(r"(因子|分类|类别|类$|类型|编号|名称|方式|渠道|状态|销售人员|部门|地区)", blob):
        return "category"
    return "numeric"


@lru_cache(maxsize=64)
def get_chart_detail(chart_id: str) -> dict | None:
    """解析单图表模板详情（结构化字段 + 完整分节 + raw）。"""
    path = _resolve_chart_file(chart_id)
    if path is None:
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        logger.warning("读取图表详情失败 %s: %s", path, e)
        return None
    stem = path.stem
    meta = _parse_chart_file(stem, text) or {}
    sections = _split_sections(text)
    sec = lambda *names: _section_content(sections, *names)  # noqa: E731
    variants: list[dict] = []
    for row in _parse_table(sec("变体清单")):
        cells = list(row.values())
        if not cells:
            continue
        # 第一列可能含多个变体名（如 `line` / `line-smooth`）→ 拆出主变体 + 别名
        toks = [t.strip().strip("`") for t in re.split(r"[、,，/\s]+", cells[0]) if t.strip().strip("`")]
        variants.append({
            "variant": toks[0] if toks else cells[0].strip().strip("`"),
            "aliases": toks[1:] if len(toks) > 1 else [],
            "chart": cells[1].strip() if len(cells) > 1 else "",
            "usage": cells[2].strip() if len(cells) > 2 else "",
        })
    return {
        **meta,
        "purpose": sec("用途"),
        "scenarios": _extract_list_items(sec("典型场景", "场景")),
        "data_structure": (_extract_code_blocks(sec("数据结构")) or [""])[0],
        "selection": _extract_list_items(sec("选型建议", "选型")),
        "variants": variants,
        "notes": _extract_list_items(sec("注意事项", "注意")),
        "sections": [{"heading": h, "content": c} for h, c in sections],
        "raw": text,
    }
