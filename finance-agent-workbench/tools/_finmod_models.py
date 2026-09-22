"""_finmod_models — 应用二模型计算注册表（P5 执行引擎，2026-08-21）。

需求文档 §四 步骤 6 ⑥：32 模型全部映射确定性计算函数——
  - 复用 L1（约 13 个）：D1/D2/E1/E3/E4/E5/F1/G2/G3/G4/G5/C1 → 直接调用
    financial_analysis_tools 的 financial_metrics / sensitivity_analysis /
    correlation_matrix / regression_analysis / time_series_analysis
  - 新增 pandas 实现（约 19 个）：A1-A4 / B1-B4 / C2-C4 / D3 / D4 / D5 /
    E2 / E6 / F2-F4 / G1

注册表 = model_id → {code, name, kind("l1"|"df"), compute, required_vars,
recommended_charts, summary}。kind="l1" 的 compute(params) 直接调 L1 工具
（读主库，只读零污染）；kind="df" 的 compute(df, params) 在已按变量映射
列重命名的 DataFrame 上确定性计算（TmpRun 快照加载，主库零污染）。

输出统一「结果摘要 JSON」+ 可选图表数据（data_table/categories/series）。
验收：_test_finmod_models.py 对 32 模型逐一跑通（造数 + 手算一致）。
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ----------------------------------------------------------------------
# 计算辅助
# ----------------------------------------------------------------------


def _num(s: pd.Series) -> pd.Series:
    """列转数值（coerce）。"""
    return pd.to_numeric(s, errors="coerce")


def _last(s: pd.Series) -> float | None:
    """最后一个非空数值。"""
    v = _num(s).dropna()
    return float(v.iloc[-1]) if len(v) else None


def _ratio(a: float | None, b: float | None, nd: int = 4) -> float | None:
    if a is None or b in (None, 0):
        return None
    return round(float(a) / float(b), nd)


def _round2(v: Any) -> Any:
    """浮点四舍五入 2 位；None/NaN 保留。"""
    if v is None:
        return None
    try:
        f = float(v)
        if np.isnan(f) or np.isinf(f):
            return None
        return round(f, 2)
    except (TypeError, ValueError):
        return v


def _sum_col(df: pd.DataFrame, col: str) -> float:
    return float(_num(df[col]).sum()) if col in df.columns else 0.0


def _mean_col(df: pd.DataFrame, col: str) -> float:
    s = _num(df[col]).dropna()
    return float(s.mean()) if len(s) else 0.0


# ----------------------------------------------------------------------
# 新增 pandas 实现（kind="df"，df 列 = 模型变量名）
# ----------------------------------------------------------------------

# A1 三表联动：勾稽校验 + 期末留存/期末现金
def _calc_a1(df: pd.DataFrame, params: dict) -> dict:
    np_ = _last(df["净利润"]) if "净利润" in df.columns else None
    ret0 = _last(df["期初留存收益"]) if "期初留存收益" in df.columns else None
    div = _last(df["股利"]) if "股利" in df.columns else None
    cfo = _last(df["经营活动净流量"]) if "经营活动净流量" in df.columns else None
    cfi = _last(df["投资活动净流量"]) if "投资活动净流量" in df.columns else None
    cff = _last(df["筹资活动净流量"]) if "筹资活动净流量" in df.columns else None
    cash0 = _last(df["期初现金"]) if "期初现金" in df.columns else None
    assets = _last(df["资产"]) if "资产" in df.columns else None
    liab = _last(df["负债"]) if "负债" in df.columns else None
    eq = _last(df["所有者权益"]) if "所有者权益" in df.columns else None

    ret1 = round(ret0 + np_ - div, 2) if ret0 is not None and np_ is not None and div is not None else None
    cash1 = round(cash0 + cfo + cfi + cff, 2) if cash0 is not None and cfo is not None and cfi is not None and cff is not None else None
    balance_ok = None
    if assets is not None and liab is not None and eq is not None:
        balance_ok = abs(assets - (liab + eq)) < 1e-6
    checks = []
    if np_ is not None and cfo is not None:
        checks.append({"项": "净利润→经营现金流勾稽", "期望": "约等于（利润≠现金流，仅近似）", "状态": "参考"})
    if ret1 is not None:
        checks.append({"项": "期末留存收益 = 期初 + 净利 − 股利", "值": ret1, "状态": "计算"})
    if cash1 is not None:
        checks.append({"项": "期末现金 = 期初 + 经营/投资/筹资净流量", "值": cash1, "状态": "计算"})
    if balance_ok is not None:
        checks.append({"项": "资产 = 负债 + 所有者权益", "平衡": balance_ok, "状态": "勾稽"})
    return {"summary": {
        "期末留存收益": ret1, "期末现金": cash1, "资产=负债+权益": balance_ok,
        "勾稽项": checks,
    }}


# A2 利润表预测：比例法（各项占收入比例 → 外推）
def _calc_a2(df: pd.DataFrame, params: dict) -> dict:
    rev = _num(df["营业收入"]) if "营业收入" in df.columns else pd.Series(dtype=float)
    rev_last = float(rev.dropna().iloc[-1]) if len(rev.dropna()) else None
    growth = params.get("growth_rate", 0.05)
    out: dict[str, Any] = {}
    if rev_last is not None:
        next_rev = round(rev_last * (1 + growth), 2)
        out["预测营业收入"] = next_rev
        for c in ("营业成本", "费用", "税金"):
            if c in df.columns:
                ratio = _last(df[c]) / rev_last if rev_last else None
                out[f"{c}（按收入比例 {_round2(ratio) if ratio is not None else '—'}）"] = (
                    round(next_rev * ratio, 2) if ratio is not None else None)
        np_col = "净利润"
        if np_col in df.columns:
            npm = _last(df[np_col]) / rev_last if rev_last else None
            out["预测净利润"] = round(next_rev * npm, 2) if npm is not None else None
    return {"summary": out, "assumption": f"比例法外推，营收增长 {growth:.0%}"}


# A3 现金流预测：线性外推
def _calc_a3(df: pd.DataFrame, params: dict) -> dict:
    col = "经营活动净流量" if "经营活动净流量" in df.columns else (df.columns[0] if len(df.columns) else "")
    s = _num(df[col]).dropna().values.astype(float)
    if len(s) < 2:
        return {"summary": {"预测": None}, "note": "数据点过少（<2），无法预测"}
    x = np.arange(len(s))
    slope, intercept = np.polyfit(x, s, 1)
    h = max(1, int(params.get("horizon", 3)))
    forecast = [round(intercept + slope * (len(s) - 1 + t), 2) for t in range(1, h + 1)]
    return {"summary": {"方法": "线性外推", "预测值": forecast, "历史末值": _round2(s[-1])}}


# A4 合并汇总：按单元 groupby 汇总
def _calc_a4(df: pd.DataFrame, params: dict) -> dict:
    dim = params.get("dim_col") or ("单元" if "单元" in df.columns else (df.columns[0] if len(df.columns) else ""))
    val_cols = [c for c in df.columns if c != dim and _num(df[c]).notna().sum() > 0]
    if not dim or dim not in df.columns or not val_cols:
        return {"summary": {"错误": "缺少分组列或数值列"}}
    g = df.groupby(dim, dropna=False)[val_cols].sum(numeric_only=True).reset_index()
    total = {c: round(float(g[c].sum()), 2) for c in val_cols}
    top = g.sort_values(val_cols[0], ascending=False).head(5).to_dict("records")
    top = [{k: _round2(v) for k, v in r.items()} for r in top]
    return {"summary": {"维度": dim, "单元数": int(len(g)), "合计": total, "Top5": top}}


# B1 年度预算：环比驱动（上年末值 × 增长率）
def _calc_b1(df: pd.DataFrame, params: dict) -> dict:
    rate = params.get("growth_rate", 0.08)
    out: dict[str, Any] = {}
    for c in df.columns:
        last_v = _last(df[c])
        if last_v is None:
            continue
        out[c] = {"上年值": _round2(last_v), "预算值": round(last_v * (1 + rate), 2)}
    return {"summary": out, "assumption": f"统一增长率 {rate:.0%}"}


# B2 滚动预测：近 N 期均值滚动
def _calc_b2(df: pd.DataFrame, params: dict) -> dict:
    col = df.columns[0] if len(df.columns) else ""
    window = max(2, int(params.get("window", 3)))
    s = _num(df[col]).dropna().values.astype(float)
    if len(s) < window:
        return {"summary": {"错误": "数据点过少"}}
    rolling = pd.Series(s).rolling(window).mean().dropna()
    last_ma = float(rolling.iloc[-1])
    forecast = [round(last_ma, 2)] * max(1, int(params.get("horizon", 3)))
    return {"summary": {"方法": f"滚动平均(W={window})", "滚动均值序列": [_round2(v) for v in rolling.tolist()],
                        "预测值": forecast}}


# B3 销售预测：移动平均/指数平滑
def _calc_b3(df: pd.DataFrame, params: dict) -> dict:
    col = "销售额" if "销售额" in df.columns else (df.columns[0] if len(df.columns) else "")
    s = _num(df[col]).dropna().values.astype(float)
    if len(s) < 2:
        return {"summary": {"错误": "数据点过少"}}
    method = params.get("method", "exp_smooth")
    h = max(1, int(params.get("horizon", 3)))
    forecast: list[float] = []
    if method == "moving_avg":
        k = min(3, len(s) - 1)
        base = float(np.mean(s[-k:]))
        forecast = [round(base, 2)] * h
        label = f"移动平均(W={k})"
    else:
        alpha = 0.3
        yhat = float(s[0])
        for v in s[1:]:
            yhat = alpha * v + (1 - alpha) * yhat
        for _ in range(h):
            yhat = alpha * yhat + (1 - alpha) * yhat
            forecast.append(round(float(yhat), 2))
        label = "指数平滑(α=0.3)"
    return {"summary": {"方法": label, "历史末值": _round2(s[-1]), "预测值": forecast}}


# B4 成本预算：成本占收入比例 → 预算
def _calc_b4(df: pd.DataFrame, params: dict) -> dict:
    rate = params.get("growth_rate", 0.05)
    out: dict[str, Any] = {}
    rev = _num(df["营业收入"]).dropna() if "营业收入" in df.columns else pd.Series(dtype=float)
    rev_last = float(rev.iloc[-1]) if len(rev) else None
    if rev_last is None:
        return {"summary": {"错误": "缺少营业收入列"}}
    for c in ("营业成本", "费用", "管理费用", "销售费用"):
        if c in df.columns:
            ratio = _last(df[c]) / rev_last if rev_last else None
            out[c] = {"占收入比": _round2(ratio), "预算值": round(rev_last * (1 + rate) * ratio, 2) if ratio is not None else None}
    return {"summary": out, "assumption": f"按收入增长 {rate:.0%} 驱动"}


# C2 边际贡献：收入 − 变动成本，按维度
def _calc_c2(df: pd.DataFrame, params: dict) -> dict:
    dim = params.get("dim_col") or ""
    rev_c = "收入" if "收入" in df.columns else ("营业收入" if "营业收入" in df.columns else None)
    vc_c = "变动成本" if "变动成本" in df.columns else ("成本" if "成本" in df.columns else None)
    if rev_c is None or vc_c is None:
        return {"summary": {"错误": "缺少收入/变动成本列"}}
    d = df.copy()
    d["边际贡献"] = _num(d[rev_c]) - _num(d[vc_c])
    d["贡献率"] = d["边际贡献"] / _num(d[rev_c]).replace(0, np.nan)
    if dim and dim in d.columns and len(d[dim].unique()) > 1:
        # groupby 求和（避免键列与数值列重名 → 先 rename）
        g = d.groupby(dim, dropna=False)[[rev_c, vc_c]].sum(numeric_only=True).reset_index()
        g["边际贡献"] = _num(g[rev_c]) - _num(g[vc_c])
        g["贡献率"] = g["边际贡献"] / g[rev_c].replace(0, np.nan)
        g = g.sort_values("边际贡献", ascending=False).reset_index(drop=True)
        rows = g.head(10).to_dict("records")
    else:
        rows = [{"收入": _round2(d[rev_c].sum()), "变动成本": _round2(d[vc_c].sum()),
                 "边际贡献": _round2(d["边际贡献"].sum()),
                 "贡献率": _round2(d["边际贡献"].sum() / d[rev_c].sum() if d[rev_c].sum() else None)}]
    return {"summary": {"维度": dim or "整体", "总边际贡献": _round2(d["边际贡献"].sum()), "明细": rows}}


# C3 成本差异：实际 vs 标准
def _calc_c3(df: pd.DataFrame, params: dict) -> dict:
    act = "实际成本" if "实际成本" in df.columns else ("实际" if "实际" in df.columns else None)
    std = "标准成本" if "标准成本" in df.columns else ("标准" if "标准" in df.columns else None)
    if act is None or std is None:
        return {"summary": {"错误": "缺少实际/标准成本列"}}
    d = df.copy()
    d["差异"] = _num(d[act]) - _num(d[std])
    d["差异率"] = d["差异"] / _num(d[std]).replace(0, np.nan)
    total_diff = float(d["差异"].sum())
    rows = d.head(10).to_dict("records")
    return {"summary": {"总差异": _round2(total_diff),
                        "有利/不利": "不利（超支）" if total_diff > 0 else "有利（节约）",
                        "明细": [{k: _round2(v) for k, v in r.items()} for r in rows]}}


# C4 产品线盈利：groupby 产品线
def _calc_c4(df: pd.DataFrame, params: dict) -> dict:
    dim = params.get("dim_col") or ("产品线" if "产品线" in df.columns else (df.columns[0] if len(df.columns) else ""))
    rev = "收入" if "收入" in df.columns else ("营业收入" if "营业收入" in df.columns else None)
    cost = "成本" if "成本" in df.columns else ("营业成本" if "营业成本" in df.columns else None)
    if rev is None or cost is None or dim not in df.columns:
        return {"summary": {"错误": "缺少维度/收入/成本列"}}
    d = df.copy()
    d["毛利"] = _num(d[rev]) - _num(d[cost])
    d["毛利率"] = d["毛利"] / _num(d[rev]).replace(0, np.nan)
    g = d.groupby(dim).agg(收入=(rev, "sum"), 成本=(cost, "sum"), 毛利=("毛利", "sum")).reset_index()
    g["毛利率"] = g["毛利"] / g["收入"].replace(0, np.nan)
    g = g.sort_values("毛利", ascending=False).reset_index(drop=True)
    return {"summary": {"维度": dim, "盈利Top": g.head(8).to_dict("records"), "亏损线": g[g["毛利"] < 0].head(8).to_dict("records")}}


# D3 预算差异：实际 vs 预算
def _calc_d3(df: pd.DataFrame, params: dict) -> dict:
    act = "实际值" if "实际值" in df.columns else ("实际" if "实际" in df.columns else None)
    bud = "预算值" if "预算值" in df.columns else ("预算" if "预算" in df.columns else None)
    if act is None or bud is None:
        return {"summary": {"错误": "缺少实际/预算列"}}
    d = df.copy()
    d["差异"] = _num(d[act]) - _num(d[bud])
    d["差异率"] = d["差异"] / _num(d[bud]).replace(0, np.nan)
    total = float(d["差异"].sum())
    return {"summary": {"总差异": _round2(total), "差异率": _round2(total / float(_num(d[bud]).sum()) if _num(d[bud]).sum() else None),
                        "明细": [{k: _round2(v) for k, v in r.items()} for r in d.head(10).to_dict("records")]}}


# D4 同比/环比/结构分析
def _calc_d4(df: pd.DataFrame, params: dict) -> dict:
    if len(df.columns) < 2:
        return {"summary": {"错误": "需要期间列 + 数值列"}}
    period_col = params.get("period_col") or df.columns[0]
    val_cols = [c for c in df.columns if c != period_col and _num(df[c]).notna().sum() > 0]
    if not val_cols:
        return {"summary": {"错误": "无数值列"}}
    d = df.copy()
    out: dict[str, Any] = {}
    for c in val_cols[:3]:
        v = _num(d[c])
        d[f"{c}_环比"] = v.pct_change()
        d[f"{c}_同比"] = v.pct_change(4) if len(v) >= 5 else None
        d[f"{c}_占比"] = v / v.sum() if v.sum() else None
    cols_out = [period_col] + val_cols[:3] + [f"{c}_环比" for c in val_cols[:3]] + [f"{c}_占比" for c in val_cols[:3]]
    rows = d[cols_out].tail(8).to_dict("records")
    return {"summary": {"期间列": period_col, "最新环比/同比/占比": rows}}


# D5 杠杆：经营/财务/总杠杆
def _calc_d5(df: pd.DataFrame, params: dict) -> dict:
    q = _num(df["销量"]) if "销量" in df.columns else pd.Series(dtype=float)
    p = _last(df["单价"]) if "单价" in df.columns else None
    v = _last(df["单位变动成本"]) if "单位变动成本" in df.columns else None
    f = _last(df["固定成本"]) if "固定成本" in df.columns else None
    i_ = _last(df["利息"]) if "利息" in df.columns else None
    qq = float(q.dropna().iloc[-1]) if len(q.dropna()) else None
    if p is None or v is None or f is None or qq is None:
        return {"summary": {"错误": "缺少单价/变动成本/固定成本/销量"}}
    cm = (p - v) * qq          # 边际贡献
    ebit = cm - f              # 息税前利润
    ebt = ebit - (i_ or 0)     # 税前利润
    dol = cm / ebit if ebit else None       # 经营杠杆
    dfl = ebit / ebt if ebt else None       # 财务杠杆
    dtl = cm / ebt if ebt else None         # 总杠杆
    return {"summary": {"边际贡献": _round2(cm), "EBIT": _round2(ebit), "EBT": _round2(ebt),
                        "经营杠杆DOL": _round2(dol), "财务杠杆DFL": _round2(dfl), "总杠杆DTL": _round2(dtl)}}


# E2 WACC：加权平均资本成本
def _calc_e2(df: pd.DataFrame, params: dict) -> dict:
    eq = _last(df["权益市值"]) if "权益市值" in df.columns else None
    debt = _last(df["债务市值"]) if "债务市值" in df.columns else None
    re = params.get("cost_of_equity", 0.12)
    rd = params.get("cost_of_debt", 0.05)
    tax = params.get("tax_rate", 0.25)
    if eq is None or debt is None or eq + debt == 0:
        return {"summary": {"错误": "缺少权益/债务市值"}}
    w_e = eq / (eq + debt)
    w_d = debt / (eq + debt)
    wacc = w_e * re + w_d * rd * (1 - tax)
    return {"summary": {"权益权重": _round2(w_e), "债务权重": _round2(w_d),
                        "WACC": round(wacc * 100, 2), "参数": {"Re": re, "Rd": rd, "税率": tax}}}


# E6 设备更新：年均成本法（EAC）
def _calc_e6(df: pd.DataFrame, params: dict) -> dict:
    cost = params.get("cost", 100000)
    salvage = params.get("salvage", 10000)
    life = int(params.get("life", 10))
    rate = params.get("discount_rate", 0.10)
    if life <= 0 or rate <= -1:
        return {"summary": {"错误": "寿命或折现率非法"}}
    pvaf = (1 - (1 + rate) ** -life) / rate if rate else life
    pv_salvage = salvage / (1 + rate) ** life
    eac = (cost - pv_salvage) / pvaf
    return {"summary": {"设备成本": cost, "残值现值": _round2(pv_salvage), "年限": life,
                        "折现率": rate, "年均成本EAC": _round2(eac)}}


# F2 账龄分析：按账龄段分组汇总
def _calc_f2(df: pd.DataFrame, params: dict) -> dict:
    amt = "应收账款" if "应收账款" in df.columns else ("金额" if "金额" in df.columns else None)
    age = "账龄天数" if "账龄天数" in df.columns else ("账龄" if "账龄" in df.columns else None)
    if amt is None:
        return {"summary": {"错误": "缺少金额列"}}
    d = df.copy()
    a = _num(d[amt])
    if age and age in d.columns:
        ag = _num(d[age])
        def bucket(x):
            if pd.isna(x):
                return "未知"
            if x <= 30:
                return "0-30天"
            if x <= 60:
                return "31-60天"
            if x <= 90:
                return "61-90天"
            if x <= 180:
                return "91-180天"
            return "180天以上"
        d["账龄段"] = ag.apply(bucket)
        g = d.groupby("账龄段")[amt].sum(numeric_only=True).sort_values(ascending=False).reset_index()
        total = float(a.sum())
        g["占比"] = g[amt] / total if total else 0
        return {"summary": {"总额": _round2(total), "账龄分布": g.to_dict("records")}}
    total = float(a.sum())
    return {"summary": {"总额": _round2(total), "行数": int(len(d))}}


# F3 存货周转：周转率 + 周转天数
def _calc_f3(df: pd.DataFrame, params: dict) -> dict:
    cost = _last(df["营业成本"]) if "营业成本" in df.columns else (_last(df["成本"]) if "成本" in df.columns else None)
    inv = _last(df["存货"]) if "存货" in df.columns else None
    if cost is None or inv is None or inv == 0:
        return {"summary": {"错误": "缺少营业成本/存货列"}}
    ito = cost / inv
    return {"summary": {"存货周转率": _round2(ito), "周转天数": _round2(365 / ito if ito else None)}}


# F4 营运资金需求 WCR
def _calc_f4(df: pd.DataFrame, params: dict) -> dict:
    ar = _last(df["应收账款"]) if "应收账款" in df.columns else None
    inv = _last(df["存货"]) if "存货" in df.columns else None
    ap = _last(df["应付账款"]) if "应付账款" in df.columns else None
    if ar is None and inv is None and ap is None:
        return {"summary": {"错误": "缺少应收/存货/应付列"}}
    wcr = (ar or 0) + (inv or 0) - (ap or 0)
    return {"summary": {"应收账款": _round2(ar), "存货": _round2(inv), "应付账款": _round2(ap),
                        "营运资金需求WCR": _round2(wcr)}}


# G1 描述性统计
def _calc_g1(df: pd.DataFrame, params: dict) -> dict:
    cols = [c for c in df.columns if _num(df[c]).notna().sum() > 0]
    if not cols:
        return {"summary": {"错误": "无数值列"}}
    out: dict[str, Any] = {}
    for c in cols[:8]:
        s = _num(df[c]).dropna()
        out[c] = {"均值": _round2(s.mean()), "中位数": _round2(s.median()),
                  "标准差": _round2(s.std()), "最小值": _round2(s.min()),
                  "最大值": _round2(s.max()), "缺失": int(df[c].isna().sum())}
    return {"summary": out}


# ----------------------------------------------------------------------
# L1 公式的 df 版实现（复用 financial_analysis_tools 公式，纯 DataFrame）
# ----------------------------------------------------------------------

# C1 本量利/盈亏平衡：q_be = fc / (p - v)
def _calc_c1(df: pd.DataFrame, params: dict) -> dict:
    p = _last(df["单价"]) if "单价" in df.columns else None
    v = _last(df["单位变动成本"]) if "单位变动成本" in df.columns else None
    f = _last(df["固定成本"]) if "固定成本" in df.columns else None
    q = _last(df["销量"]) if "销量" in df.columns else None
    if p is None or v is None or f is None:
        return {"summary": {"错误": "缺少单价/单位变动成本/固定成本"}}
    if p <= v:
        return {"summary": {"错误": "单价 ≤ 单位变动成本，无盈亏平衡点"}}
    q_be = f / (p - v)
    out = {"盈亏平衡销量": round(q_be, 4), "盈亏平衡收入": round(q_be * p, 4),
           "单位边际贡献": round(p - v, 4), "边际贡献率": round((p - v) / p, 4) if p else None}
    if q is not None and q > 0:
        out["安全边际"] = round(1 - q_be / q, 4)
        out["目标利润下的销量"] = round((f + params.get("target_profit", 0)) / (p - v), 4)
    return {"summary": out}


# D1 杜邦：ROE = 净利率 × 总资产周转率 × 权益乘数
def _calc_d1(df: pd.DataFrame, params: dict) -> dict:
    n = _last(df["净利润"]) if "净利润" in df.columns else None
    r = _last(df["营业收入"]) if "营业收入" in df.columns else None
    t = _last(df["总资产"]) if "总资产" in df.columns else None
    e = _last(df["所有者权益"]) if "所有者权益" in df.columns else None
    if n is None or r is None or t is None or e is None:
        return {"summary": {"错误": "缺少净利润/营业收入/总资产/所有者权益"}}
    if not r or not t or not e:
        return {"summary": {"错误": "分母为零"}}
    npm, tat, em = n / r, r / t, t / e
    return {"summary": {"ROE": round(n / e, 4), "净利率": round(npm, 4),
                        "总资产周转率": round(tat, 4), "权益乘数": round(em, 4),
                        "分解": f"{npm:.4f} × {tat:.4f} × {em:.4f}"}}


# D2 五维财务比率（期末值）
def _calc_d2(df: pd.DataFrame, params: dict) -> dict:
    def g(col):
        return _last(df[col]) if col in df.columns else None
    n, r, t, e = g("净利润"), g("营业收入"), g("总资产"), g("所有者权益")
    ca, cl = g("流动资产"), g("流动负债")
    inv, ar = g("存货"), g("应收账款")
    cost = g("营业成本") or g("成本")
    out = {
        "流动比率": _ratio(ca, cl), "速动比率": _ratio((ca - inv) if ca is not None and inv is not None else None, cl),
        "资产负债率": _ratio((t - e) if t is not None and e is not None else None, t),
        "毛利率": _ratio((r - cost) if r is not None and cost is not None else None, r),
        "净利率": _ratio(n, r), "ROE": _ratio(n, e), "ROA": _ratio(n, t),
        "应收账款周转率": _ratio(r, ar), "存货周转率": _ratio(cost, inv), "总资产周转率": _ratio(r, t),
    }
    return {"summary": out}


# E1 NPV/IRR/回收期/获利指数
def _calc_e1(df: pd.DataFrame, params: dict) -> dict:
    import numpy_financial as npf
    col = "现金流" if "现金流" in df.columns else (df.columns[0] if len(df.columns) else "")
    cf = _num(df[col]).dropna().tolist()
    if not cf:
        return {"summary": {"错误": "无现金流数据"}}
    rate = float(params.get("discount_rate", 0.10))
    npv = float(npf.npv(rate, cf))
    irr = float(npf.irr(cf)) if len(cf) > 1 else None
    cum, payback = 0.0, None
    for t, c in enumerate(cf):
        cum += float(c)
        if cum >= 0 and t >= 1:
            payback = float(t)
            break
    inv0 = abs(float(cf[0])) if cf[0] else 1.0
    pi = (npv + inv0) / inv0 if inv0 else None
    return {"summary": {"NPV": _round2(npv), "IRR": round(irr, 4) if irr is not None else None,
                        "回收期(期)": payback, "获利指数PI": _round2(pi), "折现率": rate}}


# F1 现金周期 CCC = DSO + DIO
def _calc_f1(df: pd.DataFrame, params: dict) -> dict:
    r = _last(df["营业收入"]) if "营业收入" in df.columns else None
    co = _last(df["营业成本"]) if "营业成本" in df.columns else (_last(df["成本"]) if "成本" in df.columns else None)
    ar = _last(df["应收账款"]) if "应收账款" in df.columns else None
    inv = _last(df["存货"]) if "存货" in df.columns else None
    if not r or not co:
        return {"summary": {"错误": "缺少营业收入/营业成本"}}
    dso = 365 * ar / r if r and ar is not None else None
    dio = 365 * inv / co if co and inv is not None else None
    ccc = (dso - dio) if dso is not None and dio is not None else None
    return {"summary": {"DSO(应收周转天数)": _round2(dso), "DIO(存货周转天数)": _round2(dio),
                        "DPO(应付周转天数)": None, "现金周期CCC": _round2(ccc)}}


# E3 单变量敏感性（±5/10/15%）
def _calc_e3(df: pd.DataFrame, params: dict) -> dict:
    formula = params.get("formula", "收入-成本")
    base = {}
    for c in df.columns:
        v = _last(df[c])
        if v is not None:
            base[c] = v
    if not base:
        return {"summary": {"错误": "无数值列"}}
    from tools.finmod_eval import _finmod_eval
    one_way = []
    for var, val in base.items():
        changes = []
        for mult in (0.85, 0.9, 0.95, 1.05, 1.1, 1.15):
            ns = dict(base)
            ns[var] = float(val) * float(mult)
            try:
                res = _finmod_eval(formula, ns)
                changes.append({"变动": f"{mult * 100:.0f}%", "结果": _round2(float(res))})
            except Exception:  # noqa: BLE001
                continue
        if changes:
            one_way.append({"变量": var, "基准": _round2(val), "变化": changes})
    try:
        base_res = _round2(float(_finmod_eval(formula, base)))
    except Exception:  # noqa: BLE001
        base_res = None
    return {"summary": {"基准结果": base_res, "公式": formula, "单变量敏感性": one_way}}


# E4 情景分析
def _calc_e4(df: pd.DataFrame, params: dict) -> dict:
    formula = params.get("formula", "收入-成本")
    base = {c: (_last(df[c]) if _last(df[c]) is not None else 0) for c in df.columns}
    from tools.finmod_eval import _finmod_eval
    scenarios = params.get("scenarios") or {}
    out: dict[str, Any] = {}
    for name, mults in scenarios.items():
        ns = dict(base)
        for k, mult in (mults or {}).items():
            if k in ns:
                ns[k] = float(ns[k]) * float(mult)
        try:
            out[name] = _round2(float(_finmod_eval(formula, ns)))
        except Exception:  # noqa: BLE001
            out[name] = None
    try:
        base_res = _round2(float(_finmod_eval(formula, base)))
    except Exception:  # noqa: BLE001
        base_res = None
    return {"summary": {"基准": base_res, "情景结果": out, "公式": formula}}


# G2 相关性矩阵
def _calc_g2(df: pd.DataFrame, params: dict) -> dict:
    cols = [c for c in df.columns if _num(df[c]).notna().sum() > 1]
    if len(cols) < 2:
        return {"summary": {"错误": "数值列不足 2 个"}}
    sub = pd.DataFrame({c: _num(df[c]) for c in cols})
    corr = sub.corr()
    matrix = [[round(float(v), 4) for v in row] for row in corr.values]
    threshold = float(params.get("threshold", 0.6))
    pairs = []
    for i in range(len(cols)):
        for j in range(i + 1, len(cols)):
            r = float(corr.iloc[i, j])
            if abs(r) >= threshold:
                pairs.append({"a": cols[i], "b": cols[j], "r": round(r, 4)})
    pairs.sort(key=lambda p: -abs(p["r"]))
    return {"summary": {"columns": cols, "matrix": matrix, "top_pairs": pairs[:20], "threshold": threshold}}


# G3 一元线性回归（scipy）
def _calc_g3(df: pd.DataFrame, params: dict) -> dict:
    from scipy import stats
    y_col = params.get("y_column") or (df.columns[-1] if len(df.columns) else "")
    x_col = params.get("x_column") or (df.columns[0] if len(df.columns) else "")
    if not x_col or not y_col or x_col not in df.columns or y_col not in df.columns:
        return {"summary": {"错误": "缺少 x/y 列"}}
    x = _num(df[x_col]).dropna()
    mask = _num(df[y_col]).notna()
    y = _num(df[y_col])[mask]
    x = x[mask]
    if len(x) < 3:
        return {"summary": {"错误": "样本过少（<3）"}}
    res = stats.linregress(x.values, y.values)
    return {"summary": {"模型": f"{y_col} = {res.intercept:.4f} + {res.slope:.4f} × {x_col}",
                        "斜率": round(float(res.slope), 6), "截距": round(float(res.intercept), 6),
                        "R²": round(float(res.rvalue ** 2), 6), "p值": round(float(res.pvalue), 6),
                        "样本数": int(len(x))}}


# G4 时间序列分解（经典比例法，简化）
def _calc_g4(df: pd.DataFrame, params: dict) -> dict:
    col = "值" if "值" in df.columns else (df.columns[0] if len(df.columns) else "")
    s = _num(df[col]).dropna().values.astype(float)
    if len(s) < 4:
        return {"summary": {"错误": "数据点过少（<4）"}}
    period = min(4, len(s) // 2)
    si = {}
    if period >= 2:
        idx = pd.Series(s)
        ma = idx.rolling(period, center=True).mean().ffill().bfill()
        ratio = idx / ma
        vals = []
        for p in range(period):
            seg = ratio.iloc[p::period].dropna().values
            vals.append(float(np.mean(seg)) if len(seg) else 1.0)
        vals = np.array(vals)
        if np.mean(vals) > 0:
            vals = vals / np.mean(vals)
        si = {f"s{p + 1}": round(float(vals[p]), 4) for p in range(period)}
    x = np.arange(len(s))
    slope, intercept = np.polyfit(x, s, 1)
    trend = [round(intercept + slope * i, 2) for i in range(len(s))]
    return {"summary": {"周期": period, "季节指数": si, "趋势": trend[-8:], "末值": _round2(s[-1])}}


# G5 预测（线性外推/移动平均/指数平滑）
def _calc_g5(df: pd.DataFrame, params: dict) -> dict:
    col = params.get("value_column") or (df.columns[0] if len(df.columns) else "")
    s = _num(df[col]).dropna().values.astype(float)
    if len(s) < 2:
        return {"summary": {"错误": "数据点过少（<2）"}}
    h = max(1, int(params.get("horizon", 3)))
    method = params.get("method", "linear")
    if method == "moving_avg":
        k = min(3, len(s) - 1)
        base = float(np.mean(s[-k:]))
        forecast = [round(base, 2)] * h
        label = f"移动平均(W={k})"
    elif method == "exp_smooth":
        alpha = 0.3
        yhat = float(s[0])
        for v in s[1:]:
            yhat = alpha * v + (1 - alpha) * yhat
        for _ in range(h):
            yhat = alpha * yhat + (1 - alpha) * yhat
            forecast.append(round(float(yhat), 2))
        label = "指数平滑(α=0.3)"
    else:
        x = np.arange(len(s))
        slope, intercept = np.polyfit(x, s, 1)
        forecast = [round(intercept + slope * (len(s) - 1 + t), 2) for t in range(1, h + 1)]
        label = "线性外推"
    return {"summary": {"方法": label, "历史末值": _round2(s[-1]), "预测值": forecast}}


# ----------------------------------------------------------------------
# 注册表（全部 kind="df"：统一 TmpRun 快照 DataFrame，主库零污染；
# 公式复用 financial_analysis_tools L1 工具的计算逻辑）
# ----------------------------------------------------------------------

MODEL_REGISTRY: dict[str, dict] = {
    # ---- A 报表预测（df） ----
    "a1-three-statement": {"code": "A1", "name": "三表联动模型", "kind": "df", "compute": _calc_a1,
                            "required_vars": ["净利润", "期初留存收益", "股利", "经营活动净流量", "投资活动净流量", "筹资活动净流量"],
                            "recommended_charts": ["bar", "line"], "summary": "三表勾稽校验"},
    "a2-income-forecast": {"code": "A2", "name": "利润表预测模型", "kind": "df", "compute": _calc_a2,
                            "required_vars": ["营业收入"], "recommended_charts": ["line", "waterfall"], "summary": "利润表比例法预测"},
    "a3-cashflow-forecast": {"code": "A3", "name": "现金流量表预测模型", "kind": "df", "compute": _calc_a3,
                              "required_vars": ["经营活动净流量"], "recommended_charts": ["line", "bar"], "summary": "现金流线性外推"},
    "a4-consolidation": {"code": "A4", "name": "多单元合并汇总模型", "kind": "df", "compute": _calc_a4,
                          "required_vars": [], "recommended_charts": ["bar", "pie"], "summary": "多单元合并汇总"},
    # ---- B 预算预测（df） ----
    "b1-budget": {"code": "B1", "name": "年度预算模型", "kind": "df", "compute": _calc_b1,
                   "required_vars": [], "recommended_charts": ["dual-axis", "gauge"], "summary": "年度预算驱动"},
    "b2-rolling-forecast": {"code": "B2", "name": "滚动预测模型", "kind": "df", "compute": _calc_b2,
                             "required_vars": [], "recommended_charts": ["line", "dual-axis"], "summary": "滚动平均预测"},
    "b3-sales-forecast": {"code": "B3", "name": "销售预测模型", "kind": "df", "compute": _calc_b3,
                           "required_vars": ["销售额"], "recommended_charts": ["line", "error-bar"], "summary": "移动平均/指数平滑"},
    "b4-cost-budget": {"code": "B4", "name": "成本费用预算模型", "kind": "df", "compute": _calc_b4,
                        "required_vars": ["营业收入"], "recommended_charts": ["bar", "waterfall"], "summary": "成本预算"},
    # ---- C 成本盈利 ----
    "c1-cvp-breakeven": {"code": "C1", "name": "本量利/盈亏平衡模型", "kind": "df", "compute": _calc_c1,
                          "required_vars": ["单价", "单位变动成本", "固定成本"], "recommended_charts": ["line", "waterfall"], "summary": "本量利/盈亏平衡"},
    "c2-contribution-margin": {"code": "C2", "name": "边际贡献分析", "kind": "df", "compute": _calc_c2,
                                "required_vars": ["收入", "变动成本"], "recommended_charts": ["bar", "waterfall"], "summary": "边际贡献"},
    "c3-cost-variance": {"code": "C3", "name": "成本差异分析", "kind": "df", "compute": _calc_c3,
                          "required_vars": ["实际成本", "标准成本"], "recommended_charts": ["tornado", "waterfall"], "summary": "成本差异"},
    "c4-product-profitability": {"code": "C4", "name": "产品线盈利分析", "kind": "df", "compute": _calc_c4,
                                  "required_vars": ["收入", "成本"], "recommended_charts": ["bar", "treemap"], "summary": "产品线盈利"},
    # ---- D 绩效比率 ----
    "d1-dupont": {"code": "D1", "name": "杜邦分析", "kind": "df", "compute": _calc_d1,
                   "required_vars": ["净利润", "营业收入", "总资产", "所有者权益"],
                   "recommended_charts": ["radar", "bar"], "summary": "杜邦三层分解"},
    "d2-financial-ratios": {"code": "D2", "name": "财务比率体系", "kind": "df", "compute": _calc_d2,
                             "required_vars": ["净利润", "营业收入", "总资产", "所有者权益"],
                             "recommended_charts": ["radar"], "summary": "五维财务比率"},
    "d3-budget-variance": {"code": "D3", "name": "预算差异分析", "kind": "df", "compute": _calc_d3,
                            "required_vars": ["实际值", "预算值"], "recommended_charts": ["waterfall", "bar"], "summary": "预算差异"},
    "d4-yoy-mom": {"code": "D4", "name": "同比/环比/结构分析", "kind": "df", "compute": _calc_d4,
                    "required_vars": [], "recommended_charts": ["bar", "line"], "summary": "同比/环比/结构"},
    "d5-leverage": {"code": "D5", "name": "经营/财务/总杠杆", "kind": "df", "compute": _calc_d5,
                     "required_vars": ["单价", "单位变动成本", "固定成本", "销量"], "recommended_charts": ["bar"], "summary": "杠杆分析"},
    # ---- E 资本决策 ----
    "e1-npv-irr": {"code": "E1", "name": "NPV/IRR/回收期", "kind": "df", "compute": _calc_e1,
                    "required_vars": ["现金流"], "recommended_charts": ["bar", "error-bar"], "summary": "NPV/IRR/回收期"},
    "e2-wacc": {"code": "E2", "name": "WACC 估算", "kind": "df", "compute": _calc_e2,
                 "required_vars": ["权益市值", "债务市值"], "recommended_charts": ["gauge"], "summary": "WACC"},
    "e3-sensitivity": {"code": "E3", "name": "敏感性分析", "kind": "df", "compute": _calc_e3,
                        "required_vars": [], "recommended_charts": ["tornado", "heatmap"], "summary": "敏感性"},
    "e4-scenario": {"code": "E4", "name": "情景分析", "kind": "df", "compute": _calc_e4,
                     "required_vars": [], "recommended_charts": ["bar", "radar"], "summary": "情景分析"},
    "e5-project-breakeven": {"code": "E5", "name": "项目盈亏平衡", "kind": "df", "compute": _calc_c1,
                              "required_vars": ["单价", "单位变动成本", "固定成本"], "recommended_charts": ["line", "bar"], "summary": "项目盈亏平衡"},
    "e6-equipment-replacement": {"code": "E6", "name": "设备更新决策", "kind": "df", "compute": _calc_e6,
                                  "required_vars": [], "recommended_charts": ["bar", "waterfall"], "summary": "设备更新EAC"},
    # ---- F 营运资金 ----
    "f1-cash-cycle": {"code": "F1", "name": "现金预算/现金周期", "kind": "df", "compute": _calc_f1,
                       "required_vars": ["营业收入", "营业成本", "应收账款", "存货"],
                       "recommended_charts": ["line", "bar"], "summary": "现金周期CCC"},
    "f2-aging-analysis": {"code": "F2", "name": "应收账款账龄分析", "kind": "df", "compute": _calc_f2,
                           "required_vars": ["应收账款"], "recommended_charts": ["bar", "pie"], "summary": "账龄分布"},
    "f3-inventory-turnover": {"code": "F3", "name": "存货周转与持有成本", "kind": "df", "compute": _calc_f3,
                               "required_vars": ["营业成本", "存货"], "recommended_charts": ["line", "bar"], "summary": "存货周转"},
    "f4-wcr": {"code": "F4", "name": "营运资金需求测算", "kind": "df", "compute": _calc_f4,
                "required_vars": ["应收账款", "存货", "应付账款"], "recommended_charts": ["line", "bar"], "summary": "WCR"},
    # ---- G 统计量化 ----
    "g1-descriptive-stats": {"code": "G1", "name": "描述性统计", "kind": "df", "compute": _calc_g1,
                              "required_vars": ["x_i"], "recommended_charts": ["boxplot", "histogram"], "summary": "描述统计"},
    "g2-correlation": {"code": "G2", "name": "相关性分析", "kind": "df", "compute": _calc_g2,
                        "required_vars": [], "recommended_charts": ["heatmap", "scatter"], "summary": "相关矩阵"},
    "g3-regression": {"code": "G3", "name": "回归分析", "kind": "df", "compute": _calc_g3,
                       "required_vars": ["y", "x_i"], "recommended_charts": ["scatter", "line"], "summary": "回归"},
    "g4-time-series-decompose": {"code": "G4", "name": "时间序列分解", "kind": "df", "compute": _calc_g4,
                                  "required_vars": [], "recommended_charts": ["line", "bar"], "summary": "时序分解"},
    "g5-forecasting": {"code": "G5", "name": "预测（移动平均/指数平滑/外推）", "kind": "df", "compute": _calc_g5,
                        "required_vars": [], "recommended_charts": ["line", "error-bar"], "summary": "预测"},
}


def get_model_spec(model_id: str) -> dict | None:
    return MODEL_REGISTRY.get(model_id)


def run_model(model_id: str, df: pd.DataFrame | None, params: dict) -> dict:
    """执行单模型（确定性，全部 kind="df"：df 列 = 变量映射后的模型变量名）。

    Returns: {model_id, code, name, summary, ok}
    """
    spec = MODEL_REGISTRY.get(model_id)
    if not spec:
        return {"model_id": model_id, "code": "?", "name": "未知模型", "ok": False,
                "summary": {"错误": f"未注册模型 {model_id}"}}
    try:
        if df is None:
            return {**spec, "model_id": model_id, "ok": False, "summary": {"错误": "缺少数据"}}
        result = spec["compute"](df, params)
        summary = result.get("summary", {})
        return {"model_id": model_id, "code": spec["code"], "name": spec["name"],
                "ok": True, "summary": summary,
                **{k: v for k, v in result.items() if k != "summary"}}
    except Exception as e:  # noqa: BLE001
        logger.warning("模型 %s 计算失败: %s", model_id, e)
        return {"model_id": model_id, "code": spec["code"], "name": spec["name"],
                "ok": False, "summary": {"错误": str(e)}}
