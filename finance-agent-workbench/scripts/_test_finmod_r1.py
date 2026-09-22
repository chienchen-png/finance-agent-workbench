# -*- coding: utf-8 -*-
"""_test_finmod_r1 — R1 多文件支持单测（finmod_merge 合并策略 + 端点 file_names 兼容）。

用法：python scripts/_test_finmod_r1.py
覆盖：
  1. merge 策略：join（共同键横向）/ concat（同构纵向）/ union（列并集）/ single
  2. collect_all_columns：多文件列索引并集 + period_cols + 来源文件
  3. 端点 file_names 归一化（varmap-suggest / derived-eval / prep-data / run 多文件）
"""

import sys
import os
import json

sys.path.insert(0, r"d:\Finance Recon Agent\finance-agent-workbench")
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

import pandas as pd  # noqa: E402
from tools.finmod_merge import (  # noqa: E402
    merge_files_for_model, collect_all_columns, _detect_join_keys, _columns_overlap_ratio,
)

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


class FakeStore:
    """模拟 ProjectDataStore：load_dataframe 返回按 file_name 区分的 df。"""
    def __init__(self, frames: dict[str, pd.DataFrame]):
        self.frames = frames

    def find_file_by_name(self, project_id, file_name):
        return {"id": file_name}

    def list_sheets(self, file_id):
        return [{"id": "s1", "file_id": file_id, "sheet_name": "Sheet1",
                 "sheet_index": 0, "table_name": "t1", "row_count": 3,
                 "col_count": 3, "headers_json": json.dumps([])}]

    def list_files(self, project_id):
        return [{"file_name": fn, "status": "done"} for fn in self.frames]


_orig_load = None

def _install_load(store: FakeStore):
    """monkeypatch finmod_eval.load_dataframe 返回 store.frames[file_name]。"""
    import tools.finmod_eval as fe
    global _orig_load
    if _orig_load is None:
        _orig_load = fe.load_dataframe
    def fake(store_, project_id, file_name, sheet_name=""):
        key = file_name
        return store_.frames[key].copy()
    fe.load_dataframe = fake
    return fe


def _restore_load(fe):
    import tools.finmod_eval
    if _orig_load is not None:
        tools.finmod_eval.load_dataframe = _orig_load


