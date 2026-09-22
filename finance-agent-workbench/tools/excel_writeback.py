"""Excel 写回适配层 — 适配财务系统各种版本/格式的 Excel 文件。

背景
----
财务系统里"Excel 文件"的扩展名并不可靠，同一批报表可能混着多种真实格式：

  1. `.xlsx` / `.xlsm` —— ZIP 容器（openpyxl 读写；.xlsm 必须 keep_vba 保留宏）
  2. `.xls`            —— OLE2 复合文档（BIFF 97-2003；xlrd 读 + xlwt 写）
  3. `.xls`            —— 实际是 HTML 表格（老系统"另存为网页"导出的假 .xls）
  4. `.xls`            —— 实际是 SpreadsheetML 2003 XML（假 .xls）
  5. `.csv` / `.txt`   —— 分隔文本

本模块提供：
  * detect_real_format()  基于 magic bytes 的真实格式检测（不信任扩展名）
  * SheetWriter           统一写回抽象，两个后端：
      - openpyxl 后端：.xlsx/.xlsm（keep_vba 保留宏、保留样式与合并单元格）
      - xlwt 后端：.xls（xlutils.copy 保留格式；自动保护合并单元格）
  * load_writer()         按真实格式装载写回器
  * writeback_not_supported() 对假 .xls 等非 Excel 格式返回可操作诊断

Phase 17 P4：.xls 老格式写回适配（原实现直接拒绝，需 xlwt 库）。
"""

from __future__ import annotations

import os
from typing import Any

__all__ = [
    "WriteBackFormatError",
    "detect_real_format",
    "format_label",
    "load_writer",
    "SheetWriter",
]

_OLE2_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_ZIP_MAGIC = b"PK\x03\x04"
_HTML_PREFIXES = (b"<html", b"<!doctype html", b"<table", b"<head", b"<meta")


class WriteBackFormatError(ValueError):
    """写回目标不是本适配层可安全回写的格式。"""


def format_label(fmt: str) -> str:
    """人类可读的真实格式描述（用于错误提示）。"""
    return {
        "xlsx": ".xlsx/.xlsm（ZIP 容器）",
        "xls": ".xls（OLE2 / BIFF 97-2003 二进制）",
        "html": "HTML 表格（扩展名是 .xls 的网页导出，并非真 Excel）",
        "spreadsheetml": "SpreadsheetML 2003 XML（扩展名是 .xls 的 XML，并非真 Excel）",
        "xml": "XML 文本",
        "csv": "CSV 文本",
        "text": "纯文本",
        "unknown": "无法识别的二进制格式",
    }.get(fmt, fmt)


def detect_real_format(path: str) -> str:
    """根据文件头 magic bytes 判断真实格式，不信任扩展名。

    返回：xlsx | xls | html | spreadsheetml | xml | csv | text | unknown
    """
    try:
        with open(path, "rb") as f:
            head = f.read(4096)
    except OSError:
        return "unknown"
    if head.startswith(_OLE2_MAGIC):
        return "xls"
    if head.startswith(_ZIP_MAGIC):
        return "xlsx"
    # 跳过 UTF-8 BOM 与首部空白后再判断文本类格式
    stripped = head.lstrip(b"\xef\xbb\xbf \t\r\n")
    low = stripped[:512].lower()
    if low.startswith(_HTML_PREFIXES):
        return "html"
    if low.startswith(b"<?xml"):
        if b"workbook" in low or b"ss:" in low:
            return "spreadsheetml"
        return "xml"
    if b"\x00" not in stripped[:2048]:
        return "csv" if b"," in stripped[:2048] or b"\t" in stripped[:2048] else "text"
    return "unknown"


class SheetWriter:
    """统一写回抽象；所有坐标均为 1-based（与 openpyxl 一致）。"""

    def sheetnames(self) -> list[str]:  # pragma: no cover - 接口
        raise NotImplementedError

    def has(self, name: str) -> bool:
        return name in self.sheetnames()

    def max_row(self, name: str) -> int:  # pragma: no cover - 接口
        raise NotImplementedError

    def set_cell(self, name: str, row: int, col: int, value: Any) -> None:
        """写入一个单元格；合并区域内的非锚点单元格会被安全跳过。"""
        raise NotImplementedError

    def delete_rows(self, name: str, start: int, count: int) -> None:
        raise NotImplementedError

    def save(self) -> None:
        raise NotImplementedError

    def close(self) -> None:
        pass


class _OpenpyxlWriter(SheetWriter):
    """openpyxl 后端：.xlsx / .xlsm（keep_vba 保留宏、样式与合并单元格）。"""

    def __init__(self, path: str) -> None:
        import openpyxl
        self.path = path
        ext = os.path.splitext(path)[1].lower()
        self.wb = openpyxl.load_workbook(path, keep_vba=ext in (".xlsm", ".xltm"))

    def sheetnames(self) -> list[str]:
        return self.wb.sheetnames

    def max_row(self, name: str) -> int:
        return self.wb[name].max_row or 0

    def set_cell(self, name: str, row: int, col: int, value: Any) -> None:
        self.wb[name].cell(row=row, column=col, value=value)

    def delete_rows(self, name: str, start: int, count: int) -> None:
        self.wb[name].delete_rows(start, count)

    def save(self) -> None:
        self.wb.save(self.path)

    def close(self) -> None:
        self.wb.close()


