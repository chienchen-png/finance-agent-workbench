"""Phase 17 P4 集成验证：.xls 老格式完整链路 导入→修改→写回→校验。

用独立临时数据库，不污染开发库 data/app.db。
运行: python scripts/_test_xls_writeback.py
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import storage.db as sdb  # noqa: E402

# 独立临时数据库
_tmp = tempfile.mkdtemp(prefix="xls_wb_test_")
sdb.DB_PATH = os.path.join(_tmp, "test.db")

from app import create_app  # noqa: E402
from storage.project_store import ProjectStore  # noqa: E402
from tools.project_data_importer import (  # noqa: E402
    NeedAnchorError, ProjectDataImporter)
from tools.project_data_tools import export_project_data, update_rows  # noqa: E402

SRC = os.path.join(ROOT, "test-fixtures", "phase5", "待处理数据",
                   "2025年4季度回款提成汇总表20251231-天箭.xls")

FAIL = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(("✅" if ok else "❌"), label, detail)
    if not ok:
        FAIL.append(label)


def main() -> int:
    app = create_app()
    with app.app_context():
        from storage.db import get_db
        db = get_db()

        # ── 1. 工作目录 + 复制源 .xls ──
        work = os.path.join(_tmp, "work")
        rel_dir = os.path.join("待处理数据")
        os.makedirs(os.path.join(work, rel_dir), exist_ok=True)
        dst = os.path.join(work, rel_dir, os.path.basename(SRC))
        shutil.copy2(SRC, dst)

        # ── 2. 建项目 + 导入（表头行 = 第 3 行，索引 2）──
        proj = ProjectStore(db).create("xls写回验证", work)
        imp = ProjectDataImporter(db)
        try:
            result = imp.import_workbook(proj["id"], os.path.join(rel_dir, os.path.basename(SRC)),
                                         work, anchor_rows={"__all__": 2})
        except NeedAnchorError as e:
            print("⚠ 需锚点:", list(e.layouts))
            result = imp.import_workbook(proj["id"], os.path.join(rel_dir, os.path.basename(SRC)),
                                         work, anchor_rows={"__all__": 2})
        file_id = result["file_id"]
        sheets = result["sheets"]
        check("导入 .xls 成功（10 个 sheet）", len(sheets) == 10,
              f"实际 {len(sheets)} 个: {[s['sheet_name'] for s in sheets]}")

        # 打印汇总表 headers，确定真实列名
        from storage.project_data_store import ProjectDataStore
        store = ProjectDataStore(db)
        sheet_recs = store.list_sheets(file_id)
        sum_sheet = next(s for s in sheet_recs if s["sheet_name"] == "汇总表")
        headers = [h["name"] for h in (sum_sheet.get("headers") or [])]
        print("  汇总表列名:", headers)

        # ── 3. 修改：符雅峰 的回款总额 → 888888 ──
        col_name = "回款总额" if "回款总额" in headers else headers[4]
        upd = update_rows(file=os.path.basename(SRC), sheet="汇总表",
                          filters={"销售人员": "符雅峰"},
                          updates={col_name: 888888},
                          project_id=proj["id"], work_dir=work)
        check("update_rows 修改数据", upd.get("success"), str(upd))
        matched = upd.get("matched", 0)

        # ── 4. template 模式写回 .xls ──
        exp = export_project_data(file=os.path.basename(SRC), mode="template",
                                  project_id=proj["id"], work_dir=work)
        check("template 模式写回成功", exp.get("success"), exp.get("message", str(exp)))
        check("写回格式识别为 xls", exp.get("format") == "xls", str(exp.get("format")))
        # 本项目不设置备份：写回后不应产生 .bak 文件
        baks = [f for f in os.listdir(os.path.join(work, rel_dir))
                if f.startswith(os.path.basename(SRC)) and ".bak." in f]
        check("写回不产生 .bak 备份", len(baks) == 0, f"baks={baks}")

        # ── 5. 校验写回结果（xlrd 重读）──
        import xlrd
        rb = xlrd.open_workbook(dst)
        check("sheet 结构保留", rb.sheet_names() == [s["sheet_name"] for s in sheets],
              str(rb.sheet_names()))
        sh = rb.sheet_by_name("汇总表")
        found = False
        for r in range(sh.nrows):
            if sh.cell_value(r, 0) == "符雅峰":
                for c in range(sh.ncols):
                    if sh.cell_value(2, c) == col_name:  # 表头行找列
                        val = sh.cell_value(r, c)
                        found = True
                        check(f"符雅峰 的 {col_name} 已写回", float(val) == 888888.0, f"值={val}")
        check("找到被改行", found)
        # 合并单元格保留（表头标题行/制表日期行通常有合并）
        rb2 = xlrd.open_workbook(dst, formatting_info=True)
        merged = rb2.sheet_by_name("汇总表").merged_cells
        check("合并单元格保留", len(merged) > 0, f"merged={merged}")
        print("  .xls 写回后大小:", os.path.getsize(dst), "bytes")

        # ── 6. precise 模式写回（依赖 change log）──
        exp2 = export_project_data(file=os.path.basename(SRC), mode="precise",
                                   project_id=proj["id"], work_dir=work)
        check("precise 模式写回成功", exp2.get("success"), exp2.get("message", str(exp2)))
        rb3 = xlrd.open_workbook(dst)
        sh3 = rb3.sheet_by_name("汇总表")
        try:
            col_idx = next(c for c in range(sh3.ncols)
                           if sh3.cell_value(2, c) == col_name)
        except StopIteration:
            col_idx = headers.index(col_name)
        ok2 = any(sh3.cell_value(r, 0) == "符雅峰" and
                  sh3.cell_value(r, col_idx) == 888888
                  for r in range(sh3.nrows))
        check("precise 写回后数据仍在", ok2)

    print()
    if FAIL:
        print(f"❌ {len(FAIL)} 项失败: {FAIL}")
        return 1
    print("✅ 全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