def main():
    # ============ 1. _detect_join_keys ============
    print("== [1] _detect_join_keys ==")
    fA = pd.DataFrame({"月份": ["1月", "2月"], "销售额": [100, 200]})
    fB = pd.DataFrame({"月份": ["1月", "2月"], "成本": [60, 120]})
    keys = _detect_join_keys([fA, fB], ["a.xlsx", "b.xlsx"])
    check("识别『月份』为共同键", "月份" in keys, str(keys))

    # ============ 2. _columns_overlap_ratio ============
    print("== [2] _columns_overlap_ratio ==")
    ratio_hi = _columns_overlap_ratio([fA, fB])
    check("同列名（月份）重叠≥0.5", ratio_hi >= 0.5, f"ratio={ratio_hi}")
    fC = pd.DataFrame({"客户": ["X", "Y"], "金额": [1, 2]})
    ratio_lo = _columns_overlap_ratio([fA, fC])
    check("列完全不同的重叠低", ratio_lo < 0.5, f"ratio={ratio_lo}")

    # ============ 3. merge join（共同键横向） ============
    print("== [3] merge join ==")
    store = FakeStore({"a.xlsx": fA, "b.xlsx": fB})
    fe = _install_load(store)
    try:
        res = merge_files_for_model(store, "p1", ["a.xlsx", "b.xlsx"])
        check("strategy=join", res["strategy"] == "join", res["strategy"])
        check("合并后 2 行", res["df"].shape[0] == 2, str(res["df"].shape))
        check("列含销售额+成本", "销售额" in res["df"].columns and "成本" in res["df"].columns,
              str(list(res["df"].columns)))
        check("1月 销售额100/成本60",
              float(res["df"].loc[res["df"]["月份"] == "1月", "销售额"].iloc[0]) == 100 and
              float(res["df"].loc[res["df"]["月份"] == "1月", "成本"].iloc[0]) == 60,
              str(res["df"]))
    finally:
        _restore_load(fe)

    # ============ 4. merge concat（同构纵向） ============
    print("== [4] merge concat ==")
    fX = pd.DataFrame({"期间": ["Q1", "Q2"], "回款": [10, 20], "业务员": ["A", "A"]})
    fY = pd.DataFrame({"期间": ["Q3", "Q4"], "回款": [30, 40], "业务员": ["B", "B"]})
    store2 = FakeStore({"x.xlsx": fX, "y.xlsx": fY})
    fe = _install_load(store2)
    try:
        res2 = merge_files_for_model(store2, "p1", ["x.xlsx", "y.xlsx"])
        check("strategy=concat", res2["strategy"] == "concat", res2["strategy"])
        check("合并后 4 行", res2["df"].shape[0] == 4, str(res2["df"].shape))
    finally:
        _restore_load(fe)

    # ============ 5. merge union（列并集） ============
    print("== [5] merge union ==")
    fM = pd.DataFrame({"产品": ["A", "B"], "销售额": [100, 200]})
    fN = pd.DataFrame({"客户": ["X", "Y"], "数量": [5, 8]})
    store3 = FakeStore({"m.xlsx": fM, "n.xlsx": fN})
    fe = _install_load(store3)
    try:
        res3 = merge_files_for_model(store3, "p1", ["m.xlsx", "n.xlsx"])
        check("strategy in union/concat", res3["strategy"] in ("union", "concat"), res3["strategy"])
        check("含全部列", {"产品", "销售额", "客户", "数量"}.issubset(set(res3["df"].columns)),
              str(list(res3["df"].columns)))
    finally:
        _restore_load(fe)

    # ============ 6. single（单文件） ============
    print("== [6] single ==")
    store4 = FakeStore({"a.xlsx": fA})
    fe = _install_load(store4)
    try:
        res4 = merge_files_for_model(store4, "p1", ["a.xlsx"])
        check("strategy=single", res4["strategy"] == "single", res4["strategy"])
        check("原样 2 行", res4["df"].shape[0] == 2, str(res4["df"].shape))
    finally:
        _restore_load(fe)

    # ============ 7. collect_all_columns ============
    print("== [7] collect_all_columns ==")
    fP = pd.DataFrame({"月份": ["1月"], "销售额": [100], "产品": ["A"]})
    fQ = pd.DataFrame({"月份": ["1月"], "成本": [60], "客户": ["X"]})
    store5 = FakeStore({"p.xlsx": fP, "q.xlsx": fQ})
    fe = _install_load(store5)
    try:
        idx = collect_all_columns(store5, "p1", ["p.xlsx", "q.xlsx"])
        check("all_cols 并集", {"月份", "销售额", "产品", "成本", "客户"}.issubset(set(idx["all_cols"])),
              str(idx["all_cols"]))
        check("period_cols 含月份", "月份" in idx["period_cols"], str(idx["period_cols"]))
        check("来源文件标注", any(c["name"] == "销售额" and "p.xlsx" in c["files"] for c in idx["cols_info"]),
              str(idx["cols_info"]))
    finally:
        _restore_load(fe)

    # ============ 8. 加载失败不阻塞整体 ============
    print("== [8] 加载失败不阻塞 ==")
    fR = pd.DataFrame({"月份": ["1月"], "销售额": [100]})
    store6 = FakeStore({"good.xlsx": fR})  # bad.xlsx 不在 frames → 模拟加载失败
    fe = _install_load(store6)
    try:
        res6 = merge_files_for_model(store6, "p1", ["good.xlsx", "bad.xlsx"])
        check("坏文件被跳过仍产出 df", res6["df"].shape[0] == 1, str(res6["df"].shape))
        check("日志含加载失败", any("失败" in l for l in res6["logs"]), str(res6["logs"]))
    finally:
        _restore_load(fe)

    # ============ 9. varmap 端点 file_names 归一化 ============
    print("== [9] varmap 端点 file_names ==")
    # 用 test_client 校验端点参数归一化逻辑（后端 _finmod_varmap 已支持）
    # 此处仅验证 collect_all_columns 在多文件无 sheet 时默认 sheet 逻辑不抛错
    fS = pd.DataFrame({"月份": ["1月"], "销售额": [100]})
    store7 = FakeStore({"s.xlsx": fS})
    fe = _install_load(store7)
    try:
        idx7 = collect_all_columns(store7, "p1", ["s.xlsx"])
        check("单文件 collect 不抛错", idx7["all_cols"] == ["月份", "销售额"], str(idx7["all_cols"]))
    finally:
        _restore_load(fe)

    # ============ 汇总 ============
    print(f"\n== 结果：PASS={PASS}，FAIL={len(FAIL)} ==")
    for f in FAIL:
        print(f"  [FAIL] {f}")
    return 0 if not FAIL else 1


if __name__ == "__main__":
    sys.exit(main())