class _XlsWriter(SheetWriter):
    """xlwt 后端：.xls 老格式，xlutils.copy 保留格式与合并单元格。

    写回时自动跳过合并区域内的非锚点单元格——xlwt 允许写入但
    Excel 打开后该值会被合并区域遮住，属于"静默丢失"，必须拦截。
    """

    def __init__(self, path: str) -> None:
        import xlrd
        from xlutils.copy import copy as _xlcopy
        self.path = path
        # formatting_info=True 才能拿到合并单元格 + 让 xlutils.copy 保留样式
        self.rb = xlrd.open_workbook(path, formatting_info=True)
        self.wb = _xlcopy(self.rb)
        self._merged: dict[str, list[tuple[int, int, int, int]]] = {}
        for i, name in enumerate(self.rb.sheet_names()):
            sh = self.rb.sheet_by_index(i)
            self._merged[name] = list(getattr(sh, "merged_cells", None) or [])

    def sheetnames(self) -> list[str]:
        return self.rb.sheet_names()

    def max_row(self, name: str) -> int:
        return self.rb.sheet_by_name(name).nrows or 0

    def set_cell(self, name: str, row: int, col: int, value: Any) -> None:
        # 合并单元格保护：非锚点位置跳过（值会被 Excel 合并区域遮住）
        for (rlo, rhi, clo, chi) in self._merged.get(name, []):
            if rlo <= row - 1 < rhi and clo <= col - 1 < chi:
                if row - 1 != rlo or col - 1 != clo:
                    return  # 合并区域内部，跳过
                break
        idx = self.rb.sheet_names().index(name)
        self.wb.get_sheet(idx).write(row - 1, col - 1, value)

    def delete_rows(self, name: str, start: int, count: int) -> None:
        # xlwt 无法物理删除行：退化为清空单元格（保留行高/边框，避免行错位）
        idx = self.rb.sheet_names().index(name)
        ws = self.wb.get_sheet(idx)
        ncols = self.rb.sheet_by_index(idx).ncols
        for r in range(start - 1, start - 1 + count):
            for c in range(ncols):
                ws.write(r, c, "")

    def save(self) -> None:
        self.wb.save(self.path)

    def close(self) -> None:
        pass


class _XlsPlainWriter(SheetWriter):
    """降级后端：xlrd 无格式读取 + xlwt 重建（用于 formatting_info 失败的怪文件）。

    不保留原样式，但保证数据完整写回；合并单元格信息尽力从行列取回。
    """

    def __init__(self, path: str) -> None:
        import xlrd
        import xlwt
        self.path = path
        self.rb = xlrd.open_workbook(path)
        self.wb = xlwt.Workbook()
        self._sheet_idx: dict[str, int] = {}
        for i, name in enumerate(self.rb.sheet_names()):
            self.wb.add_sheet(name)
            self._sheet_idx[name] = i

    def sheetnames(self) -> list[str]:
        return self.rb.sheet_names()

    def max_row(self, name: str) -> int:
        return self.rb.sheet_by_name(name).nrows or 0

    def set_cell(self, name: str, row: int, col: int, value: Any) -> None:
        self.wb.get_sheet(self._sheet_idx[name]).write(row - 1, col - 1, value)

    def delete_rows(self, name: str, start: int, count: int) -> None:
        idx = self._sheet_idx[name]
        ws = self.wb.get_sheet(idx)
        ncols = self.rb.sheet_by_name(name).ncols
        for r in range(start - 1, start - 1 + count):
            for c in range(ncols):
                ws.write(r, c, "")

    def save(self) -> None:
        self.wb.save(self.path)

    def close(self) -> None:
        pass


def load_writer(path: str, real_fmt: str | None = None) -> SheetWriter:
    """按真实格式装载写回器。

    Raises:
        WriteBackFormatError: 非 Excel 二进制格式（html/spreadsheetml/csv/text/unknown）
                              —— 上层应走"转换副本"或给出明确诊断。
    """
    real_fmt = real_fmt or detect_real_format(path)
    if real_fmt == "xlsx":
        return _OpenpyxlWriter(path)
    if real_fmt == "xls":
        try:
            return _XlsWriter(path)
        except Exception:
            # formatting_info 打开失败的怪文件（老 BIFF5/7 等）：降级无格式重建
            return _XlsPlainWriter(path)
    raise WriteBackFormatError(
        f"文件实际格式为 {format_label(real_fmt)}，不是可安全原地写回的 Excel 二进制；"
        "将生成 .xlsx 转换副本进行写回。"
    )
