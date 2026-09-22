"""Phase 17 P7 集成验证：异步写回任务 + 进度轮询 + 贴边框进度数据。

运行: python scripts/_test_export_progress.py
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import storage.db as sdb  # noqa: E402
_tmp = tempfile.mkdtemp(prefix="exp_prog_")
sdb.DB_PATH = os.path.join(_tmp, "test.db")

from app import create_app  # noqa: E402
from storage.project_store import ProjectStore  # noqa: E402
from tools.project_data_importer import ProjectDataImporter  # noqa: E402
from tools.project_data_tools import update_rows  # noqa: E402

SRC = os.path.join(ROOT, "test-fixtures", "phase5", "待处理数据",
                   "2025年4季度回款提成汇总表20251231-天箭.xls")
FAIL = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(("PASS" if ok else "FAIL"), label, detail)
    if not ok:
        FAIL.append(label)


def main() -> int:
    app = create_app()
    with app.app_context():
        from storage.db import get_db
        db = get_db()
        work = os.path.join(_tmp, "work")
        os.makedirs(work, exist_ok=True)
        dst = os.path.join(work, "天箭.xls")
        shutil.copy2(SRC, dst)

        proj = ProjectStore(db).create("进度验证", work)
        imp = ProjectDataImporter(db)
        r = imp.import_workbook(proj["id"], "天箭.xls", work,
                                anchor_rows={"__all__": 2})
        fid = r["file_id"]

        # 造 3 条 update 日志（动态值避免同值跳过）
        import xlrd
        rb0 = xlrd.open_workbook(dst)
        sh0 = rb0.sheet_by_name("汇总表")
        for row in range(sh0.nrows):
            if sh0.cell_value(row, 0) in ("符雅峰", "赵凌", "余振兴"):
                cur = float(sh0.cell_value(row, 4))
                upd = update_rows(file="天箭.xls", sheet="汇总表",
                                  filters={"销售人员": sh0.cell_value(row, 0)},
                                  updates={"回款总额": cur + 100},
                                  project_id=proj["id"], work_dir=work)
                check(f"造日志 {sh0.cell_value(row, 0)}", upd.get("success"))
        print("  日志总数:", db.execute(
            "SELECT COUNT(*) FROM project_data_changes WHERE file_id=?",
            (fid,)).fetchone()[0])

        # ── 1. POST /export 立即返回 export_id ──
        client = app.test_client()
        resp = client.post("/api/project-data/export", json={
            "project_id": proj["id"], "file": "天箭.xls", "mode": "precise",
        })
        data = (resp.get_json() or {}).get("data") or {}
        check("POST /export 立即返回 export_id", resp.status_code == 200
              and data.get("export_id"), str(data))

        # ── 2. 轮询 /export/status，观察进度单调上升 → done ──
        export_id = data["export_id"]
        seen: list[float] = []
        final = None
        for _ in range(40):
            st = client.get(f"/api/project-data/export/status?export_id={export_id}")
            body = (st.get_json() or {}).get("data") or {}
            if body.get("status") == "running":
                seen.append(body.get("progress", 0))
                time.sleep(0.05)
                continue
            final = body
            break
        check("任务完成 done", final and final.get("status") == "done",
              str(final))
        check("进度单调不减", all(b >= a for a, b in zip(seen, seen[1:])),
              f"进度序列 {seen}")
        check("有中间进度上报", len(seen) >= 2 or final.get("progress") == 100,
              f"seen={len(seen)}")
        check("written_cells ≥ 3", (final or {}).get("written_cells", 0) >= 3,
              str(final and final.get("written_cells")))
        check("message 含回写", "回写" in (final or {}).get("message", ""),
              str(final and final.get("message"))[:80])

        # ── 3. 失败场景：不存在的文件 ──
        resp2 = client.post("/api/project-data/export", json={
            "project_id": proj["id"], "file": "不存在.xls", "mode": "precise",
        })
        exp2 = (resp2.get_json() or {}).get("data", {}).get("export_id")
        time.sleep(0.5)
        st2 = client.get(f"/api/project-data/export/status?export_id={exp2}")
        b2 = (st2.get_json() or {}).get("data") or {}
        check("失败场景 status=failed", b2.get("status") == "failed",
              str(b2.get("error")))

        # ── 4. 直接调用 export_project_data（progress 回调同步验证）──
        from tools.project_data_tools import export_project_data
        steps: list[tuple[float, str]] = []

        def cb(p: float, msg: str) -> None:
            steps.append((p, msg))

        result = export_project_data(file="天箭.xls", mode="precise",
                                     project_id=proj["id"], work_dir=work,
                                     progress=cb)
        check("同步调用带 progress 仍成功", result.get("success"))
        check("进度回调被调用且末值 100", bool(steps) and steps[-1][0] == 100,
              f"回调 {len(steps)} 次，末值 {steps[-1][0] if steps else '?'}")

    print()
    if FAIL:
        print("FAILED:", FAIL)
        return 1
    print("ALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
