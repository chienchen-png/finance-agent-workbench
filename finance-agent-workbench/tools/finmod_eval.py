"""tools/finmod_eval.py — 应用二公式求值器 `_finmod_eval`（P3 派生变量，P5 数据分析器共享）。

复用 `financial_analysis_tools._eval_formula` 的 AST 白名单思路（ast.parse(mode="eval") +
Name/BinOp/UnaryOp/四则/幂/Constant 白名单），扩展三点（需求文档 §四 步骤 6 ①）：
  ① 中文列名 → DataFrame 列（命名空间直接传 pandas Series，无非法标识符限制）
  ② 向量化求值（pandas Series 运算符重载逐行计算）
  ③ 白名单函数表（SUM/AVG/MAX/MIN/COUNT 聚合 → 标量；ROUND/ABS/IF 逐行）

语法：
- 命名公式：`利润 = 收入-成本`（按序执行，前序结果可被后序引用）
- 列引用：直接写列名（命名空间 = DataFrame 列 + 已定义派生名 + 变量映射别名）
- 四则/括号/幂：逐行（向量化）计算
- 白名单函数：`SUM(收入)` 整体聚合；`ROUND(利润, 2)`/`IF(收入>成本, 1, 0)` 逐行

禁止：import、函数定义、文件访问、网络、任意 eval——AST 白名单编译期拦截。
"""

from __future__ import annotations

import ast
from typing import Any

import numpy as np
import pandas as pd

# ----------------------------------------------------------------------
# 白名单定义
# ----------------------------------------------------------------------

# AST 白名单节点（复用 _eval_formula 思路）
_ALLOWED_NODES = (
    ast.Expression, ast.BinOp, ast.UnaryOp,
    ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow, ast.Mod,
    ast.USub, ast.UAdd,
    ast.Constant, ast.Load,
    ast.Name, ast.Call, ast.keyword, ast.Compare, ast.Eq, ast.NotEq,
    ast.Lt, ast.LtE, ast.Gt, ast.GtE, ast.BoolOp, ast.And, ast.Or,
    ast.IfExp, ast.Tuple, ast.List,
)

# 白名单函数：聚合（返回标量）+ 逐行（返回 Series）
# v2.0 V1 扩展：MEAN/STD/MEDIAN/VAR/COUNTIF 统计量 + GROUPBY/LAG/PCT_CHANGE 面板/时序
def _num(s: Any) -> pd.Series:
    return pd.to_numeric(s, errors="coerce")


AGG_FUNCTIONS = {
    "SUM": lambda s: float(_num(s).sum()),
    "AVG": lambda s: float(_num(s).mean()),
    "MEAN": lambda s: float(_num(s).mean()),       # AVG 别名（统计量语义）
    "MAX": lambda s: float(_num(s).max()),
    "MIN": lambda s: float(_num(s).min()),
    "COUNT": lambda s: int(_num(s).count()),        # 样本量 n（非空计数）
    "STD": lambda s: float(_num(s).std()),          # 标准差
    "VAR": lambda s: float(_num(s).var()),          # 方差
    "MEDIAN": lambda s: float(_num(s).median()),    # 中位数
    "COUNTIF": lambda s, cond: int((s == cond).sum()),  # 条件计数（如 COUNTIF(状态,"已回款")）
}
ROW_FUNCTIONS = {
    "ROUND": lambda s, nd=0: s.round(int(nd)),
    "ABS": lambda s: np.abs(s),
    "IF": lambda cond, a, b: np.where(cond, a, b),
    "LAG": lambda s, n=1: s.shift(int(n)),          # 前 n 期值（同比/环比）
    "PCT_CHANGE": lambda s, n=1: _num(s).pct_change(int(n)),  # 环比/同比变化率
}


class FormulaError(ValueError):
    """公式错误（分类：syntax / unknown_column / undefined_ref / value）。"""

    def __init__(self, kind: str, message: str) -> None:
        super().__init__(message)
        self.kind = kind  # syntax | unknown_column | undefined_ref | value


# ----------------------------------------------------------------------
# AST 白名单校验
# ----------------------------------------------------------------------

