# -*- coding: utf-8 -*-
"""_test_finmod_models — 32 模型注册表单测（P5 验收：造数 + 手算一致）。

用法：python scripts/_test_finmod_models.py
"""

import sys

sys.path.insert(0, r"d:\Finance Recon Agent\finance-agent-workbench")

import pandas as pd
from tools._finmod_models import MODEL_REGISTRY, run_model

PASS = 0
FAIL: list[str] = []


def check(name: str, cond: bool, detail: str = ""):
    global PASS
    if cond:
        PASS += 1
        print(f"  [OK] {name}")
    else:
        FAIL.append(f"{name}: {detail}")
        print(f"  [FAIL] {name}: {detail}")


# ---- 造数：通用 df ----
df_simple = pd.DataFrame({
    "收入": [100, 200, 300, 400],
    "成本": [60, 120, 180, 240],
    "变动成本": [60, 120, 180, 240],
    "净利润": [30, 60, 90, 120],
    "期初留存收益": [100, 130, 190, 280],
    "股利": [0, 0, 0, 0],
    "经营活动净流量": [50, 80, 100, 120],
    "投资活动净流量": [-20, -30, -10, -25],
    "筹资活动净流量": [0, 0, 0, 0],
    "期初现金": [200, 230, 280, 370],
    "资产": [1000, 1000, 1000, 1000],
    "负债": [400, 400, 400, 400],
    "所有者权益": [600, 600, 600, 600],
    "营业收入": [100, 200, 300, 400],
    "营业成本": [60, 120, 180, 240],
    "费用": [10, 20, 30, 40],
    "税金": [0, 0, 0, 0],
    "销售额": [100, 120, 110, 130],
    "实际成本": [100, 200, 300, 400],
    "标准成本": [90, 190, 280, 380],
    "实际值": [100, 200, 300, 400],
    "预算值": [110, 190, 310, 390],
    "单价": [10, 10, 10, 10],
    "单位变动成本": [6, 6, 6, 6],
    "固定成本": [100, 100, 100, 100],
    "销量": [50, 60, 55, 70],
    "应收账款": [80, 90, 85, 100],
    "存货": [40, 45, 42, 50],
    "应付账款": [30, 35, 32, 40],
    "账龄天数": [10, 40, 70, 200],
    "权益市值": [6000000, 6000000, 6000000, 6000000],
    "债务市值": [4000000, 4000000, 4000000, 4000000],
})
df_simple["利润"] = df_simple["收入"] - df_simple["成本"]

print(f"共 {len(MODEL_REGISTRY)} 个模型注册")
assert len(MODEL_REGISTRY) == 32, f"注册表应有 32 模型，实际 {len(MODEL_REGISTRY)}"

# ---- A 报表预测 ----
print("\n[ A 报表预测 ]")
r = run_model("a1-three-statement", df_simple, {})
# 末值：净利润120 + 期初留存280 − 股利0 = 400
check("A1 三表联动：期末留存=400", r["ok"] and r["summary"]["期末留存收益"] == 400, str(r.get("summary")))
check("A1 资产=负债+权益", r["summary"]["资产=负债+权益"] is True)

r = run_model("a2-income-forecast", df_simple, {"growth_rate": 0.05})
check("A2 利润表预测：营收增长5%→420", r["ok"] and r["summary"]["预测营业收入"] == 420, str(r.get("summary")))

r = run_model("a3-cashflow-forecast", df_simple, {"horizon": 2})
check("A3 现金流预测：2 期线性外推", r["ok"] and len(r["summary"]["预测值"]) == 2, str(r.get("summary")))

df_units = pd.DataFrame({"单元": ["A", "A", "B"], "收入": [100, 200, 300], "成本": [60, 100, 150]})
r = run_model("a4-consolidation", df_units, {"dim_col": "单元"})
check("A4 合并汇总：2 单元", r["ok"] and r["summary"]["单元数"] == 2, str(r.get("summary")))

