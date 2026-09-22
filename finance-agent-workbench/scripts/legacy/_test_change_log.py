"""Phase 17 P5 集成验证：字段级修改日志（col_name/key_value）+ /changes 增强 + /list 角标。

运行: python scripts/_test_change_log.py
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import storage.db as sdb  # noqa: E402
_tmp = tempfile.mkdtemp(prefix="chglog_test_")
sdb.DB_PATH = os.path.join(_tmp, "test.db")

from app import create_app  # noqa: E402
from storage.project_store import ProjectStore  # noqa: E402
from tools.project_data_importer import ProjectDataImporter  # noqa: E402
from tools.project_data_tools import (  # noqa: E402
    export_project_data, update_rows, insert_rows, delete_rows)

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

        proj = ProjectStore(db).create("日志验证", work)
        imp = ProjectDataImporter(db)
        r = imp.import_workbook(proj["id"], "天箭.xls", work,
                                anchor_rows={"__all__": 2})
        fid = r["file_id"]

        # ── 1. update + insert + delete，生成日志 ──
        # 源文件可能已被此前测试写回，读取当前值构造必定不同的新值
        import xlrd
        rb0 = xlrd.open_workbook(dst)
        sh0 = rb0.sheet_by_name("汇总表")
        cur_val = next(
            (sh0.cell_value(row, 4) for row in range(sh0.nrows)
             if sh0.cell_value(row, 0) == "符雅峰"),
            0,
        )
        new_val = float(cur_val) + 11111
        upd = update_rows(file="天箭.xls", sheet="汇总表",
                          filters={"销售人员": "符雅峰"},
                          updates={"回款总额": new_val},
                          project_id=proj["id"], work_dir=work)
        check("update_rows", upd.get("success"), str(upd.get("message")))

        ins = insert_rows(file="天箭.xls", sheet="汇总表",
                          rows=[{"销售人员": "测试新人", "回款总额": 100, "备注": "P5测试"}],
                          project_id=proj["id"], work_dir=work)
        check("insert_rows", ins.get("success"), str(ins.get("message")))

        dele = delete_rows(file="天箭.xls", sheet="汇总表",
                           filters={"销售人员": "赵凌"},
                           project_id=proj["id"], work_dir=work)
        check("delete_rows", dele.get("success"), str(dele.get("message")))

        # ── 2. 直接查库：col_name/key_value 已固化 ──
        rows = db.execute(
            "SELECT op_type, col_name, key_value, col_index, row_index "
            "FROM project_data_changes WHERE file_id = ? ORDER BY id",
            (fid,),
        ).fetchall()
        check("日志已生成 ≥3 条", len(rows) >= 3, f"实际 {len(rows)} 条")
        update_logs = [dict(x) for x in rows if x["op_type"] == "update"]
        check("update 日志固化字段名 回款总额",
              update_logs and update_logs[0]["col_name"] == "回款总额",
              str(update_logs[0] if update_logs else None))
        check("update 日志固化行定位键 符雅峰",
              update_logs and update_logs[0]["key_value"] == "符雅峰",
              str(update_logs[0] if update_logs else None))
        insert_logs = [dict(x) for x in rows if x["op_type"] == "insert"]
        check("insert 日志固化行定位键 测试新人",
              insert_logs and insert_logs[0]["key_value"] == "测试新人",
              str(insert_logs[0] if insert_logs else None))
        delete_logs = [dict(x) for x in rows if x["op_type"] == "delete"]
        check("delete 日志固化行定位键 赵凌",
              delete_logs and delete_logs[0]["key_value"] == "赵凌",
              str(delete_logs[0] if delete_logs else None))
        # delete 的 col_index 应覆盖全列（headers 全列）
        check("delete 日志覆盖全部字段",
              delete_logs and all(d["col_name"] for d in delete_logs),
              f"delete 日志 {len(delete_logs)} 条")

        # ── 3. API 层验证：/changes 增强 ──
        client = app.test_client()
        resp = client.get(f"/api/project-data/{fid}/changes?limit=100")
        data = (resp.get_json() or {}).get("data") or {}
        check("GET /changes 200", resp.status_code == 200)
        summary = data.get("summary") or {}
        check("summary 统计", summary.get("total", 0) == len(rows)
              and summary.get("update") >= 1 and summary.get("insert") >= 1
              and summary.get("delete") >= 1, str(summary))
        chs = data.get("changes") or []        # excel_row 换算：表头第 3 行（0-based=2），符雅峰是第一个数据行
        # → Excel 行 = 2 + 1 + 1 = 4（第 4 行）；回款总额是第 5 列 → E
        upd_api = next((c for c in chs if c.get("op_type") == "update"
                        and c.get("col_name") == "回款总额"), None)
        check("update 日志带 Excel 物理行/列",
              upd_api and upd_api.get("excel_row") == 4
              and upd_api.get("excel_col") == "E",
              f"excel_row={upd_api and upd_api.get('excel_row')} "
              f"excel_col={upd_api and upd_api.get('excel_col')}")
        # 正序：第一条应是 update（先执行）
        check("日志正序（先 update）", (chs or [{}])[0].get("op_type") == "update",
              str((chs or [{}])[0].get("op_type")))

        # ── 4. API 层验证：/list 角标 ──
        resp2 = client.get(f"/api/project-data/list?project_id={proj['id']}")
        files = (resp2.get_json() or {}).get("data", {}).get("files") or []
        cc = files[0].get("changes_count") or {}
        check("list 带变更数角标", cc.get("total", 0) == len(rows)
              and cc.get("update") == summary.get("update")
              and cc.get("insert") == summary.get("insert")
              and cc.get("delete") == summary.get("delete"), str(cc))

        # ── 5. 写回仍正常（precise 按日志打补丁）──
        exp = export_project_data(file="天箭.xls", mode="precise",
                                  project_id=proj["id"], work_dir=work)
        check("precise 写回成功", exp.get("success"), exp.get("message", str(exp)))

        # ── 6. 过滤参数 ──
        resp3 = client.get(f"/api/project-data/{fid}/changes?op=delete")
        only_del = (resp3.get_json() or {}).get("data", {}).get("changes") or []
        check("op=delete 过滤", all(c["op_type"] == "delete" for c in only_del)
              and len(only_del) == len(delete_logs),
              f"{len(only_del)} 条 delete")

    print()
    if FAIL:
        print("FAILED:", FAIL)
        return 1
    print("ALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