def _collect_names_and_calls(tree: ast.AST) -> tuple[set[str], set[str]]:
    """收集表达式中的 Name 标识符与函数调用名（白名单校验用）。"""
    names: set[str] = set()
    calls: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Call):
            f = node.func
            if isinstance(f, ast.Name):
                calls.add(f.id)
    return names, calls


def _check_whitelist(expr: str, available: set[str]) -> tuple[set[str], set[str]]:
    """AST 白名单校验；返回 (用到的列名, 用到的函数)。

    抛 FormulaError：
      - syntax：语法错误（ast.parse 失败）或不支持的语法节点
      - unknown_column：Name 不在可用列/别名中，且不是白名单函数
      - undefined_ref：引用未定义（由调用方把已定义名并入 available 后检测）
    """
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as e:
        raise FormulaError(
            "syntax",
            f"公式语法错误：{e.msg or '表达式无法解析'}（第 {e.lineno or 1} 行，位置 {e.offset or 1}）",
        ) from e
    for node in ast.walk(tree):
        if not isinstance(node, _ALLOWED_NODES):
            raise FormulaError(
                "syntax",
                f"不支持的语法节点：{type(node).__name__}（仅允许四则运算、比较、聚合函数）",
            )
    names, calls = _collect_names_and_calls(tree)
    for c in calls:
        if c not in AGG_FUNCTIONS and c not in ROW_FUNCTIONS:
            raise FormulaError(
                "syntax",
                f"未授权的函数「{c}」——可用函数：{'/'.join(sorted(set(AGG_FUNCTIONS) | set(ROW_FUNCTIONS)))}",
            )
    for n in names:
        if n in calls:  # 函数名本身不算列引用
            continue
        if n not in available and n not in AGG_FUNCTIONS and n not in ROW_FUNCTIONS:
            raise FormulaError("unknown_column", f"未找到列「{n}」")
    return names, calls


# ----------------------------------------------------------------------
# 求值
# ----------------------------------------------------------------------

def _eval_expr(expr: str, namespace: dict[str, Any]) -> Any:
    """AST 白名单求值（namespace 值为 Series/标量/函数）。"""
    tree = ast.parse(expr, mode="eval")
    with np.errstate(divide="ignore", invalid="ignore"):
        code = compile(tree, "<safe>", "eval")
        val = eval(code, {"__builtins__": {}}, dict(namespace))  # noqa: S307 —— AST 已白名单校验
    return val


def _finmod_eval(expr: str, namespace: dict[str, Any],
                 available: set[str] | None = None) -> Any:
    """求单个表达式（无 `名称=` 前缀）。

    Args:
        expr: 表达式（如 `收入-成本` / `SUM(收入)` / `ROUND(利润, 2)`）
        namespace: {名称: Series|float|函数}——列、已定义派生名、变量映射别名、白名单函数
        available: 可引用的名称集合（默认 = namespace keys）

    Returns:
        Series（逐行）或 float（聚合）。

    Raises:
        FormulaError: syntax / unknown_column / undefined_ref
    """
    av = available if available is not None else set(namespace)
    _check_whitelist(expr, av)
    # 注入白名单函数
    ns = dict(namespace)
    ns.update(AGG_FUNCTIONS)
    ns.update(ROW_FUNCTIONS)
    return _eval_expr(expr, ns)


def parse_named_formula(line: str) -> tuple[str, str]:
    """解析命名公式 `名称 = 表达式` → (name, expr)。

    按第一个 `=` 分割（名称不含 =）；无 `=` 时视为纯表达式（name 为空）。
    """
    text = (line or "").strip()
    if not text:
        raise FormulaError("syntax", "公式为空")
    if "=" in text:
        name, _, expr = text.partition("=")
        name = name.strip()
        expr = expr.strip()
        if not name:
            raise FormulaError("syntax", "命名公式缺少名称（格式：利润 = 收入-成本）")
        if not expr:
            raise FormulaError("syntax", f"「{name}」缺少表达式")
        return name, expr
    return "", text


