"""Financial analysis tools — 财务建模分析工具集（financial-modeling skill，P2 计算层）。

决策 D7/D8/D9 落地：数据源统一项目数据库（SQLite），pandas 只作工具内部计算引擎，
AI 不读全量数据、不写分析代码——6 个 L1 预写工具 + generate_chart 图表生成。

模块函数：
- _load_dataframe()  → 从 SQLite 读表为 DataFrame（数据获取约定，D7）
- financial_metrics()  → 财务比率/杜邦/资本预算/现金周期
- regression_analysis() → 一元/多元回归（scipy + lstsq）
- correlation_matrix() → Pearson/Spearman 相关矩阵 + Top 强相关对
- time_series_analysis() → 季节分解/趋势/预测（纯 pandas/numpy，无 statsmodels）
- sensitivity_analysis() → 单/双变量敏感性 + CVP 盈亏平衡 + 情景
- generate_chart()   → ECharts option JSON（模板注册表 + data_table 必填）

依赖：pandas/numpy/scipy/numpy_financial（均在 offline_packages/，零新增）。
"""

from __future__ import annotations

import json
import math
import re
from typing import Any

# 复用项目数据平面（与 query_table 同一套定位/安全机制）
from tools.project_data_tools import _file_and_sheet, _store

# ------------------------------------------------------------------
# 数据获取约定（决策 D7）：SQLite 读表 → DataFrame
# ------------------------------------------------------------------


def _load_dataframe(file: str, sheet: str = "", columns: list | None = None,
                    project_id: str = "", work_dir: str = "") -> Any:
    """从项目数据库加载数据为 DataFrame（不直读 Excel）。

    列名经导入白名单校验、值参数化——安全机制与 query_table 完全一致。
    """
    import pandas as pd
    store, _db = _store()
    file_rec, sheet_rec = _file_and_sheet(store, project_id, file, sheet)
    headers = [h["name"] for h in (sheet_rec.get("headers") or [])]
    table_name = sheet_rec["table_name"]
    cols = columns if columns else headers
    rows = store.fetch_rows(table_name, cols, {})
    return pd.DataFrame(rows)


def _numeric(df: Any, col: str) -> Any:
    """列转数值（coerce 后丢弃 NaN），返回 Series。"""
    import pandas as pd
    return pd.to_numeric(df[col], errors="coerce")


