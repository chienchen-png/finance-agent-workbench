# -*- coding: utf-8 -*-
"""_test_preview_d1 — 文件预览 D1 后端格式映射 + D4 导出验收测试。

用法：python scripts/_test_preview_d1.py
覆盖（设计方案 §七 7.1 + D1/D4 验收标准）：
  1. _viewer_type(".xls") == "xlsx"（.xls 归一化补齐，之前落入 unsupported）
  2. 5 类 office 后缀（docx/xlsx/xls/ppt/pptx）can_open_external == True
  3. pdf can_open_external == True（保留 external 能力，双击走浏览器预览由前端分发）
  4. markdown/text/image viewer_type 正确 + can_open_external == False
  5. POST /api/files/open-external 对 docx 返回 opened=True（mock os.startfile）
  6. open-external 对非 office 文件返回 400
  7. D4 POST /api/files/export-docx：md → docx（PK 头/文件名/mimetype）
  8. export-docx content 优先 / 缺参 400 / 非 md 415 / 不存在 404 / pandoc 缺失 501
"""

import os
import sys
import tempfile
from pathlib import Path
from unittest import mock

sys.path.insert(0, r"d:\Finance Recon Agent\finance-agent-workbench")
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

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


def _mk_test_app(db_path: str):
    """用临时 DB 构建 Flask app（真实 schema + 会话钩子）。

    与 _test_dashboard_d2 同款隔离：patch storage.db / config.settings /
    storage.session_store 三处 DB_PATH（模块导入期绑定），进程结束前不恢复。
    """
    import app as app_module
    import config.settings as settings
    import storage.db as sdb
    import storage.session_store as ss
    sdb.DB_PATH = db_path  # type: ignore
    settings.DB_PATH = db_path  # type: ignore
    ss.DB_PATH = db_path  # type: ignore
    return app_module.create_app()