def eval_named_formulas(
    formulas: list[str],
    df: pd.DataFrame,
    aliases: dict[str, str] | None = None,
    limit: int | None = None,
) -> tuple[dict[str, Any], list[dict]]:
    """按序执行命名公式列表（前序结果可被后序引用）。

    Args:
        formulas: ["利润=收入-成本", "毛利率=利润/收入"] 或纯表达式
        df: 源 DataFrame（列 → Series）
        aliases: 变量映射别名 {模型变量名: 实际列名}（如 {净利润: 净利润(万元)}）
        limit: 返回 sample 行数上限（默认全部）

    Returns:
        (results, errors)
        results: {名称: {"type": "series"|"scalar", "sample": [...], "rows": int, "dtype": str}}
        errors: [{line, name, kind, message}]——错误公式（不阻塞后续）
    """
    namespace: dict[str, Any] = {}
    for col in df.columns:
        namespace[str(col)] = df[col]
    if aliases:
        for var, col in aliases.items():
            if var and col and col in df.columns:
                namespace.setdefault(str(var), df[col])

    results: dict[str, Any] = {}
    errors: list[dict] = []
    available: set[str] = set(namespace)

    for idx, raw in enumerate(formulas):
        try:
            name, expr = parse_named_formula(raw)
        except FormulaError as e:
            errors.append({"line": idx + 1, "name": "", "kind": e.kind, "message": str(e)})
            continue
        try:
            val = _finmod_eval(expr, namespace, available)
        except FormulaError as e:
            errors.append({"line": idx + 1, "name": name, "kind": e.kind, "message": str(e)})
            continue
        except Exception as e:  # noqa: BLE001 —— 运行期错误（如除零传播异常）
            errors.append({"line": idx + 1, "name": name, "kind": "value",
                           "message": f"求值失败：{e}"})
            continue

        # numpy ndarray（如 IF/np.where 结果）→ 统一为 Series（index 对齐 df）
        if isinstance(val, np.ndarray):
            val = pd.Series(val, index=df.index)

        # 聚合（标量） vs 逐行（Series）
        if isinstance(val, pd.Series):
            key = name or f"expr_{idx + 1}"
            series = val
            sample = series.head(limit).tolist() if limit else series.tolist()
            results[key] = {
                "type": "series",
                "sample": _jsonable(sample),
                "rows": int(series.shape[0]),
                "dtype": str(series.dtype),
            }
            namespace[key] = series
            available.add(key)
        else:
            key = name or f"expr_{idx + 1}"
            scalar = val
            results[key] = {
                "type": "scalar",
                "sample": _jsonable(scalar),
                "rows": 1,
                "dtype": type(scalar).__name__,
            }
            if name:
                # 标量结果也可被后序引用（如 总额=SUM(收入)；占比=收入/总额）
                namespace[name] = scalar
                available.add(name)
    return results, errors


def materialize_derived(
    df: pd.DataFrame,
    formulas: list[str],
    aliases: dict[str, str] | None = None,
) -> tuple[pd.DataFrame, dict[str, Any], list[dict]]:
    """物化派生/统计量列到 DataFrame（V1 统计量广播：run 前调用）。

    与 `eval_named_formulas` 的差别：
      - 命名**聚合公式**（如 `x̄=MEAN(回款总额)`、`n=COUNT(回款总额)`）结果
        自动**广播为整列**（np.full(len(df), value)）——统计量变量语义：
        每行都是同一个值，供模型 compute 取用。
      - 命名 Series 公式（如 `毛利率=利润/收入`）正常整列物化。
      - 纯表达式（无名称）不物化（无法列名引用）。

    Returns:
        (df, results, errors)
        df: 追加派生列的 DataFrame（副本，不污染入参）
        results: {名称: {type, sample, rows, dtype, broadcast}}——broadcast=True 表示统计量广播列
        errors: [{line, name, kind, message}]
    """
    out_df = df.copy()
    namespace: dict[str, Any] = {}
    for col in df.columns:
        namespace[str(col)] = df[col]
    if aliases:
        for var, col in aliases.items():
            if var and col and col in df.columns:
                namespace.setdefault(str(var), df[col])

    results: dict[str, Any] = {}
    errors: list[dict] = []
    available: set[str] = set(namespace)
    nrows = int(df.shape[0])

    for idx, raw in enumerate(formulas):
        try:
            name, expr = parse_named_formula(raw)
        except FormulaError as e:
            errors.append({"line": idx + 1, "name": "", "kind": e.kind, "message": str(e)})
            continue
        try:
            val = _finmod_eval(expr, namespace, available)
        except FormulaError as e:
            errors.append({"line": idx + 1, "name": name, "kind": e.kind, "message": str(e)})
            continue
        except Exception as e:  # noqa: BLE001
            errors.append({"line": idx + 1, "name": name, "kind": "value",
                           "message": f"求值失败：{e}"})
            continue
        if not name:
            continue  # 纯表达式不物化（无可列名）
        if isinstance(val, np.ndarray):
            val = pd.Series(val, index=df.index)

        if isinstance(val, pd.Series):
            series = val
            out_df[name] = series.values
            results[name] = {
                "type": "series", "sample": _jsonable(series.head(5).tolist()),
                "rows": int(series.shape[0]), "dtype": str(series.dtype), "broadcast": False,
            }
            namespace[name] = series
            available.add(name)
        else:
            # 聚合标量 → 广播整列（统计量变量语义：全列同值）
            scalar = val
            out_df[name] = np.full(nrows, scalar)
            results[name] = {
                "type": "scalar_broadcast", "sample": _jsonable(scalar),
                "rows": nrows, "dtype": type(scalar).__name__, "broadcast": True,
            }
            # 广播列可被后续公式整列引用（均值→占比/差值）
            namespace[name] = pd.Series(np.full(nrows, scalar), index=df.index)
            available.add(name)
    return out_df, results, errors


