# -*- coding: utf-8 -*-
"""_test_finmod_v3 — V3 数据预处理单测（prep-data 四类操作 + run 物化）。

用法：python scripts/_test_finmod_v3.py
"""

import sys
import os

sys.path.insert(0, r"d:\Finance Recon Agent\finance-agent-workbench")
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

import pandas as pd  # noqa: E402
from tools.finmod_prep import _apply_clean, _apply_cast, _apply_pivot  # noqa: E402

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
    # ---- 1. clean: dedup 去重 ----
    print("== [1] clean dedup ==")
    df = pd.DataFrame({"业务员": ["A", "A", "B"], "金额": [1, 2, 3]})
    out, log = _apply_clean(df, {"op": "clean", "action": "dedup"})
    check("去重 3→3（无重复行）", len(out) == 3, f"len={len(out)}")
    df2 = pd.DataFrame({"业务员": ["A", "A", "B"], "金额": [1, 1, 3]})
    out2, _ = _apply_clean(df2, {"op": "clean", "action": "dedup"})
    check("全列去重 3→2", len(out2) == 2, f"len={len(out2)}")
    out3, _ = _apply_clean(df2, {"op": "clean", "action": "dedup", "subset": ["业务员"]})
    check("按业务员去重 3→2", len(out3) == 2, f"len={len(out3)}")

    # ---- 2. clean: filter 过滤 ----
    print("== [2] clean filter ==")
    out4, _ = _apply_clean(df, {"op": "clean", "action": "filter",
                                "where": {"col": "金额", "op": "gte", "value": 2}})
    check("金额≥2 → 2 行", len(out4) == 2, f"len={len(out4)}")

    # ---- 3. clean: replace 替换异常值 ----
    print("== [3] clean replace ==")
    out5, _ = _apply_clean(df, {"op": "clean", "action": "replace",
                                "where": {"col": "金额", "op": "lt", "value": 2},
                                "with": None})
    check("金额<2 → None", pd.isna(out5.loc[0, "金额"]), str(out5.loc[0, "金额"]))

    # ---- 4. cast 类型修正 ----
    print("== [4] cast ==")
    dfc = pd.DataFrame({"金额": ["1", "2.5", "abc"]})
    outc, _ = _apply_cast(dfc, {"op": "cast", "col": "金额", "to": "numeric"})
    check("文本→数值（abc→NaN）", outc["金额"].dtype.kind in "fiu" and pd.isna(outc.loc[2, "金额"]),
          f"dtype={outc['金额'].dtype}")
    dfd = pd.DataFrame({"日期": ["2024-01-01", "2024-02-01"]})
    outd, _ = _apply_cast(dfd, {"op": "cast", "col": "日期", "to": "date"})
    check("文本→日期", pd.api.types.is_datetime64_any_dtype(outd["日期"]), f"dtype={outd['日期'].dtype}")

    # ---- 5. pivot 长转宽 ----
    print("== [5] pivot wide ==")
    dfp = pd.DataFrame({
        "期间": ["Q1", "Q1", "Q2", "Q2"],
        "业务员": ["A", "B", "A", "B"],
        "回款": [100, 200, 150, 250],
    })
    outp, _ = _apply_pivot(dfp, {"op": "pivot", "mode": "wide",
                                 "index": "期间", "columns": "业务员", "values": "回款"})
    check("长转宽：4 行→2 行", len(outp) == 2, f"shape={outp.shape}")
    check("宽表含 A/B 列", "A" in outp.columns and "B" in outp.columns, str(list(outp.columns)))
    check("A/Q1=100", float(outp.loc[outp["期间"] == "Q1", "A"].iloc[0]) == 100, str(outp))

    # ---- 6. pivot 宽转长 ----
    print("== [6] pivot long ==")
    dfw = pd.DataFrame({"期间": ["Q1", "Q2"], "回款A": [100, 150], "回款B": [200, 250]})
    outl, _ = _apply_pivot(dfw, {"op": "pivot", "mode": "long",
                                 "id_vars": ["期间"], "var_name": "业务员", "value_name": "回款"})
    check("宽转长：2 行→4 行", len(outl) == 4, f"shape={outl.shape}")
    check("长表列名", list(outl.columns) == ["期间", "业务员", "回款"], str(list(outl.columns)))

    # ---- 7. 列类型推断 ----
    print("== [7] 列类型推断 ==")
    from tools.finmod_prep import run_prep_steps
    from types import SimpleNamespace

    class FakeStore:
        db = None
        def find_file_by_name(self, *a):
            return {"id": "f1"}
        def list_sheets(self, *a):
            import json as _json
            return [{"id": "s1", "file_id": "f1", "sheet_name": "Sheet1",
                     "sheet_index": 0, "table_name": "t1", "row_count": 3,
                     "col_count": 3,
                     "headers_json": _json.dumps([
                         {"name": "期间"}, {"name": "回款"}, {"name": "业务员"},
                     ])}]

    # 模拟 load_dataframe 返回固定 df
    import tools.finmod_prep as fp
    orig_load = fp.load_sheet
    test_df = pd.DataFrame({
        "期间": ["Q1", "Q2", "Q3"],
        "回款": [100, 200, 150],
        "业务员": ["A", "B", "A"],
    })
    fp.load_sheet = lambda store, pid, fn, sh: test_df.copy()
    try:
        res = run_prep_steps(FakeStore(), "p1", "f.xlsx", "Sheet1", [])
        check("无步骤成功", res["success"] is True and res["rows"] == 3, str(res))
        types = {c["name"]: c["type"] for c in res["columns"]}
        check("回款→numeric", types.get("回款") == "numeric", str(types))
        check("期间→text/category", types.get("期间") in ("text", "category"), str(types))
        check("业务员→category", types.get("业务员") == "category", str(types))
    finally:
        fp.load_sheet = orig_load

    # ---- 8. 步骤链叠加 + 日志 ----
    print("== [8] 步骤链 ==")
    fp.load_sheet = lambda store, pid, fn, sh: test_df.copy()  # 重新 mock（[7] finally 已恢复）
    try:
        res2 = run_prep_steps(FakeStore(), "p1", "f.xlsx", "Sheet1", [
            {"op": "clean", "action": "filter", "where": {"col": "回款", "op": "gte", "value": 150}},
            {"op": "cast", "col": "回款", "to": "numeric"},
        ])
    finally:
        fp.load_sheet = orig_load
    check("链式执行成功", res2["success"] and res2["rows"] == 2, str(res2.get("logs")))
    check("有 2 条日志", len(res2.get("logs") or []) == 2, str(res2.get("logs")))

    # ---- 9. prep-data 端点 + run 物化 ----
    print("== [9] prep-data 端点 + run ==")
    from app import create_app
    app = create_app(); c = app.test_client()
    pid = "80658bea48c74b16983c5a4c614376ad"
    r = c.post("/api/apps/finmod/prep-data", json={
        "project_id": pid, "file_name": "2025年1季度回款提成汇总表20250331-母公司.xls",
        "steps": [{"op": "clean", "action": "filter",
                   "where": {"col": "回款总额", "op": "gt", "value": 0}}],
    })
    d = (r.get_json() or {}).get("data") or {}
    check("prep-data 200", r.status_code == 200 and d.get("success") is True,
          str((r.get_json() or {}))[:200])
    check("prep 有列信息", len(d.get("columns") or []) > 0, str(d.get("columns"))[:100])
    # run 带 prep_steps + 统计量
    r2 = c.post("/api/apps/finmod/run", json={
        "project_id": pid, "file_name": "2025年1季度回款提成汇总表20250331-母公司.xls",
        "model_ids": ["g1-descriptive-stats"],
        "params": {}, "mappings": {"g1-descriptive-stats": {"x_i": "回款总额"}},
        "derived_formulas": ["x̄=MEAN(回款总额)", "n=COUNT(回款总额)"],
        "prep_steps": [{"op": "clean", "action": "filter",
                        "where": {"col": "回款总额", "op": "gt", "value": 0}}],
        "chart_manifest": [],
    })
    d2 = (r2.get_json() or {}).get("data") or {}
    check("run+prep 200", r2.status_code == 200 and len(d2.get("models") or []) == 1,
          str((r2.get_json() or {}))[:200])
    check("run 返回 prep_logs", len(d2.get("prep_logs") or []) == 1, str(d2.get("prep_logs")))

    # ---- 汇总 ----
    print("\n========================================")
    print(f"V3 数据预处理单测: PASS={PASS} FAIL={len(FAIL)}")
    for f in FAIL:
        print(f"  [FAIL] {f}")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
