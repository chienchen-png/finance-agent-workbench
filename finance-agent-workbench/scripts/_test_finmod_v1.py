# -*- coding: utf-8 -*-
"""_test_finmod_v1 — V1 统计量扩展单测（varmap 方向/类型 + 统计量广播 + run 物化）。

用法：python scripts/_test_finmod_v1.py
"""

import sys
import os

sys.path.insert(0, r"d:\Finance Recon Agent\finance-agent-workbench")
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

import pandas as pd  # noqa: E402
from tools.finmod_eval import materialize_derived, _finmod_eval  # noqa: E402
from routes import finmod_refs  # noqa: E402

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


def main():
    # ---- 1. references 变量方向/类型解析 ----
    print("== [1] references 变量方向/类型 ==")
    g1 = finmod_refs.get_model_detail("g1-descriptive-stats")
    varmap = {v["var_name"]: v for v in (g1 or {}).get("variables", [])}
    check("G1 x_i → input", varmap.get("x_i", {}).get("direction") == "input",
          str(varmap.get("x_i")))
    check("G1 n → statistic", varmap.get("n", {}).get("direction") == "statistic",
          str(varmap.get("n")))
    check("G1 x̄ → statistic", varmap.get("x̄", {}).get("direction") == "statistic",
          str(varmap.get("x̄")))
    check("G1 s → statistic", varmap.get("s", {}).get("direction") == "statistic",
          str(varmap.get("s")))
    g3 = finmod_refs.get_model_detail("g3-regression")
    v3 = {v["var_name"]: v for v in (g3 or {}).get("variables", [])}
    check("G3 y → input", v3.get("y", {}).get("direction") == "input", str(v3.get("y")))
    check("G3 b_i → statistic", v3.get("b_i", {}).get("direction") == "statistic",
          str(v3.get("b_i")))
    check("G3 R² → statistic", v3.get("R²", {}).get("direction") == "statistic",
          str(v3.get("R²")))

    # ---- 2. 统计函数扩展 ----
    print("== [2] 统计函数扩展 ==")
    df = pd.DataFrame({"回款总额": [100.0, 200.0, 300.0, 400.0]})
    ns = {"回款总额": df["回款总额"]}
    check("MEAN=250", abs(_finmod_eval("MEAN(回款总额)", ns) - 250.0) < 1e-9, "")
    check("STD≈129.1", abs(_finmod_eval("STD(回款总额)", ns) - 129.099) < 0.01, "")
    check("MEDIAN=250", abs(_finmod_eval("MEDIAN(回款总额)", ns) - 250.0) < 1e-9, "")
    check("VAR≈16666.7", abs(_finmod_eval("VAR(回款总额)", ns) - 16666.67) < 0.1, "")
    check("COUNT=4", _finmod_eval("COUNT(回款总额)", ns) == 4, "")

    # ---- 3. 统计量广播整列 ----
    print("== [3] 统计量广播 ==")
    out_df, results, errors = materialize_derived(
        df, ["x̄=MEAN(回款总额)", "n=COUNT(回款总额)", "s=STD(回款总额)"])
    check("无错误", len(errors) == 0, str(errors))
    check("x̄ 广播整列 4 行全 250", list(out_df["x̄"]) == [250.0, 250.0, 250.0, 250.0],
          str(list(out_df["x̄"])))
    check("n 广播整列 4", list(out_df["n"]) == [4, 4, 4, 4], str(list(out_df["n"])))
    check("x̄ broadcast=True", results["x̄"]["broadcast"] is True, str(results["x̄"]))
    check("s≈129.1", abs(float(out_df["s"][0]) - 129.099) < 0.01, "")

    # ---- 4. 广播列可被后续引用 ----
    print("== [4] 广播列后序引用 ==")
    out2, res2, err2 = materialize_derived(
        df, ["x̄=MEAN(回款总额)", "偏离=x̄-回款总额"])
    check("无错误", len(err2) == 0, str(err2))
    check("偏离=均值-各行", list(out2["偏离"]) == [150.0, 50.0, -50.0, -150.0],
          str(list(out2["偏离"])))

    # ---- 5. LAG/PCT_CHANGE 时序 ----
    print("== [5] LAG/PCT_CHANGE ==")
    out3, res3, err3 = materialize_derived(
        df, ["lag1=LAG(回款总额,1)", "chg=PCT_CHANGE(回款总额,1)"])
    check("无错误", len(err3) == 0, str(err3))
    check("LAG 前移", pd.isna(out3["lag1"][0]) and
          list(out3["lag1"][1:]) == [100.0, 200.0, 300.0],
          str(list(out3["lag1"])))
    check("PCT_CHANGE", abs(float(out3["chg"][1]) - 1.0) < 1e-9 and
          abs(float(out3["chg"][2]) - 0.5) < 1e-9, str(list(out3["chg"])))

    # ---- 汇总 ----
    print("\n========================================")
    print(f"V1 统计量扩展单测: PASS={PASS} FAIL={len(FAIL)}")
    for f in FAIL:
        print(f"  [FAIL] {f}")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
