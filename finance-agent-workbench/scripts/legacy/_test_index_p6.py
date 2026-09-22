"""Phase 17 P6 集成验证：索引接口增强（excel_col/表头行）+ 导入器跳空行（G1）。

运行: python scripts/_test_index_p6.py
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
_tmp = tempfile.mkdtemp(prefix="index_p6_")
sdb.DB_PATH = os.path.join(_tmp, "test.db")

from app import create_app  # noqa: E402
from storage.project_store import ProjectStore  # noqa: E402
from tools.project_data_importer import ProjectDataImporter  # noqa: E402

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

        proj = ProjectStore(db).create("索引验证", work)
        imp = ProjectDataImporter(db)
        r = imp.import_workbook(proj["id"], "天箭.xls", work,
                                anchor_rows={"__all__": 2})
        fid = r["file_id"]
        check("导入成功（10 sheet）", len(r["sheets"]) == 10,
              f"实际 {len(r['sheets'])}")

        # ── 1. index 接口增强 ──
        client = app.test_client()
        resp = client.get(f"/api/project-data/{fid}/index")
        data = (resp.get_json() or {}).get("data") or {}
        check("GET /index 200", resp.status_code == 200)

        sheets = data.get("sheets") or []
        sum_sheet = next(s for s in sheets if s["sheet_name"] == "汇总表")
        headers = sum_sheet.get("headers") or []
        check("每个字段带 excel_col 列字母",
              all("excel_col" in h for h in headers),
              f"前3列: {[h.get('excel_col') for h in headers[:3]]}")
        check("excel_col 从 A 开始", headers[0].get("excel_col") == "A"
              and headers[4].get("excel_col") == "E",
              f"A/E 校验: {headers[0].get('excel_col')}/{headers[4].get('excel_col')}")

        layouts = ((data.get("file") or {}).get("meta") or {}).get("layouts") or {}
        lay = layouts.get("汇总表") or {}
        check("layouts 带 1-based excel_header_row",
              lay.get("excel_header_row") == 3,
              f"汇总表表头行={lay.get('excel_header_row')}（原始 header_row={lay.get('header_row')}）")
        check("layouts 带 data_start_row",
              lay.get("data_start_row") == 4, str(lay.get("data_start_row")))

        # ── 2. G1：数据区中部空行被跳过 ──
        # 构造含中部空行的 xlsx：2 行数据 + 空行 + 2 行数据
        import openpyxl
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "S1"
        ws.append(["姓名", "金额"])
        ws.append(["张三", 100])
        ws.append([None, None])  # 中部空行（视觉分隔）
        ws.append([None, None])
        ws.append(["李四", 200])
        ws.append(["王五", 300])
        p2 = os.path.join(work, "空行测试.xlsx")
        wb.save(p2)
        wb.close()

        r2 = imp.import_workbook(proj["id"], "空行测试.xlsx", work)
        fid2 = r2["file_id"]
        recs = db.execute(
            "SELECT row_count FROM project_data_sheets WHERE file_id = ?",
            (fid2,),
        ).fetchall()
        check("中部空行被跳过（3 行数据而非 5）",
              recs and recs[0]["row_count"] == 3,
              f"row_count={recs[0]['row_count'] if recs else '?'}")

        # 数据内容校验：无 null 行
        tbl = db.execute(
            "SELECT table_name FROM project_data_sheets WHERE file_id = ? LIMIT 1",
            (fid2,),
        ).fetchone()["table_name"]
        rows = db.execute(f'SELECT * FROM "{tbl}" ORDER BY id').fetchall()
        check("数据行均为有效内容",
              len(rows) == 3 and all(r["姓名"] for r in rows),
              str([r["姓名"] for r in rows]))

    print()
    if FAIL:
        print("FAILED:", FAIL)
        return 1
    print("ALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
