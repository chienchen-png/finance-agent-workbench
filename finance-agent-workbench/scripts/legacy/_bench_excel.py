"""自研 Excel 工具性能基准（真实文件）。

对比对象：GitHub nordeim/excel-agent-tools（53 CLI）——它本身也是 openpyxl 底层。
本脚本实测自研工具链路：读 .xlsx/.xls / 导入数据平面 / 精确写回 / 格式检测。
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import storage.db as sdb
import tempfile
sdb.DB_PATH = os.path.join(tempfile.mkdtemp(), "bench.db")

from app import create_app
from storage.project_store import ProjectStore
from tools.project_data_importer import ProjectDataImporter
from tools.project_data_tools import (export_project_data, update_rows,
                                      query_table)
from tools.excel_tools import read_excel, get_sheet_info, compare_excel_sheets

XLSX = os.path.join("test-fixtures", "phase5", "待处理数据",
                    "销售提成汇总表2021-2026 0722.xlsx")   # 2031 行 × 34 列
XLS = os.path.join("test-fixtures", "phase5", "待处理数据",
                   "2025年4季度回款提成汇总表20251231-天箭.xls")  # 10 sheet


def bench(label, fn):
    t0 = time.perf_counter()
    r = fn()
    dt = (time.perf_counter() - t0) * 1000
    print(f"{label:<42} {dt:>8.1f} ms")
    return r, dt


app = create_app()
with app.app_context():
    from storage.db import get_db
    db = get_db()

    print("=" * 64)
    print("读取基准（test-fixtures 真实文件）")
    print("=" * 64)

    # 1. 读 .xlsx（2031 行 × 34 列 全表）
    bench("read_excel .xlsx 全表(2031×34)", lambda: read_excel(
        XLSX, sheet="汇总表", work_dir=".", max_rows=5000))
    # 2. 读 .xls（10 sheet 元数据）
    bench("read_excel .xls 元数据(10 sheet)", lambda: read_excel(
        XLS, work_dir="."))
    # 3. 读取 sheet 信息
    bench("get_sheet_info .xlsx", lambda: get_sheet_info(XLSX, "."))
    # 4. 对比两 sheet
    bench("compare_excel_sheets", lambda: compare_excel_sheets(
        XLSX, "汇总表", XLSX, "2024年", "."))

    print()
    print("=" * 64)
    print("数据平面链路基准（导入→查询→改→写回）")
    print("=" * 64)

    work = tempfile.mkdtemp()
    import shutil
    dst = os.path.join(work, "总表.xlsx")
    shutil.copy2(os.path.join("test-fixtures", "phase5", "待处理数据",
                              "销售提成汇总表2021-2026 0722.xlsx"), dst)
    proj = ProjectStore(db).create("bench", work)
    imp = ProjectDataImporter(db)

    # 5. 导入（读+表头检测+建表+入库）
    _, t5 = bench("import_workbook .xlsx 2031行", lambda: imp.import_workbook(
        proj["id"], "总表.xlsx", work))
    fid = imp.import_workbook(proj["id"], "总表.xlsx", work)["file_id"]

    # 6. 库内查询
    bench("query_table(limit=2000)", lambda: query_table(
        file="总表.xlsx", sheet="汇总表", columns=["序号", "销售客户", "合同编号"],
        limit=2000, project_id=proj["id"], work_dir=work))

    # 7. 造 100 条更新
    t7 = time.perf_counter()
    for i in range(1, 101):
        update_rows(file="总表.xlsx", sheet="汇总表",
                    filters={"序号": i}, updates={"提成比例": 0.01 + i / 100000},
                    project_id=proj["id"], work_dir=work)
    print(f"{'update_rows ×100 条':<42} {(time.perf_counter()-t7)*1000:>8.1f} ms")

    # 8. 精确写回 100 处
    bench("export_project_data precise(100处)", lambda: export_project_data(
        file="总表.xlsx", mode="precise", project_id=proj["id"], work_dir=work))

    # 9. .xls 写回基准
    dst2 = os.path.join(work, "天箭.xls")
    shutil.copy2(os.path.join("test-fixtures", "phase5", "待处理数据",
                              "2025年4季度回款提成汇总表20251231-天箭.xls"), dst2)
    imp2 = ProjectDataImporter(db)
    imp2.import_workbook(proj["id"], "天箭.xls", work, anchor_rows={"__all__": 2})
    r9, t9 = bench("import_workbook .xls(10sheet)", lambda: imp2.import_workbook(
        proj["id"], "天箭.xls", work, anchor_rows={"__all__": 2}))
    # 造 10 条日志再写回
    for i, name in enumerate(["符雅峰", "赵凌", "余振兴", "郭洋", "周现伟",
                              "李立", "刘吉", "张尚志", "杜元伟", "汇总表"]):
        key_col = "姓名" if name != "汇总表" else "销售人员"
        sheet = "汇总表" if name == "汇总表" else name
        update_rows(file="天箭.xls", sheet=sheet,
                    filters={key_col: "符雅峰" if name == "汇总表" else "符雅峰"},
                    updates={"回款总额": 1}, project_id=proj["id"], work_dir=work)
    bench("export .xls precise(10处)", lambda: export_project_data(
        file="天箭.xls", mode="precise", project_id=proj["id"], work_dir=work))

    print()
    print("完成")