# ---- B 预算预测 ----
print("\n[ B 预算预测 ]")
r = run_model("b1-budget", df_simple, {"growth_rate": 0.10})
check("B1 年度预算：收入预算 440", r["ok"] and r["summary"]["收入"]["预算值"] == 440, str(r.get("summary")))

r = run_model("b2-rolling-forecast", df_simple, {"window": 3, "horizon": 2})
check("B2 滚动预测：2 期", r["ok"] and len(r["summary"]["预测值"]) == 2, str(r.get("summary")))

r = run_model("b3-sales-forecast", df_simple, {"method": "moving_avg", "horizon": 2})
check("B3 销售预测：移动平均", r["ok"] and len(r["summary"]["预测值"]) == 2, str(r.get("summary")))

r = run_model("b4-cost-budget", df_simple, {"growth_rate": 0.05})
check("B4 成本预算：营业成本占收入60%", r["ok"] and r["summary"]["营业成本"]["占收入比"] == 0.6, str(r.get("summary")))

# ---- C 成本盈利 ----
print("\n[ C 成本盈利 ]")
r = run_model("c1-cvp-breakeven", df_simple, {})
# 末值：p=10, v=6, fc=100 → q_be=25
check("C1 本量利：盈亏平衡销量 25", r["ok"] and r["summary"]["盈亏平衡销量"] == 25.0, str(r.get("summary")))

r = run_model("c2-contribution-margin", df_simple, {})
# 整体：收入 1000 − 变动成本 600 = 400
check("C2 边际贡献：总贡献 400", r["ok"] and r["summary"]["总边际贡献"] == 400, str(r.get("summary")))

r = run_model("c3-cost-variance", df_simple, {})
# 实际 1000 − 标准 940 = 60
check("C3 成本差异：总差异 60", r["ok"] and r["summary"]["总差异"] == 60, str(r.get("summary")))

r = run_model("c4-product-profitability", df_units, {"dim_col": "单元"})
check("C4 产品线盈利：2 单元", r["ok"] and len(r["summary"]["盈利Top"]) == 2, str(r.get("summary")))

# ---- D 绩效比率 ----
print("\n[ D 绩效比率 ]")
df_dupont = pd.DataFrame({"净利润": [100], "营业收入": [1000], "总资产": [2000], "所有者权益": [800]})
r = run_model("d1-dupont", df_dupont, {})
# ROE = 100/1000 × 1000/2000 × 2000/800 = 0.1×0.5×2.5 = 0.125
check("D1 杜邦：ROE=0.125", r["ok"] and r["summary"]["ROE"] == 0.125, str(r.get("summary")))

r = run_model("d2-financial-ratios", df_dupont, {})
check("D2 五维比率：净利率 0.1", r["ok"] and r["summary"]["净利率"] == 0.1, str(r.get("summary")))

r = run_model("d3-budget-variance", df_simple, {})
# 实际 1000 − 预算 1000 = 0
check("D3 预算差异：总差异 0", r["ok"] and r["summary"]["总差异"] == 0, str(r.get("summary")))

r = run_model("d4-yoy-mom", df_simple, {"period_col": "收入"})
check("D4 同比环比：可执行", r["ok"], str(r.get("summary")))

r = run_model("d5-leverage", df_simple, {})
# 销量 70：CM=(10-6)*70=280；EBIT=280-100=180；DOL=280/180≈1.5556
check("D5 杠杆：DOL=1.5556", r["ok"] and abs(r["summary"]["经营杠杆DOL"] - 1.5556) < 0.01, str(r.get("summary")))

# ---- E 资本决策 ----
print("\n[ E 资本决策 ]")
df_cf = pd.DataFrame({"现金流": [-1000, 300, 400, 500]})
r = run_model("e1-npv-irr", df_cf, {"discount_rate": 0.1})
# numpy_financial npv：CF0 计入 → -1000+272.73+330.58+375.66 ≈ -21.04
check("E1 NPV≈-21.04", r["ok"] and abs(r["summary"]["NPV"] - (-21.04)) < 0.1, str(r.get("summary")))