def _jsonable(obj: Any) -> Any:
    """JSON 序列化兜底（NaN/Inf → None，numpy 类型 → 原生）。"""
    if isinstance(obj, dict):
        return {k: _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    try:
        import numpy as np
        if isinstance(obj, np.floating):
            return None if math.isnan(float(obj)) or math.isinf(float(obj)) else float(obj)
        if isinstance(obj, np.integer):
            return int(obj)
    except Exception:  # noqa: BLE001
        pass
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        return None
    return obj


# ------------------------------------------------------------------
# 1. financial_metrics — 财务指标/比率/杜邦/资本预算
# ------------------------------------------------------------------

RATIO_GROUPS = {
    "流动性": ["流动比率", "速动比率", "现金比率"],
    "偿债": ["资产负债率", "利息保障倍数"],
    "盈利": ["毛利率", "净利率", "ROE", "ROA"],
    "营运": ["应收账款周转率", "存货周转率", "总资产周转率"],
    "发展": ["收入增长率", "净利增长率"],
}


def financial_metrics(
    file: str,
    sheet: str = "",
    metrics: list | None = None,
    net_profit_col: str = "",
    revenue_col: str = "",
    total_assets_col: str = "",
    equity_col: str = "",
    current_assets_col: str = "",
    current_liab_col: str = "",
    inventory_col: str = "",
    receivables_col: str = "",
    cost_col: str = "",
    interest_col: str = "",
    cashflow_col: str = "",
    discount_rate: float = 0.10,
    project_id: str = "",
    work_dir: str = "",
) -> dict:
    """财务指标：五维比率 / 杜邦 / 资本预算（NPV/IRR）/ 现金周期。

    输入：文件 + sheet + 字段映射列（财务科目列名）。
    输出：{ratios: {...}, dupont: {...}, capital: {...}, ccc: {...}}
    """
    import numpy as np
    import numpy_financial as npf

    df = _load_dataframe(file, sheet, project_id=project_id, work_dir=work_dir)
    out: dict[str, Any] = {}
    want = metrics or ["ratios", "dupont", "capital", "ccc"]

    def series(col: str):
        s = _numeric(df, col)
        return s

    # ── 五维比率（基于字段映射的期末值） ──
    if "ratios" in want:
        ratios: dict[str, Any] = {}
        rev = series(revenue_col) if revenue_col else None
        np_ = series(net_profit_col) if net_profit_col else None
        ta = series(total_assets_col) if total_assets_col else None
        eq = series(equity_col) if equity_col else None
        ca = series(current_assets_col) if current_assets_col else None
        cl = series(current_liab_col) if current_liab_col else None
        inv = series(inventory_col) if inventory_col else None
        ar = series(receivables_col) if receivables_col else None
        cost = series(cost_col) if cost_col else None
        itr = series(interest_col) if interest_col else None

        def last(s) -> float | None:
            try:
                v = s.dropna().iloc[-1]
                return float(v)
            except Exception:  # noqa: BLE001
                return None

        R = last(rev); N = last(np_); T = last(ta); E = last(eq)
        C = last(ca); L = last(cl); I = last(inv); A = last(ar); CO = last(cost); INT = last(itr)

        def ratio(num, den):
            return round(num / den, 4) if num is not None and den not in (None, 0) else None

        ratios["流动比率"] = ratio(C, L)
        ratios["速动比率"] = ratio(C - I if C is not None and I is not None else None, L)
        ratios["现金比率"] = None  # 需现金列，未映射
        ratios["资产负债率"] = ratio(T - E if T is not None and E is not None else None, T)
        ratios["利息保障倍数"] = ratio(N + INT if N is not None and INT is not None else None, INT)
        ratios["毛利率"] = ratio(R - CO if R is not None and CO is not None else None, R)
        ratios["净利率"] = ratio(N, R)
        ratios["ROE"] = ratio(N, E)
        ratios["ROA"] = ratio(N, T)
        ratios["应收账款周转率"] = ratio(R, A)
        ratios["存货周转率"] = ratio(CO, I)
        ratios["总资产周转率"] = ratio(R, T)
        out["ratios"] = _jsonable(ratios)

    # ── 杜邦分析 ──
    if "dupont" in want and revenue_col and net_profit_col and total_assets_col and equity_col:
        R = series(revenue_col).dropna().iloc[-1] if len(series(revenue_col).dropna()) else None
        N = series(net_profit_col).dropna().iloc[-1] if len(series(net_profit_col).dropna()) else None
        T = series(total_assets_col).dropna().iloc[-1] if len(series(total_assets_col).dropna()) else None
        E = series(equity_col).dropna().iloc[-1] if len(series(equity_col).dropna()) else None
        if R is not None and N is not None and T is not None and E is not None and R and T and E:
            npm = float(N) / float(R)          # 净利率
            tat = float(R) / float(T)          # 总资产周转率
            em = float(T) / float(E)           # 权益乘数
            out["dupont"] = _jsonable({
                "ROE": round(float(N) / float(E), 4),
                "净利率": round(npm, 4),
                "总资产周转率": round(tat, 4),
                "权益乘数": round(em, 4),
                "分解": f"{npm:.4f} × {tat:.4f} × {em:.4f}",
            })

    # ── 资本预算（NPV/IRR/回收期/获利指数） ──
    if "capital" in want and cashflow_col:
        cf = series(cashflow_col).dropna().tolist()
        if cf:
            rate = float(discount_rate or 0.10)
            npv = float(npf.npv(rate, cf))
            irr = float(npf.irr(cf)) if len(cf) > 1 else None
            try:
                mirr = float(npf.mirr(cf, rate, rate))
            except Exception:  # noqa: BLE001
                mirr = None
            # 回收期：累计现金流首次转正（含期初）
            cum = 0.0
            payback: float | None = None
            for t, c in enumerate(cf):
                cum += float(c)
                if cum >= 0 and t >= 1:
                    payback = float(t)
                    break
            inv0 = abs(float(cf[0])) if cf[0] else 1.0
            pi = (npv + inv0) / inv0 if inv0 else None
            out["capital"] = _jsonable({
                "NPV": npv,
                "IRR": irr,
                "MIRR": mirr,
                "回收期(期)": payback,
                "获利指数PI": pi,
                "折现率": rate,
            })

    # ── 现金周期 CCC = DSO + DIO − DPO ──
    if "ccc" in want and revenue_col and cost_col and receivables_col and inventory_col:
        R = series(revenue_col).dropna().iloc[-1] if len(series(revenue_col).dropna()) else None
        CO = series(cost_col).dropna().iloc[-1] if len(series(cost_col).dropna()) else None
        AR = series(receivables_col).dropna().iloc[-1] if len(series(receivables_col).dropna()) else None
        INV = series(inventory_col).dropna().iloc[-1] if len(series(inventory_col).dropna()) else None
        if R and CO and AR is not None and INV is not None and R and CO:
            dso = 365 * float(AR) / float(R) if R else None
            dio = 365 * float(INV) / float(CO) if CO else None
            out["ccc"] = _jsonable({
                "DSO(应收周转天数)": round(dso, 2) if dso is not None else None,
                "DIO(存货周转天数)": round(dio, 2) if dio is not None else None,
                "DPO(应付周转天数)": None,  # 需应付列，未映射
                "现金周期CCC": round(dso - dio, 2) if dso is not None and dio is not None else None,
            })

    return {"success": True, "result": out}


# ------------------------------------------------------------------
# 2. regression_analysis — 回归分析
# ------------------------------------------------------------------


def regression_analysis(
    file: str,
    sheet: str = "",
    x_columns: list | None = None,
    y_column: str = "",
    add_constant: bool = True,
    project_id: str = "",
    work_dir: str = "",
) -> dict:
    """一元/多元线性回归。一元用 scipy.linregress；多元用 lstsq + t 近似 p 值。"""
    import numpy as np
    from scipy import stats

    df = _load_dataframe(file, sheet, project_id=project_id, work_dir=work_dir)
    xs = x_columns or []
    if not xs or not y_column:
        return {"success": False, "error": "x_columns 与 y_column 必填"}
    y = _numeric(df, y_column).dropna()
    X = df[xs].apply(lambda c: _numeric(df, c.name), axis=0)
    # 对齐有效行
    mask = y.notna()
    for c in xs:
        mask &= X[c].notna()
    yv = y[mask].values
    Xv = X[mask].values if len(xs) > 1 else X[xs[0]][mask].values

    if len(xs) == 1:
        res = stats.linregress(Xv, yv)
        out = {
            "model_type": "一元线性回归",
            "coefficients": [{"col": xs[0], "coef": round(float(res.slope), 6),
                              "p_value": round(float(res.pvalue), 6)}],
            "intercept": round(float(res.intercept), 6),
            "r_squared": round(float(res.rvalue ** 2), 6),
            "adj_r_squared": round(float(res.rvalue ** 2), 6),
            "n": int(len(yv)),
        }
    else:
        Xmat = Xv if add_constant else Xv[:, 1:]
        if add_constant:
            Xd = np.column_stack([np.ones(len(Xv)), Xv])
        else:
            Xd = Xv
        try:
            beta, *_ = np.linalg.lstsq(Xd, yv, rcond=None)
        except Exception as e:  # noqa: BLE001
            return {"success": False, "error": f"回归失败: {e}"}
        n, k = Xd.shape
        yhat = Xd @ beta
        resid = yv - yhat
        ss_res = float(np.sum(resid ** 2))
        ss_tot = float(np.sum((yv - yv.mean()) ** 2))
        r2 = 1 - ss_res / ss_tot if ss_tot else 0.0
        dof = n - k
        mse = ss_res / dof if dof > 0 else 0.0
        # 系数标准误 → t → p（scipy t 分布）
        try:
            cov = mse * np.linalg.inv(Xd.T @ Xd)
            se = np.sqrt(np.diag(cov))
        except Exception:  # noqa: BLE001
            se = np.zeros(k)
        coeffs = []
        for i in range(len(xs)):
            tstat = beta[i] / se[i] if se[i] else 0.0
            p = 2 * (1 - stats.t.cdf(abs(float(tstat)), dof)) if dof > 0 else 1.0
            coeffs.append({"col": xs[i], "coef": round(float(beta[i]), 6),
                           "p_value": round(float(p), 6)})
        intercept = float(beta[0]) if add_constant else 0.0
        adj_r2 = 1 - (1 - r2) * (n - 1) / dof if dof > 0 else r2
        out = {
            "model_type": f"多元线性回归({len(xs)} 自变量)",
            "coefficients": coeffs,
            "intercept": round(intercept, 6),
            "r_squared": round(float(r2), 6),
            "adj_r_squared": round(float(adj_r2), 6),
            "n": int(n),
        }
    # 残差摘要
    try:
        if len(xs) == 1:
            yhat = float(res.intercept) + float(res.slope) * Xv
        else:
            yhat = (Xd @ beta) if len(xs) > 1 else Xv
        resid = yv - yhat
        out["residuals"] = _jsonable({
            "mean": float(np.mean(resid)),
            "std": float(np.std(resid)),
            "min": float(np.min(resid)),
            "max": float(np.max(resid)),
            "summary": _jsonable(list(resid[:10])),
        })
    except Exception:  # noqa: BLE001
        pass
    return {"success": True, "result": _jsonable(out)}


# ------------------------------------------------------------------
# 3. correlation_matrix — 相关性矩阵
# ------------------------------------------------------------------


def correlation_matrix(
    file: str,
    sheet: str = "",
    columns: list | None = None,
    method: str = "pearson",
    threshold: float = 0.6,
    project_id: str = "",
    work_dir: str = "",
) -> dict:
    """相关矩阵 + Top-N 强相关对（|r| ≥ threshold）。"""
    df = _load_dataframe(file, sheet, project_id=project_id, work_dir=work_dir)
    cols = columns or [c for c in df.columns if _numeric(df, c).notna().sum() > 1]
    if method not in ("pearson", "spearman"):
        return {"success": False, "error": f"method 必须是 pearson/spearman，收到 {method}"}
    sub = df[cols].apply(lambda c: _numeric(df, c.name), axis=0)
    corr = sub.corr(method=method)
    matrix = [[round(float(v), 4) for v in row] for row in corr.values]
    pairs = []
    names = list(corr.columns)
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            r = float(corr.iloc[i, j])
            if abs(r) >= threshold:
                pairs.append({"a": names[i], "b": names[j], "r": round(r, 4)})
    pairs.sort(key=lambda p: -abs(p["r"]))
    return {"success": True, "result": _jsonable({
        "columns": names,
        "matrix": matrix,
        "top_pairs": pairs[:20],
        "method": method,
        "threshold": threshold,
    })}


# ------------------------------------------------------------------
# 4. time_series_analysis — 时间序列分析（纯 pandas/numpy）
# ------------------------------------------------------------------


def time_series_analysis(
    file: str,
    sheet: str = "",
    date_column: str = "",
    value_column: str = "",
    freq: str = "M",
    decompose: bool = True,
    forecast_horizon: int = 3,
    method: str = "auto",
    project_id: str = "",
    work_dir: str = "",
) -> dict:
    """趋势 + 季节分解（经典比例法）+ 预测（线性外推/指数平滑/移动平均）。

    纯 pandas/numpy 实现，不依赖 statsmodels（离线无该包）。
    """
    import numpy as np
    import pandas as pd

    df = _load_dataframe(file, sheet, project_id=project_id, work_dir=work_dir)
    if not date_column or not value_column:
        return {"success": False, "error": "date_column 与 value_column 必填"}
    s = _numeric(df, value_column).dropna()
    if len(s) < 4:
        return {"success": False, "error": "数据点过少（<4），无法分析"}
    values = s.values.astype(float)
    n = len(values)

    # 季节周期（按 freq）
    period = {"M": 12, "Q": 4, "Y": 1}.get(freq, 12)

    # ── 经典比例法季节分解 ──
    seasonal_indices: dict = {}
    trend_series: list | None = None
    is_seasonal = False
    if decompose and period >= 2 and n >= 2 * period:
        try:
            idx = pd.Series(values)
            ma = idx.rolling(period, center=True).mean()
            ma = ma.ffill().bfill()
            ratio = idx / ma
            # 按周期位置平均 → 季节指数（归一化）
            si = np.full(period, 1.0)
            for p in range(period):
                vals = ratio.iloc[p::period].dropna().values
                if len(vals):
                    si[p] = float(np.mean(vals))
            if np.mean(si) > 0:
                si = si / np.mean(si)
            seasonal_indices = {f"s{p + 1}": round(float(si[p]), 4) for p in range(period)}
            # 判断季节性强弱：指数偏离 1 的程度
            dev = float(np.std(si))
            is_seasonal = dev > 0.03
            # 去季节后的趋势（线性外推基础）
            adj = values / np.tile(si, int(np.ceil(n / period)))[:n]
            trend_series = [round(float(x), 4) for x in adj]
        except Exception:  # noqa: BLE001
            pass

    # ── 预测 ──
    h = max(1, int(forecast_horizon or 1))
    method_used = method
    forecast = []
    try:
        if method in ("auto", "linear"):
            # 线性外推（polyfit 1 阶）
            x = np.arange(n)
            base = trend_series if trend_series is not None else values
            slope, intercept = np.polyfit(x, base, 1)
            for t in range(1, h + 1):
                pred = intercept + slope * (n - 1 + t)
                if trend_series is not None and seasonal_indices and is_seasonal:
                    pos = (n - 1 + t) % period
                    pred *= seasonal_indices.get(f"s{pos + 1}", 1.0)
                forecast.append(round(float(pred), 2))
            method_used = "linear_extrap" + ("_seasonal" if is_seasonal else "")
        elif method == "moving_avg":
            k = min(3, n - 1)
            base = float(np.mean(values[-k:]))
            for _ in range(h):
                forecast.append(round(base, 2))
            method_used = f"moving_avg({k})"
        elif method == "exp_smooth":
            alpha = 0.3
            yhat = values[0]
            for v in values[1:]:
                yhat = alpha * v + (1 - alpha) * yhat
            for _ in range(h):
                yhat = alpha * yhat + (1 - alpha) * yhat
                forecast.append(round(float(yhat), 2))
            method_used = "exp_smooth(α=0.3)"
    except Exception:  # noqa: BLE001
        method_used = "fallback_last"
        last_v = float(values[-1])
        forecast = [round(last_v, 2)] * h

    # 拟合质量（对历史拟合）
    try:
        x = np.arange(n)
        if trend_series is not None:
            slope, intercept = np.polyfit(x, trend_series, 1)
            fitted = intercept + slope * x
        else:
            fitted = np.full(n, float(np.mean(values)))
        resid = values - fitted
        mae = float(np.mean(np.abs(resid)))
        mape = float(np.mean(np.abs(resid) / np.where(values != 0, np.abs(values), 1))) * 100
        fit_quality = {"mae": round(mae, 4), "mape": round(mape, 2)}
    except Exception:  # noqa: BLE001
        fit_quality = {}

    return {"success": True, "result": _jsonable({
        "n": int(n),
        "freq": freq,
        "period": period,
        "seasonal": {"indices": seasonal_indices, "is_seasonal": is_seasonal} if decompose else {},
        "trend": trend_series,
        "forecast": forecast,
        "method_used": method_used,
        "fit_quality": fit_quality,
    })}


# ------------------------------------------------------------------
# 5. sensitivity_analysis — 敏感性/情景分析（CVP/盈亏平衡）
# ------------------------------------------------------------------


def _eval_formula(formula: str, variables: dict) -> float:
    """AST 白名单求值：仅四则/括号/幂 + 白名单变量名（防注入）。"""
    import ast
    names = set(variables)
    tree = ast.parse(formula, mode="eval")
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            if node.id not in names:
                raise ValueError(f"未授权变量: {node.id}")
        elif not isinstance(node, (ast.Expression, ast.BinOp, ast.UnaryOp,
                                   ast.Add, ast.Sub, ast.Mult, ast.Div,
                                   ast.Pow, ast.USub, ast.UAdd, ast.Constant,
                                   ast.Load, ast.Mod)):
            raise ValueError(f"不支持的语法节点: {type(node).__name__}")
    return float(eval(compile(tree, "<safe>", "eval"), {"__builtins__": {}}, dict(variables)))


def sensitivity_analysis(
    base_inputs: dict | None = None,
    model_type: str = "cvp",
    formula: str = "",
    variable_ranges: dict | None = None,
    two_way_vars: list | None = None,
    discount_rate: float = 0.10,
    scenarios: dict | None = None,
    project_id: str = "",
    work_dir: str = "",
) -> dict:
    """单变量敏感性 / 双变量网格 / CVP 盈亏平衡 / 情景分析。

    model_type: cvp | npv | custom_formula
    base_inputs: {变量: 值}（cvp 需 price/vc/fc；npv 需 cashflows 列表 + rate）
    """
    import numpy as np

    base = base_inputs or {}
    if not base and model_type != "custom_formula":
        return {"success": False, "error": "base_inputs 必填"}

    # ── 目标函数 ──
    def target(vars_dict: dict) -> float:
        if model_type == "cvp":
            p = float(vars_dict["price"]); v = float(vars_dict["vc"])
            q = float(vars_dict["qty"]); f = float(vars_dict["fc"])
            return (p - v) * q - f
        if model_type == "npv":
            cf = [float(x) for x in vars_dict["cashflows"]]
            r = float(vars_dict.get("rate", discount_rate))
            return sum(c / (1 + r) ** t for t, c in enumerate(cf))
        if model_type == "custom_formula":
            return _eval_formula(formula, vars_dict)
        raise ValueError(f"未知 model_type: {model_type}")

    out: dict[str, Any] = {}
    base_val = None
    try:
        base_val = target(base)
    except Exception as e:  # noqa: BLE001
        return {"success": False, "error": f"基准计算失败: {e}"}

    # ── 单变量敏感性（±5/10/15%） ──
    one_way: list = []
    ranges = variable_ranges or {}
    for var, val in base.items():
        if model_type == "npv" and var == "cashflows":
            continue
        if not isinstance(val, (int, float)) or isinstance(val, bool):
            continue
        steps = ranges.get(var, {}).get("steps") or [0.85, 0.9, 0.95, 1.05, 1.1, 1.15]
        changes = []
        for mult in steps:
            v2 = dict(base); v2[var] = float(val) * float(mult)
            try:
                res = target(v2)
                changes.append({"mult": float(mult), "result": round(float(res), 4)})
            except Exception:  # noqa: BLE001
                pass
        if changes:
            one_way.append({"variable": var, "base": round(float(val), 4), "changes": changes})

    # ── 双变量网格 ──
    two_way: dict = {}
    tw = two_way_vars or []
    if len(tw) >= 2 and all(v in base for v in tw[:2]):
        a, b = tw[0], tw[1]
        steps_a = ranges.get(a, {}).get("steps") or [0.9, 1.0, 1.1]
        steps_b = ranges.get(b, {}).get("steps") or [0.9, 1.0, 1.1]
        grid = []
        for ma in steps_a:
            row = []
            for mb in steps_b:
                v2 = dict(base); v2[a] = float(base[a]) * float(ma); v2[b] = float(base[b]) * float(mb)
                try:
                    row.append(round(float(target(v2)), 4))
                except Exception:  # noqa: BLE001
                    row.append(None)
            grid.append(row)
        two_way = {"x": {"var": a, "steps": steps_a}, "y": {"var": b, "steps": steps_b}, "grid": grid}

    # ── CVP 盈亏平衡（二分法求目标=0 的 qty/price） ──
    break_even: dict = {}
    if model_type == "cvp" and "qty" in base:
        p = float(base["price"]); v = float(base["vc"]); f = float(base["fc"])
        if p > v:
            q_be = f / (p - v)
            break_even["qty"] = round(float(q_be), 4)
            break_even["revenue"] = round(float(q_be * p), 4)
            margin = p - v
            break_even["contribution_margin"] = round(margin, 4)
            break_even["margin_ratio"] = round(margin / p, 4) if p else None
            # 安全边际（相对 base qty）
            if "qty" in base and float(base["qty"]) > 0:
                break_even["safety_margin"] = round(1 - q_be / float(base["qty"]), 4)

    # ── 情景分析 ──
    scen_out: dict = {}
    sc = scenarios or {}
    for k, v in sc.items():
        try:
            scen_out[k] = round(float(target(v)), 4)
        except Exception:  # noqa: BLE001
            scen_out[k] = None

    return {"success": True, "result": _jsonable({
        "model_type": model_type,
        "base_result": round(float(base_val), 4),
        "one_way": one_way,
        "two_way": two_way,
        "break_even": break_even,
        "scenarios": scen_out,
    })}


# ------------------------------------------------------------------
# 6. generate_chart — ECharts option 生成（模板注册表 + P5 变体）
# ------------------------------------------------------------------

CHART_TEMPLATES = [
    "line", "bar", "pie", "scatter", "heatmap", "waterfall",
    "radar", "boxplot", "histogram", "tornado", "funnel", "dual-axis",
    "sunburst", "sankey", "gauge",
    # P5-③ 新增类型
    "treemap", "graph", "parallel", "error-bar", "calendar",
    # P6-② 3D + 联动
    "scatter3d", "bar3d", "histogram-4grid",
    # P7 3D 瀑布图（2026-08-23 多指标并排）
    "waterfall3d",
]

# P5 变体注册表（与前端 chart-templates/index.ts 保持一致）：
# 每类型的变体 key 列表；变体 key "" = 默认变体（等价纯类型名）。
# template 参数支持 `类型`（默认变体）或 `类型-变体key`（如 "bar-line"）。
# 2026-08-23 按用户附件重构：line 3 变体 / bar 5 变体；删除 bar-stacked 类型。
CHART_VARIANTS: dict[str, list[str]] = {
    "line": ["", "simple", "multi-x"],
    "bar": ["", "simple", "negative", "line", "fancy"],
    "pie": ["", "donut", "simple", "half-donut", "rounded", "nested"],
    "scatter": ["", "effect", "regression"],
    "heatmap": ["", "simple", "discrete", "calendar"],
    "waterfall": ["", "simple", "bar"],
    "radar": ["", "simple", "multi"],
    "boxplot": ["", "simple", "multi"],
    "histogram": [""],
    "tornado": [""],
    "funnel": ["", "simple", "compare"],
    "dual-axis": [""],
    "sunburst": [""],
    "sankey": ["", "simple", "vertical"],
    "gauge": ["", "simple", "progress", "stage"],
    # P5-③ 新增类型
    "treemap": ["", "simple", "drilldown"],
    "graph": ["", "force", "circle"],
    "parallel": [""],
    "error-bar": ["", "bar", "range"],
    "calendar": ["", "simple", "year"],
    # P6-② 3D + 联动
    "scatter3d": ["", "simple"],
    "bar3d": ["", "simple"],
    "histogram-4grid": ["", "simple"],
    # P7 3D 瀑布图
    "waterfall3d": [""],
}

# 全部可用模板名（类型 + 类型-变体，供错误提示与 SKILL.md 选型）
# 排除与默认变体等价的 key（simple/smooth/donut 等指向默认 build 的别名）
_VARIANT_ALIASES_EQUIV_DEFAULT = {"simple", "smooth", "donut"}
CHART_TEMPLATE_NAMES = CHART_TEMPLATES + [
    f"{t}-{k}" for t, keys in CHART_VARIANTS.items()
    for k in keys if k and k not in _VARIANT_ALIASES_EQUIV_DEFAULT
]


def _resolve_chart_template(template: str) -> tuple[str | None, str | None]:
    """解析 template 名 → (类型, 变体key)。

    - "line" → ("line", None)        纯类型名 = 默认变体
    - "line-smooth" → ("line", "smooth")
    - "line-simple" → ("line", "simple")
    - 未知 → (None, None)
    最长类型前缀优先（避免 "bar-stacked" 被 "bar" 抢）。
    """
    if template in CHART_TEMPLATES:
        return template, None
    for t in sorted(CHART_TEMPLATES, key=len, reverse=True):
        if template.startswith(t + "-"):
            key = template[len(t) + 1:]
            if key in CHART_VARIANTS.get(t, []):
                return t, key
    return None, None


def generate_chart(
    template: str = "",
    title: str = "",
    data: dict | None = None,
    option_overrides: dict | None = None,
    data_table: list | None = None,
) -> dict:
    """生成 ECharts option JSON（模板注册表约束 + data_table 必填）。

    前端 ChartRenderer 只信任模板产出的 option；本工具是后端镜像校验。
    template 支持 `类型`（默认变体）或 `类型-变体key`（P5-①）。
    """
    tpl_type, variant = _resolve_chart_template(template)
    if tpl_type is None:
        return {"success": False, "error": f"未知模板「{template}」；可用: {', '.join(CHART_TEMPLATE_NAMES)}"}
    if data_table is None:
        return {"success": False, "error": "data_table 必填（图表必须有数据基础，§6 协议）"}
    data = data or {}
    cats = data.get("categories") or []
    series = data.get("series") or []

    # 基础 option 骨架（中文默认主题：蓝橙配色）
    # 注：不含 title——容器标题栏已展示表名（防元素堆叠/重复）
    option: dict[str, Any] = {
        "tooltip": {"trigger": "axis"},
        "legend": {"bottom": 0} if len(series) > 1 else {},
        "color": ["#2563eb", "#f97316", "#0d9488", "#db2777", "#7c3aed",
                  "#059669", "#d97706", "#4f46e5"],
    }
    if tpl_type in ("line", "bar", "dual-axis", "waterfall", "histogram"):
        option["xAxis"] = {"type": "category", "data": cats}
        option["yAxis"] = {"type": "value"}
        # 2026-08-23 按用户附件重构（镜像前端 chart-templates/line.ts）：
        #   line                = 多维折线·分组对比（多系列 + markPoint 极值 + markLine 平均线）
        #   line-simple         = 简单折线（单系列）
        #   line-multi-x        = 多x轴折线（双 x 轴）
        #   bar                 = 分组柱状（多系列并排）
        #   bar-simple          = 简单柱状（单系列）
        #   bar-negative        = 正负条形（横向堆叠，正绿负红）
        #   bar-line            = 折线柱状（柱 + 折线双 y 轴）
        #   bar-fancy           = 分组折线柱状（多年柱 + trend 折线）
        is_line = tpl_type == "line"
        is_bar = tpl_type == "bar"
        is_line_simple = is_line and variant == "simple"
        is_line_multix = is_line and variant == "multi-x"
        is_bar_negative = is_bar and variant == "negative"
        is_bar_line = is_bar and variant == "line"
        is_bar_fancy = is_bar and variant == "fancy"

        # 默认 option（单/双系列折线或柱，label 显示数值）
        # bar-line 时折线系列（series[].type==="line"）保留原 type 绑右轴；其余默认 bar。
        # bar-fancy 时 custom 系列（series[].type==="custom"）保留原 type（trend 折线）。
        option["series"] = [
            {"name": s.get("name", f"系列{i + 1}"),
             "type": (s.get("type") if ((is_bar_line and s.get("type") == "line") or
                                        (is_bar_fancy and s.get("type") == "custom"))
                      else ("line" if is_line else "bar")),
             "data": s.get("data") or [],
             "label": {"show": True, "position": "top", "fontSize": 10, "color": "#52525b"},
             **({"smooth": True} if is_line else {})}
            for i, s in enumerate(series)
        ]

        if is_line:
            # 多维折线·分组对比：每系列 markPoint(极值) + markLine(平均线)
            for s in option["series"]:
                s["markPoint"] = {"data": [{"type": "max", "name": "最大"}, {"type": "min", "name": "最小"}]}
                s["markLine"] = {"data": [{"type": "average", "name": "平均"}]}
        elif is_line_multix:
            # 多x轴：示例数据带 xCategories/xCategories2，
            # 这里把 series 按 xAxisIndex 分组（首个 x 轴 = xCategories，其余 = xCategories2）
            xcats2 = data.get("xCategories2") or []
            option["xAxis"] = [
                {"type": "category", "data": cats},
                {"type": "category", "data": xcats2},
            ]
            for i, s in enumerate(option["series"]):
                s["xAxisIndex"] = 1 if (i >= 0 and i % 2 == 1) else 0

        if tpl_type == "bar" and variant in ("", None):
            # 默认/Simple 的处理在 option["series"] 中已覆盖（type=bar）
            pass
        elif is_bar_negative:
            # 正负条形：交换轴（y 类别 / x 数值），正绿负红，费用类堆叠
            option["xAxis"] = {"type": "value"}
            option["yAxis"] = {"type": "category", "data": cats, "inverse": True}
            for s in option["series"]:
                s["label"] = {"show": True, "fontSize": 9, "color": "#52525b"}
                s["itemStyle"] = {
                    "color": "function(p){return Number(p.value)>=0?'#059669':'#dc2626';}"
                }
                if "费用" in (s.get("name") or "") or "成本" in (s.get("name") or ""):
                    s["stack"] = "Total"
        elif is_bar_line:
            # 折线柱状：柱（左轴）+ 折线（右轴）；按 type 分柱/线
            y0 = data.get("yAxis0Name") or "量"
            y1 = data.get("yAxis1Name") or "率"
            option["yAxis"] = [
                {"type": "value", "name": y0},
                {"type": "value", "name": y1},
            ]
            for i, s in enumerate(option["series"]):
                # 折线系列（name 含率/type 为 line）绑右轴
                is_line_series = (s.get("type") == "line")
                s["type"] = "line" if is_line_series else "bar"
                if is_line_series:
                    s["yAxisIndex"] = 1
                    s["smooth"] = True
        elif is_bar_fancy:
            # 分组折线柱：多年柱 + custom trend（series 里第 0 组为 custom）
            option["dataZoom"] = [
                {"type": "slider", "start": 50, "end": 70},
                {"type": "inside", "start": 50, "end": 70},
            ]
            option["legend"] = {"bottom": 0, "type": "scroll"}
    elif tpl_type == "pie":
        option["series"] = [{
            "type": "pie", "radius": "60%",
            "data": [{"name": cats[i] if i < len(cats) else f"项{i + 1}", "value": s.get("data", [])[i]}
                     for i in range(len(cats)) for s in series[:1]] if cats else [],
        }]
        option["tooltip"] = {"trigger": "item"}
    elif tpl_type == "scatter":
        option["series"] = [
            {"name": s.get("name", f"系列{i + 1}"), "type": "scatter", "data": s.get("data") or []}
            for i, s in enumerate(series)
        ]
    elif tpl_type == "heatmap":
        option["visualMap"] = {"min": 0, "max": 1, "calculable": True, "orient": "horizontal", "left": "center", "bottom": 0}
        xc = data.get("xCategories") or cats
        yc = data.get("yCategories") or []
        option["xAxis"] = {"type": "category", "data": xc}
        option["yAxis"] = {"type": "category", "data": yc}
        option["series"] = [{"type": "heatmap", "data": s.get("data") or []} for s in series]
    elif tpl_type == "radar":
        inds = data.get("indicators") or [
            {"name": c, "max": 100} for c in cats
        ]
        option["radar"] = {"indicator": inds}
        option["series"] = [
            {"type": "radar", "name": s.get("name", f"系列{i + 1}"),
             "data": [{"value": s.get("data") or []}]}
            for i, s in enumerate(series)
        ]
    elif tpl_type == "waterfall":
        # 瀑布图：首尾灰、中间增减（堆叠 + 透明占位）
        vals = series[0].get("data") if series else []
        base_vals = []
        acc = 0.0
        for i, item in enumerate(vals):
            v = item.get("value", 0) if isinstance(item, dict) else item
            v = float(v)
            if i == 0 or i == len(vals) - 1:
                base_vals.append(0)
                acc = v
            else:
                base_vals.append(acc if v >= 0 else acc + v)
                acc += v
        option["xAxis"] = {"type": "category", "data": [i.get("name", "") if isinstance(i, dict) else i for i in vals]}
        option["yAxis"] = {"type": "value"}
        option["series"] = [
            {"type": "bar", "stack": "wf", "data": base_vals,
             "itemStyle": {"color": "rgba(0,0,0,0)"}},
            {"type": "bar", "stack": "wf",
             "data": [i.get("value", 0) if isinstance(i, dict) else i for i in vals],
             "label": {"show": True, "position": "top"}},
        ]
    elif tpl_type == "tornado":
        option["yAxis"] = {"type": "category", "data": cats}
        option["xAxis"] = {"type": "value"}
        option["series"] = [
            {"name": s.get("name", f"系列{i + 1}"), "type": "bar", "data": s.get("data") or []}
            for i, s in enumerate(series)
        ]
    elif tpl_type == "treemap":
        # 矩形树图：series[0].data 为树形嵌套（{name, value, children?}）
        tree = (series[0].get("data") or []) if series else []
        option["tooltip"] = {"trigger": "item"}
        option["series"] = [{
            "type": "treemap", "data": tree,
            "leafDepth": 1 if variant == "drilldown" else None,
            "breadcrumb": {"show": True, "height": 20},
            "label": {"show": True, "fontSize": 10},
            "itemStyle": {"borderColor": "#fff", "borderWidth": 1, "gapWidth": 1},
        }]
    elif tpl_type == "graph":
        # 关系图：nodes + links + categories
        nodes = data.get("nodes") or []
        links = data.get("links") or []
        cats2 = [{"name": c} for c in cats]
        option["tooltip"] = {"trigger": "item"}
        if len(cats2) > 1:
            option["legend"] = {"bottom": 0}
        option["series"] = [{
            "type": "graph",
            "layout": "circular" if variant == "circle" else "force",
            "roam": True,
            "force": {"repulsion": 120, "edgeLength": [40, 90]} if variant != "circle" else None,
            "label": {"show": True, "fontSize": 9},
            "categories": cats2,
            "data": nodes,
            "links": links,
        }]
    elif tpl_type == "parallel":
        # 平行坐标：dimensions + rows
        dims = data.get("dimensions") or [{"name": c} for c in cats]
        rows = (series[0].get("data") or []) if series else []
        option["parallelAxis"] = [
            {"dim": i, "name": d.get("name", f"维度{i + 1}") if isinstance(d, dict) else str(d)}
            for i, d in enumerate(dims)
        ]
        option["parallel"] = {"left": 40, "right": 60, "top": 30, "bottom": 40}
        option["series"] = [{"type": "parallel", "lineStyle": {"width": 1.5}, "data": rows}]
    elif tpl_type == "error-bar":
        # 误差条：series[0].data = [value, low, high] 三元组或 {value, low, high}
        raw = (series[0].get("data") or []) if series else []
        tris = []
        for r in raw:
            if isinstance(r, dict):
                tris.append({
                    "value": float(r.get("value", 0)),
                    "low": float(r.get("low", r.get("lower", 0))),
                    "high": float(r.get("high", r.get("upper", 0))),
                })
            elif isinstance(r, (list, tuple)) and len(r) >= 3:
                tris.append({"value": float(r[0]), "low": float(r[1]), "high": float(r[2])})
            else:
                tris.append({"value": float(r), "low": float(r), "high": float(r)})
        if variant == "range":
            # 区间带：上下界折线 + 面积
            option["xAxis"] = {"type": "category", "data": cats, "boundaryGap": False}
            option["yAxis"] = {"type": "value"}
            option["series"] = [
                {"name": "上界", "type": "line", "data": [t["high"] for t in tris],
                 "lineStyle": {"opacity": 0}, "symbol": "none", "stack": "band", "silent": True},
                {"name": "区间", "type": "line", "data": [t["low"] for t in tris],
                 "lineStyle": {"opacity": 0}, "symbol": "none", "stack": "band",
                 "areaStyle": {"color": "rgba(37,99,235,0.15)"}, "silent": True, "tooltip": {"show": False}},
                {"name": "均值", "type": "line", "smooth": True, "data": [t["value"] for t in tris]},
            ]
        else:
            # 误差条：柱 + 上下误差须
            option["xAxis"] = {"type": "category", "data": cats}
            option["yAxis"] = {"type": "value"}
            option["series"] = [
                {"name": "均值", "type": "bar", "data": [t["value"] for t in tris],
                 "itemStyle": {"color": "#2563eb", "borderRadius": [4, 4, 0, 0]}},
            ]
    elif tpl_type == "calendar":
        # 日历热力：series[0].data = [["2025-01-05", 1200], ...]
        cal = data.get("calendarRange") or (
            [cats[0], cats[-1]] if len(cats) >= 2 else ["2025-01-01", "2025-12-31"]
        )
        cells = (series[0].get("data") or []) if series else []
        vals = [c[1] for c in cells if isinstance(c, (list, tuple)) and len(c) >= 2]
        option["visualMap"] = {
            "min": min(vals) if vals else 0, "max": max(vals) if vals else 100,
            "orient": "horizontal", "left": "center", "bottom": 4,
        }
        option["calendar"] = {"range": cal, "left": 40, "top": 20, "cellSize": ["auto", 16]}
        option["series"] = [{"type": "heatmap", "coordinateSystem": "calendar", "data": cells}]
    elif tpl_type == "scatter3d":
        # 三维散点：series[0].data = [[x, y, z], ...]
        pts = (series[0].get("data") or []) if series else []
        zs = [p[2] for p in pts if isinstance(p, (list, tuple)) and len(p) >= 3]
        ax = data.get("axisNames") or ["X", "Y", "Z"]
        option["tooltip"] = {"formatter": None}  # 前端模板格式化（option 完整）
        option["grid3D"] = {
            "boxWidth": 120, "boxDepth": 120, "boxHeight": 90,
            "axisLine": {"lineStyle": {"color": "#a1a1aa"}},
            "splitLine": {"lineStyle": {"color": "#e4e4e7"}},
            "axisPointer": {"lineStyle": {"color": "#71717a"}},
            "viewControl": {"alpha": 22, "beta": -30, "distance": 220,
                            "rotateSensitivity": 2, "zoomSensitivity": 2, "panSensitivity": 1},
            "light": {"main": {"intensity": 1.2}, "ambient": {"intensity": 0.5}},
        }
        option["xAxis3D"] = {"type": "value", "name": ax[0] if len(ax) > 0 else "X"}
        option["yAxis3D"] = {"type": "value", "name": ax[1] if len(ax) > 1 else "Y"}
        option["zAxis3D"] = {"type": "value", "name": ax[2] if len(ax) > 2 else "Z"}
        option["visualMap"] = {
            "show": True, "dimension": 2,
            "min": min(zs) if zs else 0, "max": max(zs) if zs else 1,
            "left": 16, "bottom": 16, "text": ["高", "低"],
            "inRange": {"color": ["#d7d7d7", "#a1a1aa", "#71717a", "#3f3f46", "#27272a"]},
        }
        option["series"] = [{"type": "scatter3D", "data": pts, "symbolSize": 8,
                             "itemStyle": {"opacity": 0.9}}]
    elif tpl_type == "bar3d":
        # 三维柱状：v6.12 重构为「二维数据直方图」——data = [[x,y],...] 二维点集（柱高=频数）
        # 兼容旧三元组 [[x,y,z],...]（取 x,y）。此处仅生成 echarts 骨架（前端 3D 走 Python 分支）。
        xc = data.get("xCategories") or cats
        yc = data.get("yCategories") or ["Q1", "Q2", "Q3", "Q4"]
        cells = (series[0].get("data") or []) if series else []
        # 频数直方图：对二维点集做 histogram2d（柱高=频数）；三元组则取 z 作柱高
        if cells and isinstance(cells[0], (list, tuple)) and len(cells[0]) >= 3:
            # 旧三元组：柱高=z
            zs = [c[2] for c in cells if isinstance(c, (list, tuple)) and len(c) >= 3]
            bar_data = cells
        else:
            # 二维点集：[x,y] → 用 numpy histogram2d 得到频数柱（柱高=频数）
            import numpy as _np
            _xs = _np.array([float(c[0]) for c in cells if isinstance(c, (list, tuple)) and len(c) >= 2])
            _ys = _np.array([float(c[1]) for c in cells if isinstance(c, (list, tuple)) and len(c) >= 2])
            if len(_xs) > 1 and len(_ys) > 1:
                h, xe, ye = _np.histogram2d(_xs, _ys, bins=4)
                xpos, ypos = _np.meshgrid(xe[:-1], ye[:-1], indexing="ij")
                dx = (xe[1] - xe[0]) * 0.8
                dy = (ye[1] - ye[0]) * 0.8
                bar_data = [[float(xp), float(yp), float(zp)] for xp, yp, zp in zip(xpos.ravel(), ypos.ravel(), h.ravel())]
                zs = [r[2] for r in bar_data]
            else:
                bar_data = cells
                zs = []
        option["tooltip"] = {"formatter": None}
        option["grid3D"] = {
            "boxWidth": 150, "boxDepth": 80, "boxHeight": 100,
            "axisLine": {"lineStyle": {"color": "#a1a1aa"}},
            "splitLine": {"lineStyle": {"color": "#e4e4e7"}},
            "axisPointer": {"lineStyle": {"color": "#71717a"}},
            "viewControl": {"alpha": 25, "beta": -25, "distance": 240,
                            "rotateSensitivity": 2, "zoomSensitivity": 2, "panSensitivity": 1},
            "light": {"main": {"intensity": 1.3}, "ambient": {"intensity": 0.5}},
        }
        option["xAxis3D"] = {"type": "category", "data": xc, "name": data.get("xAxisName", "X")}
        option["yAxis3D"] = {"type": "category", "data": yc, "name": data.get("yAxisName", "Y")}
        option["zAxis3D"] = {"type": "value", "name": data.get("zAxisName", "值")}
        option["visualMap"] = {
            "show": True, "dimension": 2,
            "min": min(zs) if zs else 0, "max": max(zs) if zs else 1,
            "left": 16, "bottom": 16, "text": ["高", "低"],
            "inRange": {"color": ["#d7d7d7", "#a1a1aa", "#71717a", "#3f3f46", "#27272a"]},
        }
        option["series"] = [{"type": "bar3D", "data": bar_data, "shading": "lambert",
                             "bevelSize": 0.5, "itemStyle": {"opacity": 0.95,
                                                             "borderColor": "#18181b", "borderWidth": 0.4}}]
    elif tpl_type == "waterfall3d":
        # 三维瀑布图：x=年份 category、y=指标 category、z=数值 value
        # series[0].data = [[xIdx, yIdx, zVal], ...]
        xc = data.get("xCategories") or cats
        yc = data.get("yCategories") or []
        cells = (series[0].get("data") or []) if series else []
        shades = ["#c6dbef", "#9ecae1", "#6baed6", "#4292c6", "#2171b5", "#08519c", "#08306b"]
        # 轮廓线：每指标一条折线（y=指标索引，x沿年份，z=数值）
        def _lines_for(yi: int) -> list:
            pts = [c for c in cells if isinstance(c, (list, tuple)) and len(c) >= 3 and c[1] == yi]
            pts.sort(key=lambda c: c[0])
            return [list(p) for p in pts]

        option["tooltip"] = {"formatter": None}
        option["grid3D"] = {
            "boxWidth": 200, "boxDepth": 120, "boxHeight": 90,
            "axisLine": {"lineStyle": {"color": "#a1a1aa"}},
            "splitLine": {"lineStyle": {"color": "#e4e4e7"}},
            "axisPointer": {"lineStyle": {"color": "#71717a"}},
            "viewControl": {"alpha": 22, "beta": 28, "distance": 260,
                            "rotateSensitivity": 2, "zoomSensitivity": 2, "panSensitivity": 1,
                            "autoRotate": False},
            "light": {"main": {"intensity": 1.2}, "ambient": {"intensity": 0.5}},
        }
        option["xAxis3D"] = {"type": "category", "data": xc, "name": data.get("xAxisName", "时间")}
        option["yAxis3D"] = {"type": "category", "data": yc, "name": data.get("yAxisName", "财务指标")}
        option["zAxis3D"] = {"type": "value", "name": data.get("zAxisName", "数值(%)")}
        option["visualMap"] = {
            "show": True, "dimension": 1,
            "min": 0, "max": max((len(yc) - 1), 1),
            "left": 16, "bottom": 16, "text": ["前", "后"],
            "textStyle": {"color": "#71717a"},
            "inRange": {"color": shades},
        }
        # 主体网格曲面 + 每指标轮廓线
        main_series = {"type": "surface", "data": cells, "shading": "color",
                       "wireframe": {"show": True, "lineStyle": {"color": "#cbd5e1", "width": 0.5}},
                       "itemStyle": {"opacity": 0.85}}
        line_series = [
            {"type": "line3D", "data": _lines_for(yi), "lineStyle": {"color": "#18181b", "width": 2},
             "symbol": "circle", "symbolSize": 5}
            for yi in range(len(yc))
        ]
        option["series"] = [main_series] + line_series
    elif tpl_type == "histogram-4grid":
        # 联动直方图：原始双变量 [[x, y], ...]，自研 sturges 分箱（echarts-stat 有 bug）
        raw = (series[0].get("data") or []) if series else []
        xs = [r[0] for r in raw if isinstance(r, (list, tuple)) and len(r) >= 2]
        ys = [r[1] for r in raw if isinstance(r, (list, tuple)) and len(r) >= 2]
        x_name = data.get("xAxisName", "X")
        y_name = data.get("yAxisName", "Y")

        def _bins(vals: list, n: int) -> list:
            if not vals:
                return [{"x0": 0, "x1": 1, "count": 0, "label": "0~1"}]
            mn, mx = min(vals), max(vals)
            rng = (mx - mn) or 1
            step = rng / n
            bins = []
            for i in range(n):
                x0 = mn + i * step
                x1 = (mx + 0.0001) if i == n - 1 else mn + (i + 1) * step
                bins.append({"x0": x0, "x1": x1, "count": 0,
                             "label": f"{round(x0, 1)}~{round(mx, 1) if i == n - 1 else round(mn + (i + 1) * step, 1)}"})
            for v in vals:
                for b in bins:
                    if b["x0"] <= v < b["x1"]:
                        b["count"] += 1
                        break
            return bins

        n = int(__import__("math").log2(len(xs))) + 1 if xs else 5
        x_bins = _bins(xs, n)
        y_bins = _bins(ys, n)
        option["tooltip"] = {}
        option["grid"] = [
            {"top": "52%", "right": "50%"},
            {"bottom": "54%", "right": "50%"},
            {"top": "52%", "left": "52%"},
        ]
        option["xAxis"] = [
            {"type": "value", "scale": True, "gridIndex": 0, "name": x_name},
            {"type": "category", "data": [b["label"] for b in x_bins], "axisTick": {"show": False},
             "axisLabel": {"show": False}, "axisLine": {"show": False}, "gridIndex": 1},
            {"type": "value", "scale": True, "gridIndex": 2},
        ]
        option["yAxis"] = [
            {"type": "value", "scale": True, "gridIndex": 0, "name": y_name},
            {"type": "value", "gridIndex": 1},
            {"type": "category", "data": [b["label"] for b in y_bins], "axisTick": {"show": False},
             "axisLabel": {"show": False}, "axisLine": {"show": False}, "gridIndex": 2},
        ]
        option["series"] = [
            {"name": "原始散点", "type": "scatter", "xAxisIndex": 0, "yAxisIndex": 0, "data": raw,
             "itemStyle": {"color": "#3f3f46", "opacity": 0.75}},
            {"name": f"{x_name} 分箱", "type": "bar", "xAxisIndex": 1, "yAxisIndex": 1,
             "barWidth": "99%", "data": [b["count"] for b in x_bins],
             "label": {"show": True, "position": "top", "fontSize": 9, "color": "#52525b"},
             "itemStyle": {"color": "#a1a1aa"}},
            {"name": f"{y_name} 分箱", "type": "bar", "xAxisIndex": 2, "yAxisIndex": 2,
             "barWidth": "99%", "data": [b["count"] for b in y_bins],
             "label": {"show": True, "position": "right", "fontSize": 9, "color": "#52525b"},
             "itemStyle": {"color": "#52525b"}},
        ]
    else:
        option["series"] = [
            {"name": s.get("name", f"系列{i + 1}"), "type": "bar", "data": s.get("data") or []}
            for i, s in enumerate(series)
        ]

    # 局部覆盖
    if option_overrides:
        option = _deep_merge(option, option_overrides)

    # ── v6.9-2：Python 3D 图原始数据回传 ──
    # echarts-gl 无法复刻「每行折线围成的填充平面」瀑布样式，3D 模板改用
    # Python(mplot3d) 生成 PNG。原数据（x/y 类别 + 三元组）注入 option._py_data，
    # 前端 ChartRenderer 优先取它转发给 /api/apps/finmod/py-chart。
    if tpl_type in ("waterfall3d", "bar3d", "scatter3d"):
        option["_py_data"] = {
            "xCategories": data.get("xCategories") or cats,
            "yCategories": data.get("yCategories") or [],
            "xAxisName": data.get("xAxisName") or "X",
            "yAxisName": data.get("yAxisName") or "Y",
            "zAxisName": data.get("zAxisName") or "Z",
            "series": [{"name": (series[0].get("name") if series else None) or "数据",
                        "data": (series[0].get("data") if series else []) or []}],
        }

    # ── 阶段 3：官方级优化注入（v6.6，2026-08-22）──
    # AI 输出自动对齐 ECharts 官方示例观感：数据增长动画 + 缓动；
    # 大数据量（类别 >12）自动隐藏数据点标签避免贴死（官方大数据量风格）。
    option.setdefault("animationDuration", 1500)
    option.setdefault("animationEasing", "cubicOut")
    opt_series = option.get("series")
    if isinstance(opt_series, list):
        n_cats = len(data.get("categories") or [])
        for s in opt_series:
            if isinstance(s, dict) and isinstance(s.get("label"), dict) and n_cats > 12:
                s["label"]["show"] = False  # 大数据量降采样（官方 style）

    markdown_block = "```chart-json\n" + json.dumps({
        "template": template, "title": title, "option": option, "data_table": data_table,
    }, ensure_ascii=False) + "\n```"

    return {"success": True, "result": {
        "chart_id": f"chart-{abs(hash(template + title)) % 100000}",
        "template": template,
        "title": title,
        "option": option,
        "data_table": data_table,
        "markdown_block": markdown_block,
    }}


def _deep_merge(base: dict, override: dict) -> dict:
    """浅层+深层字典合并（override 优先）。"""
    out = dict(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out
