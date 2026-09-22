# -*- coding: utf-8 -*-
"""_test_finmod_p6 — P6 报告交付后端单测（save-chart / 静态代理 / export-md）。

用法：python scripts/_test_finmod_p6.py
依赖：启动 app.py 之前可直接用 test_client 测；LLM 不可用时 export-md 降级确定性报告。
"""

import sys
import os

sys.path.insert(0, r"d:\Finance Recon Agent\finance-agent-workbench")
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

from app import create_app  # noqa: E402

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
    app = create_app()
    client = app.test_client()

    # ---- 0. 先跑一次 run 拿到 run_id + charts ----
    # 直接造一个最小 run：先上传数据到项目 → run
    # 为简单，这里先构造 run 所需的最小输入：project_id + file_name + model_ids
    # 通过 run 端点（复用已有数据文件）
    print("== [0] run 前置准备 ==")
    # 查找可用项目（test-fixtures 或已存在项目）
    proj_resp = client.get("/api/projects")
    print(f"  projects status={proj_resp.status_code}")
    projects = proj_resp.get_json() or {}
    proj_list = projects.get("projects") or projects.get("data") or []
    if not proj_list:
        print("  [WARN] 无项目，跳过 run 前置（只测 save-chart/export-md 直接调用）")
    else:
        pid = proj_list[0]["id"]
        # 找项目下第一个数据文件
        files_resp = client.get(f"/api/projects/{pid}/files")
        files = (files_resp.get_json() or {}).get("files") or []
        if files:
            fid = files[0]
            run_resp = client.post("/api/apps/finmod/run", json={
                "project_id": pid,
                "file_name": fid,
                "model_ids": ["a1"],
                "params": {},
                "manifest": [{"id": "c1", "template": "line", "name": "收入趋势",
                              "level": "L2", "color_scheme": "auto"}],
                "mappings": {},
            })
            run_json = run_resp.get_json() or {}
            print(f"  run status={run_resp.status_code} run_id={run_json.get('run_id')} "
                  f"models={len(run_json.get('models') or [])} charts={len(run_json.get('charts') or [])}")
            check("run 可执行", run_resp.status_code == 200 and run_json.get("run_id"), str(run_json)[:200])
            run_id = run_json.get("run_id") or "testrun0000000000000000"
        else:
            run_id = "testrun0000000000000000"
            print("  [WARN] 无数据文件，使用伪 run_id 测 save-chart")
    # 若无 run，手动注册一个伪 run 也行——但 save-chart 不校验注册表，只校验目录

    # ---- 1. save-chart：SVG 落盘 ----
    print("== [1] save-chart SVG ==")
    svg = '<svg xmlns="http://www.w3.org/2000/svg" width="800" height="500"><rect width="100%" height="100%" fill="white"/></svg>'
    resp = client.post("/api/apps/finmod/save-chart", json={
        "run_id": run_id, "filename": "图1_收入趋势.svg", "content": svg, "format": "svg",
    })
    j = (resp.get_json() or {}).get("data") or {}
    print(f"  status={resp.status_code} -> {j}")
    check("save-chart SVG 成功", resp.status_code == 200 and j.get("rel_path", "").startswith("assets/"),
          str(j))
    check("save-chart 返回 path", bool(j.get("path")) and os.path.isfile(j.get("path")), str(j))
    saved_path = j.get("path") or ""

    # ---- 2. save-chart：PNG base64 ----
    print("== [2] save-chart PNG ==")
    import base64
    png_b64 = base64.b64encode(b"\x89PNG\r\n\x1a\nfake").decode()
    resp2 = client.post("/api/apps/finmod/save-chart", json={
        "run_id": run_id, "filename": "图3d.png", "content": png_b64, "format": "png",
    })
    j2 = (resp2.get_json() or {}).get("data") or {}
    print(f"  status={resp2.status_code} -> {j2}")
    check("save-chart PNG 成功", resp2.status_code == 200 and j2.get("rel_path", "").endswith(".png"),
          str(j2))

    # ---- 3. 路径穿越防护 ----
    print("== [3] 路径穿越防护 ==")
    resp3 = client.post("/api/apps/finmod/save-chart", json={
        "run_id": run_id, "filename": "../../evil.svg", "content": svg, "format": "svg",
    })
    j3 = (resp3.get_json() or {}).get("data") or {}
    print(f"  status={resp3.status_code} -> {j3}")
    check("路径穿越被拦截/不越界", not (j3.get("path") or "").replace("\\", "/").count("/.."),
          str(j3))

    # ---- 4. 静态代理 ----
    print("== [4] 静态代理 ==")
    if saved_path:
        fname = os.path.basename(saved_path)
        proxy = client.get(f"/api/apps/finmod/files/{run_id}/assets/{fname}")
        print(f"  GET assets/{fname} status={proxy.status_code} ct={proxy.content_type}")
        check("静态代理 200", proxy.status_code == 200, str(proxy.status_code))
        check("静态代理内容为 SVG", b"<svg" in proxy.data, "")
        # 不存在的文件 → 404
        nf = client.get(f"/api/apps/finmod/files/{run_id}/assets/no_such_file.svg")
        check("静态代理 404", nf.status_code == 404, str(nf.status_code))

    # ---- 5. export-md（LLM 不可用 → 降级确定性报告）----
    print("== [5] export-md ==")
    resp5 = client.post("/api/apps/finmod/export-md", json={
        "project_id": "p1", "run_id": run_id, "goal": "分析企业收入与成本结构",
        "model_id": "none",  # 触发降级
        "models": [
            {"code": "a1", "name": "收入增长率", "ok": True, "summary": {"收入增长率": "25%"}},
        ],
        "charts": [
            {"chart_id": "c1", "name": "收入趋势", "template": "line",
             "rel_path": "assets/图1_收入趋势.svg"},
        ],
    })
    j5 = (resp5.get_json() or {}).get("data") or {}
    print(f"  status={resp5.status_code} used_llm={j5.get('used_llm')} path={j5.get('path')}")
    check("export-md 成功", resp5.status_code == 200 and j5.get("path"), str(j5)[:200])
    check("export-md 降级报告含图表引用",
          "assets/图1_收入趋势.svg" in (j5.get("report") or ""), str(j5.get("report"))[:200])
    check("export-md 落盘文件存在", bool(j5.get("path")) and os.path.isfile(j5.get("path")), str(j5.get("path")))

    # ---- 结果汇总 ----
    print("\n========================================")
    print(f"P6 后端单测: PASS={PASS} FAIL={len(FAIL)}")
    for f in FAIL:
        print(f"  [FAIL] {f}")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