def main() -> int:
    # ---------------------------------------------------------------
    # 准备临时 DB：完整 schema + 一个测试项目（work_dir 指向临时目录）
    # ---------------------------------------------------------------
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    import sqlite3
    schema = Path(r"d:\Finance Recon Agent\finance-agent-workbench\storage\schema.sql")
    conn = sqlite3.connect(db_path)
    conn.executescript(schema.read_text(encoding="utf-8"))

    work_dir = tempfile.mkdtemp(prefix="d1_workdir_")
    now = "2026-08-24T00:00:00+00:00"
    conn.execute(
        "INSERT INTO projects (id, name, work_dir, created_at, updated_at) "
        "VALUES ('p1', 'D1测试项目', ?, ?, ?)", (work_dir, now, now))
    conn.commit()
    conn.close()

    flask_app = _mk_test_app(db_path)

    # ---------------------------------------------------------------
    # 1. _viewer_type 映射（.xls 归一化）
    # ---------------------------------------------------------------
    print("== 1. _viewer_type 映射 ==")
    import routes.files as files_mod

    def vt(suffix: str) -> str:
        return files_mod._viewer_type(Path(f"dummy{suffix}"))

    check("_viewer_type(.md)==markdown", vt(".md") == "markdown")
    check("_viewer_type(.markdown)==markdown", vt(".markdown") == "markdown")
    check("_viewer_type(.txt)==text", vt(".txt") == "text")
    check("_viewer_type(.docx)==docx", vt(".docx") == "docx")
    check("_viewer_type(.xlsx)==xlsx", vt(".xlsx") == "xlsx")
    check("_viewer_type(.xls)==xlsx（归一化补齐）", vt(".xls") == "xlsx", vt(".xls"))
    check("_viewer_type(.ppt)==ppt", vt(".ppt") == "ppt")
    check("_viewer_type(.pptx)==pptx", vt(".pptx") == "pptx")
    check("_viewer_type(.pdf)==pdf", vt(".pdf") == "pdf")
    check("_viewer_type(.png)==image", vt(".png") == "image")
    check("_viewer_type(.unknown)==unsupported", vt(".xyz") == "unsupported")

    # ---------------------------------------------------------------
    # 2. can_open_external 白名单（5 类 office + pdf）
    # ---------------------------------------------------------------
    print("== 2. can_open_external 白名单 ==")
    office = {".docx": "docx", ".xlsx": "xlsx", ".xls": "xlsx", ".ppt": "ppt", ".pptx": "pptx"}
    for suffix, expected_vt in office.items():
        root = Path(work_dir)
        target = root / f"f{suffix}"
        target.write_bytes(b"dummy")
        meta = files_mod._meta_payload(root, target)
        check(f"can_open_external({suffix})=True", meta.get("can_open_external") is True,
              str(meta))
        check(f"viewer_type({suffix})=={expected_vt}", meta.get("viewer_type") == expected_vt,
              str(meta.get("viewer_type")))

    # pdf 保留 external（右键场景）
    target = Path(work_dir) / "f.pdf"
    target.write_bytes(b"%PDF-1.4 dummy")
    meta = files_mod._meta_payload(Path(work_dir), target)
    check("can_open_external(pdf)=True（保留外部打开能力）", meta.get("can_open_external") is True,
          str(meta))

    # markdown / text / image 不可 external
    for suffix in (".md", ".txt", ".png"):
        t2 = Path(work_dir) / f"g{suffix}"
        t2.write_bytes(b"x" if suffix != ".png" else b"\x89PNG\r\n\x1a\n")
        meta = files_mod._meta_payload(Path(work_dir), t2)
        check(f"can_open_external({suffix})=False", meta.get("can_open_external") is False,
              str(meta))

    # ---------------------------------------------------------------
    # 3. POST /api/files/open-external 端点（mock os.startfile）
    # ---------------------------------------------------------------
    print("== 3. open-external 端点 ==")
    client = flask_app.test_client()

    def _open(path: str):
        return client.post("/api/files/open-external",
                           json={"project_id": "p1", "path": path})

    # docx → opened=True（startfile 被调用）
    (Path(work_dir) / "报告.docx").write_bytes(b"dummy docx")
    with mock.patch("routes.files.os.startfile") as sf:
        resp = _open("报告.docx")
    data = resp.get_json()
    check("open-external(docx) HTTP 200", resp.status_code == 200, str(resp.status_code))
    check("open-external(docx) opened=True", (data or {}).get("data", {}).get("opened") is True,
          str(data))
    check("os.startfile 被调用 1 次", sf.call_count == 1, str(sf.call_count))
    # Windows 路径大小写不敏感：mkdtemp 返回 C:\WINDOWS\TEMP，resolve 后为
    # C:\Windows\Temp——比较时两边 resolve + casefold
    expected_path = str((Path(work_dir).resolve() / "报告.docx")).casefold()
    check("startfile 路径=work_dir/报告.docx",
          str(sf.call_args.args[0]).casefold() == expected_path,
          f"got={sf.call_args!r} expect={expected_path}")

    # xls → opened=True（归一化后仍可 external）
    (Path(work_dir) / "老表.xls").write_bytes(b"dummy xls")
    with mock.patch("routes.files.os.startfile") as sf:
        resp = _open("老表.xls")
    data = resp.get_json()
    check("open-external(xls) HTTP 200", resp.status_code == 200, str(resp.status_code))
    check("open-external(xls) opened=True", (data or {}).get("data", {}).get("opened") is True,
          str(data))
    check("startfile 调用（xls）", sf.call_count == 1)

    # md → 400（不支持外部打开，走软件内编辑器）
    (Path(work_dir) / "说明.md").write_text("# 说明", encoding="utf-8")
    resp = _open("说明.md")
    check("open-external(md) HTTP 400", resp.status_code == 400, str(resp.status_code))

    # 不存在的文件 → 404
    resp = _open("不存在.docx")
    check("open-external(不存在) HTTP 404", resp.status_code == 404, str(resp.status_code))

    # 越权路径 → 400（_resolve_inside 拒绝）
    resp = client.post("/api/files/open-external",
                       json={"project_id": "p1", "path": "../outside.docx"})
    check("open-external(越权) HTTP 400", resp.status_code == 400, str(resp.status_code))

    # ---------------------------------------------------------------
    # 4. D4 export-docx（Markdown → Word）
    # ---------------------------------------------------------------
    print("== 4. export-docx（Markdown → Word） ==")
    import routes.files as files_mod4
    _pandoc = files_mod4._find_pandoc()
    check("Pandoc 探测（离线介质/PATH）", _pandoc is not None and Path(_pandoc).is_file(),
          str(_pandoc))

    # 4.1 有效导出（文件源）
    (Path(work_dir) / "导出.md").write_text(
        "# 财务报告\n\n| 项 | 值 |\n|---|---|\n| A | 1 |\n\n$$x^2$$\n",
        encoding="utf-8")
    resp = client.post("/api/files/export-docx",
                       json={"project_id": "p1", "path": "导出.md"})
    check("export-docx HTTP 200", resp.status_code == 200, str(resp.status_code))
    docx_bytes = resp.data
    check("export-docx 返回 docx（PK 头）", docx_bytes[:2] == b"PK",
          str(docx_bytes[:8]))
    disp = resp.headers.get("Content-Disposition", "")
    # Flask 对非 ASCII 文件名：filename 回退 ASCII，filename* 提供 UTF-8（RFC 5987）——
    # 浏览器下载时正确使用 filename*。断言检查 UTF-8 编码的「导出.docx」。
    check("export-docx 文件名=导出.docx（filename*）",
          "filename*=UTF-8''%E5%AF%BC%E5%87%BA.docx" in disp, disp)
    check("export-docx mimetype=docx",
          "openxmlformats-officedocument.wordprocessingml" in
          resp.headers.get("Content-Type", ""), resp.headers.get("Content-Type", ""))

    # 4.2 content 优先（未保存内容导出）
    resp = client.post("/api/files/export-docx",
                       json={"project_id": "p1", "path": "导出.md",
                             "content": "# 新内容\n\n- [x] 已编辑"})
    check("export-docx(content) HTTP 200", resp.status_code == 200, str(resp.status_code))
    check("export-docx(content) PK 头", resp.data[:2] == b"PK")

    # 4.3 参数缺失 → 400
    resp = client.post("/api/files/export-docx", json={"project_id": "p1"})
    check("export-docx(缺 path) HTTP 400", resp.status_code == 400, str(resp.status_code))

    # 4.4 非 md 文件 → 415
    (Path(work_dir) / "表格.xlsx").write_bytes(b"PK\x03\x04 xlsx")
    resp = client.post("/api/files/export-docx",
                       json={"project_id": "p1", "path": "表格.xlsx"})
    check("export-docx(xlsx) HTTP 415", resp.status_code == 415, str(resp.status_code))

    # 4.5 文件不存在 → 404
    resp = client.post("/api/files/export-docx",
                       json={"project_id": "p1", "path": "不存在.md"})
    check("export-docx(不存在) HTTP 404", resp.status_code == 404, str(resp.status_code))

    # 4.6 pandoc 缺失 → 501（mock _find_pandoc 返回 None）
    with mock.patch("routes.files._find_pandoc", return_value=None):
        resp = client.post("/api/files/export-docx",
                           json={"project_id": "p1", "path": "导出.md"})
    check("export-docx(pandoc 缺失) HTTP 501", resp.status_code == 501, str(resp.status_code))
    msg = (resp.get_json() or {}).get("message", "")
    check("501 错误含 Pandoc 提示", "Pandoc" in msg, msg)

    # ---------------------------------------------------------------
    # 汇总
    # ---------------------------------------------------------------
    print(f"\n结果: {PASS} 通过, {len(FAIL)} 失败")
    for f in FAIL:
        print(f"  FAIL: {f}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