r = run_model("e2-wacc", df_simple, {"cost_of_equity": 0.12, "cost_of_debt": 0.05, "tax_rate": 0.25})
# WACC = 0.6*0.12 + 0.4*0.05*0.75 = 8.7%
check("E2 WACC=8.7%", r["ok"] and abs(r["summary"]["WACC"] - 8.7) < 0.01, str(r.get("summary")))

r = run_model("e3-sensitivity", df_simple, {"formula": "收入-成本"})
check("E3 敏感性：基准 160", r["ok"] and abs(r["summary"]["基准结果"] - 160) < 0.01, str(r.get("summary")))

r = run_model("e4-scenario", df_simple, {"formula": "收入-成本", "scenarios": {"乐观": {"收入": 1.1}, "悲观": {"收入": 0.9}}})
# 只改收入：400×1.1 − 240 = 200
check("E4 情景：乐观 200", r["ok"] and r["summary"]["情景结果"]["乐观"] == 200, str(r.get("summary")))

r = run_model("e5-project-breakeven", df_simple, {})
check("E5 项目盈亏平衡销量 25", r["ok"] and r["summary"]["盈亏平衡销量"] == 25.0, str(r.get("summary")))

r = run_model("e6-equipment-replacement", df_simple, {"cost": 100000, "salvage": 10000, "life": 10, "discount_rate": 0.10})
check("E6 设备更新 EAC 可算", r["ok"] and r["summary"]["年均成本EAC"] > 0, str(r.get("summary")))

# ---- F 营运资金 ----
print("\n[ F 营运资金 ]")
r = run_model("f1-cash-cycle", df_simple, {})
# 末值：AR=100, INV=50, R=400, CO=240 → DSO=91.25, DIO=76.04, CCC≈15.21
check("F1 现金周期 CCC≈15.21", r["ok"] and abs(r["summary"]["现金周期CCC"] - 15.21) < 0.1, str(r.get("summary")))

r = run_model("f2-aging-analysis", df_simple, {})
check("F2 账龄：4 段分布", r["ok"] and len(r["summary"]["账龄分布"]) == 4, str(r.get("summary")))

r = run_model("f3-inventory-turnover", df_simple, {})
# 240/50 = 4.8
check("F3 存货周转率 4.8", r["ok"] and r["summary"]["存货周转率"] == 4.8, str(r.get("summary")))

r = run_model("f4-wcr", df_simple, {})
# 100+50-40 = 110
check("F4 WCR=110", r["ok"] and r["summary"]["营运资金需求WCR"] == 110, str(r.get("summary")))

# ---- G 统计量化 ----
print("\n[ G 统计量化 ]")
r = run_model("g1-descriptive-stats", df_simple, {})
check("G1 描述统计可执行", r["ok"] and "收入" in r["summary"], str(r.get("summary")))
check("G1 收入均值 250", r["summary"]["收入"]["均值"] == 250)

r = run_model("g2-correlation", df_simple, {})
check("G2 相关矩阵：列数 ≥ 2", r["ok"] and len(r["summary"]["matrix"]) >= 2, str(r.get("summary")))

r = run_model("g3-regression", df_simple, {"x_column": "销量", "y_column": "收入"})
check("G3 回归：R² 可算", r["ok"] and r["summary"]["R²"] is not None, str(r.get("summary")))

r = run_model("g4-time-series-decompose", df_simple, {})
check("G4 时序分解：趋势存在", r["ok"] and r["summary"]["末值"] is not None, str(r.get("summary")))

r = run_model("g5-forecasting", df_simple, {"horizon": 2, "method": "linear"})
check("G5 预测：2 期", r["ok"] and len(r["summary"]["预测值"]) == 2, str(r.get("summary")))

# 模型总数检查
print(f"\n通过 {PASS} 项，失败 {len(FAIL)} 项")
if FAIL:
    print("失败项：")
    for f in FAIL:
        print(f"  - {f}")
    sys.exit(1)
print("_test_finmod_models 全部 PASS ✓")