def _jsonable(v: Any) -> Any:
    """pandas/numpy 标量转原生类型（JSON 可序列化；NaN/inf → None）。"""
    if isinstance(v, (pd.Series, pd.Index, list, tuple)):
        return [_jsonable(x) for x in v.tolist()] if not isinstance(v, list) \
            else [_jsonable(x) for x in v]
    if isinstance(v, (np.ndarray,)):
        return [_jsonable(x) for x in v.tolist()]
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating, np.float64, float)):
        f = float(v)
        return f if np.isfinite(f) else None
    if isinstance(v, (np.bool_,)):
        return bool(v)
    return v


# ----------------------------------------------------------------------
# 数据库 → DataFrame（复用 load_data 自动清洗语义）
# ----------------------------------------------------------------------

def load_dataframe(store: Any, project_id: str, file_name: str,
                   sheet_name: str = "") -> pd.DataFrame:
    """从项目数据库加载文件某 sheet 为 DataFrame（自动清洗）。

    清洗规则（与 smol_tools load_data 一致）：占位符（empty/None/null/''）→ NaN、
    数值列自动 to_numeric。只读主库，不写库不建临时快照（P3 预览求值用；
    P5 run 走 TmpRun 快照）。
    """
    file_rec = store.find_file_by_name(project_id, file_name)
    if not file_rec:
        raise ValueError(f"未找到数据文件「{file_name}」")
    sheets = store.list_sheets(file_rec["id"]) or []
    if not sheets:
        raise ValueError(f"文件「{file_name}」没有工作表")
    if sheet_name:
        sheet = next((s for s in sheets if s.get("sheet_name") == sheet_name), None)
        if sheet is None:
            raise ValueError(f"未找到工作表「{sheet_name}」")
    else:
        # 默认第一个非「说明/目录」sheet
        sheet = next((s for s in sheets if not any(k in (s.get("sheet_name") or "")
                                                   for k in ("说明", "目录", "封面"))), sheets[0])
    table_name = sheet.get("table_name") or ""
    headers = sheet.get("headers") or []
    if not table_name:
        raise ValueError(f"工作表「{sheet.get('sheet_name')}」无数据表")
    cols = [h.get("name") or "" for h in headers]
    cols = [c for c in cols if c]
    if not cols:
        raise ValueError(f"工作表「{sheet.get('sheet_name')}」无有效列")
    db = store.db
    sel = ", ".join('"' + c.replace('"', '""') + '"' for c in cols)
    df = pd.read_sql_query(f'SELECT {sel} FROM "{table_name}"', db)
    # 自动清洗：占位符 → NaN + 数值列 to_numeric
    for c in df.columns:
        if str(df[c].dtype) in ("object", "str", "string"):
            df[c] = df[c].replace(["empty", "None", "null", ""], None)
            conv = pd.to_numeric(df[c], errors="coerce")
            if conv.notna().sum() > 0:
                df[c] = conv
    return df
