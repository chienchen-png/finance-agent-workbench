"""Phase 17 P9 集成验证：文件锁检测（file_locked 结构化错误）。

Windows 上用独占打开模拟"文件被占用"，验证：
  1. is_file_locked 层1（~$ 锁文件）
  2. is_file_locked 层2（独占打开 PermissionError）
  3. ensure_file_writable 返回结构化错误
  4. write_file / write_excel / export_project_data 接入检测

运行: python scripts/_test_file_lock.py
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import storage.db as sdb  # noqa: E402
_tmp = tempfile.mkdtemp(prefix="flock_")
sdb.DB_PATH = os.path.join(_tmp, "test.db")

from app import create_app  # noqa: E402
from storage.project_store import ProjectStore  # noqa: E402
from tools.project_data_importer import ProjectDataImporter  # noqa: E402
from tools.file_lock import is_file_locked, ensure_file_writable  # noqa: E402

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

        # ── 1. 层1：~$ 锁文件检测 ──
        xlsx = os.path.join(work, "报表.xlsx")
        with open(xlsx, "w") as f:
            f.write("test")
        # 模拟 Excel 打开：创建 ~$ 锁文件
        lockf = os.path.join(work, "~$报表.xlsx")
        with open(lockf, "w") as f:
            f.write("")
        locked, reason = is_file_locked(xlsx)
        check("层1 ~$ 锁文件检测", locked and "Office" in reason, reason)

        # 删除锁文件后正常
        os.remove(lockf)
        locked2, _ = is_file_locked(xlsx)
        check("删除锁文件后未锁定", not locked2)

        # ── 2. 层2：独占打开模拟占用（Windows 语义）──
        txt = os.path.join(work, "说明.txt")
        with open(txt, "w") as f:
            f.write("data")
        handle = open(txt, "r+b")  # 独占写锁（Windows）
        try:
            locked3, reason3 = is_file_locked(txt)
            check("层2 独占打开检测到占用", locked3, reason3)
            # ensure_file_writable 返回结构化错误
            err = ensure_file_writable(txt)
            check("ensure_file_writable 返回结构化错误",
                  err and err.get("error_type") == "file_locked"
                  and "关闭" in (err.get("error") or ""),
                  str(err and err.get("error")))
            check("错误含 hint", err and "hint" in err, str(err and err.get("hint")))
        finally:
            handle.close()
        # 释放后正常
        err2 = ensure_file_writable(txt)
        check("释放后 ensure_file_writable 返回 None", err2 is None)

        # ── 3. write_file 接入检测 ──
        handle2 = open(txt, "r+b")
        try:
            from tools.filesystem_tools import write_file
            r = write_file(path="说明.txt", content="new", work_dir=work)
            check("write_file 返回 file_locked",
                  not r.get("success") and r.get("error_type") == "file_locked",
                  str(r.get("error")))
        finally:
            handle2.close()

        # ── 4. export_project_data 接入检测（数据文件被占用）──
        src = os.path.join(ROOT, "test-fixtures", "phase5", "待处理数据",
                           "2025年4季度回款提成汇总表20251231-天箭.xls")
        dst = os.path.join(work, "天箭.xls")
        shutil.copy2(src, dst)
        proj = ProjectStore(db).create("锁验证", work)
        imp = ProjectDataImporter(db)
        r = imp.import_workbook(proj["id"], "天箭.xls", work,
                                anchor_rows={"__all__": 2})
        # 造 1 条日志
        import xlrd
        rb0 = xlrd.open_workbook(dst)
        sh0 = rb0.sheet_by_name("汇总表")
        for row in range(sh0.nrows):
            if sh0.cell_value(row, 0) == "符雅峰":
                cur = float(sh0.cell_value(row, 4))
                break
        from tools.project_data_tools import update_rows
        upd = update_rows(file="天箭.xls", sheet="汇总表",
                          filters={"销售人员": "符雅峰"},
                          updates={"回款总额": cur + 5},
                          project_id=proj["id"], work_dir=work)
        check("造日志", upd.get("success"))

        # 独占打开源文件 → 写回应返回 file_locked
        handle3 = open(dst, "r+b")
        try:
            from tools.project_data_tools import export_project_data
            exp = export_project_data(file="天箭.xls", mode="precise",
                                      project_id=proj["id"], work_dir=work)
            check("export_project_data 返回 file_locked",
                  not exp.get("success") and exp.get("error_type") == "file_locked",
                  str(exp.get("error")))
        finally:
            handle3.close()

        # 释放后写回成功
        exp2 = export_project_data(file="天箭.xls", mode="precise",
                                   project_id=proj["id"], work_dir=work)
        check("释放后写回成功", exp2.get("success"), str(exp2.get("message"))[:40])

    print()
    if FAIL:
        print("FAILED:", FAIL)
        return 1
    print("ALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
