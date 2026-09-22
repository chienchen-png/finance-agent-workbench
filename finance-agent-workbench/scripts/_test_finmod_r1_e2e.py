# -*- coding: utf-8 -*-
"""_test_finmod_r1_e2e — R1 多文件端到端（导入 2 文件 → 多文件变量映射/执行）。

覆盖：
  1. 创建项目 + 导入 radar.xlsx + 销售提成汇总表 → 2 个数据文件
  2. varmap 传 file_names[2] → 列索引并集 + files/file_of_col
  3. varmap-suggest 传 file_names[2] → 正常返回（LLM 不可用降级确定性）
  4. derived-eval 传 file_names[2] → 多文件合并求值
  5. run 传 file_names[2] → merge_strategy 非空 + models 产出
"""

import sys
import os

sys.path.insert(0, r"d:\Finance Recon Agent\finance-agent-workbench")
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

BASE = r"d:\Finance Recon Agent\finance-agent-workbench\data\app-workspaces\finmod"
F1 = os.path.join(BASE, "radar.xlsx")
F2 = os.path.join(BASE, "销售提成汇总表2021-2026 0722.xlsx")

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
    from app import create_app
    app = create_app()
    client = app.test_client()

    # ---- 0. 项目准备（app ctx 内建项目 + 导入 2 文件） ----
    print("== [0] 项目准备 ==")
    with app.app_context():
        from storage.db import get_db
        from storage.project_store import ProjectStore
        from storage.project_data_store import ProjectDataStore
        from tools.project_data_tools import import_excel_to_db
        db = get_db()
        proj_name = "__test_r1_multi__"
        ps = ProjectStore(db)
        existing = None
        for p in ps.get_all():
            if p.get("name") == proj_name:
                existing = p
                break
        if existing:
            pid = existing["id"]
        else:
            pid = ps.create(name=proj_name, work_dir=str(BASE),
                            default_model="deepseek", description="R1 多文件测试").get("id")
        print(f"  project id={pid}")
        # radar.xlsx 表头自动识别；销售表首 sheet「说明」无法识别，给 header_row=2（表头在第 2 行）
        for f in (F1, F2):
            hr = 2 if "销售提成" in os.path.basename(f) else None
            r = import_excel_to_db(f, header_row=hr, project_id=pid, work_dir=str(BASE))
            print(f"  import {os.path.basename(f)} → {str(r)[:120]}")
        pds = ProjectDataStore(db)
        fnames = [f["file_name"] for f in (pds.list_files(pid) or [])]
    print(f"  files={fnames}")
    check("项目已有 ≥2 数据文件", len(fnames) >= 2, str(fnames))
    if len(fnames) < 2:
        print("  [ABORT] 数据文件不足，无法测多文件")
        return 1

    # ---- 1. varmap 传 file_names[2] ----
    print("== [1] varmap file_names ==")
    vm = client.post("/api/apps/finmod/varmap", json={
        "project_id": pid, "file_names": fnames, "model_ids": ["d1-dupont"],
    })
    vmj = (vm.get_json() or {}).get("data") or {}
    print(f"  status={vm.status_code} all_cols={len(vmj.get('all_cols') or [])} "
          f"file_count={vmj.get('file_count')}")
    check("varmap 多文件成功", vm.status_code == 200 and len(vmj.get("all_cols") or []) > 0,
          str(vmj)[:200])
    check("varmap 返回 files", bool(vmj.get("files")) and len(vmj.get("files") or []) >= 2,
          str(vmj.get("files")))

    # ---- 2. varmap-suggest 传 file_names[2] ----
    print("== [2] varmap-suggest file_names ==")
    vs = client.post("/api/apps/finmod/varmap-suggest", json={
        "project_id": pid, "file_names": fnames, "model_ids": ["g1-descriptive-stats"],
        "model_id": "none",  # LLM 不可用 → 降级确定性
    })
    vsj = (vs.get_json() or {}).get("data") or {}
    print(f"  status={vs.status_code} used_llm={vsj.get('used_llm')} "
          f"models={len((vsj.get('varmap') or {}).get('models') or [])}")
    check("varmap-suggest 多文件成功", vs.status_code == 200 and vsj.get("varmap"), str(vsj)[:200])

    # ---- 3. derived-eval 传 file_names[2] ----
    print("== [3] derived-eval file_names ==")
    de = client.post("/api/apps/finmod/derived-eval", json={
        "project_id": pid, "file_names": fnames,
        "formulas": ["毛利率=(收入-成本)/收入"],
    })
    dej = (de.get_json() or {}).get("data") or {}
    print(f"  status={de.status_code} all_cols={len(dej.get('all_cols') or [])} "
          f"row_count={dej.get('row_count')}")
    check("derived-eval 多文件成功", de.status_code == 200 and dej.get("row_count", 0) >= 1,
          str(dej)[:200])

    # ---- 4. run 传 file_names[2]（多文件建模） ----
    print("== [4] run file_names ==")
    run = client.post("/api/apps/finmod/run", json={
        "project_id": pid, "file_names": fnames, "model_ids": ["g1-descriptive-stats"],
        "mappings": {}, "params": {}, "chart_manifest": [
            {"id": "c1", "template": "bar", "variant": "bar", "name": "收入对比",
             "level": "L2", "color_scheme": "auto"},
        ],
    })
    rj = (run.get_json() or {}).get("data") or {}
    print(f"  status={run.status_code} run_id={rj.get('run_id')} "
          f"models={len(rj.get('models') or [])} charts={len(rj.get('charts') or [])} "
          f"strategy={rj.get('merge_strategy')}")
    check("run 多文件成功", run.status_code == 200 and rj.get("run_id"), str(rj)[:200])
    check("run 合并策略非空", bool(rj.get("merge_strategy")), str(rj.get("merge_strategy")))
    check("run 返回 merge_logs", isinstance(rj.get("merge_logs"), list), str(rj.get("merge_logs")))
    check("run 产出模型结果", len(rj.get("models") or []) >= 1, str(rj.get("models"))[:200])

    print(f"\n== 结果：PASS={PASS}，FAIL={len(FAIL)} ==")
    for f in FAIL:
        print(f"  [FAIL] {f}")

    # ---- 5. 清理测试项目（防止 __test_r1_multi__ 污染主库项目列表） ----
    print("== [5] 清理测试项目 ==")
    try:
        with app.app_context():
            from storage.db import get_db
            from storage.project_store import ProjectStore
            from storage.project_data_store import ProjectDataStore
            db = get_db()
            pstore = ProjectStore(db)
            pdstore = ProjectDataStore(db)
            for p in pstore.get_all():
                if p.get("name") == proj_name:
                    for f in (pdstore.list_files(p["id"]) or []):
                        pdstore.delete_file(f["id"])
                    pstore.delete(p["id"])
                    print(f"  已清理测试项目 {proj_name} ({p['id']})")
                    break
    except Exception as exc:
        print(f"  清理失败（不影响测试结果）：{exc}")

    return 0 if not FAIL else 1


if __name__ == "__main__":
    sys.exit(main())
