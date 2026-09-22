"""Excel Tools — read/write/analyze Excel files via openpyxl.

Phase 8: Direct openpyxl operations for financial data processing.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from tools.file_lock import ensure_file_writable


def _resolve_path(path: str, work_dir: str, allow_outside: bool = False) -> str:
    """Resolve a path within work_dir, enforcing sandbox.

    allow_outside=True（全自动模式）：跳过边界检查，支持绝对路径。
    """
    if allow_outside:
        return os.path.abspath(path)
    work = Path(work_dir).resolve()
    full = (work / path).resolve()
    if not str(full).startswith(str(work) + os.sep) and str(full) != str(work):
        raise ValueError(f"路径超出工作目录范围: {path}")
    return str(full)


def _norm(v: Any) -> Any:
    """Normalize a cell value for JSON-safe output.

    Converts floats that are whole numbers to int, and datetime/date/time
    objects to ISO strings so json.dumps never fails downstream.
    """
    if isinstance(v, float) and v.is_integer():
        return int(v)
    if hasattr(v, "isoformat"):  # datetime / date / time
        return v.isoformat()
    return v


def read_excel(
    path: str,
    sheet: str = "",
    work_dir: str = "",
    range_spec: str = "",
    max_rows: int = 2000,
    allow_outside: bool = False,
) -> dict[str, Any]:
    """Read data from an Excel file (.xlsx via openpyxl, .xls via xlrd).

    Phase 17 P2: max_rows 默认 1000→2000（配合 range_spec 区域分块）。
    """
    try:
        import openpyxl
        if not work_dir:
            return {"success": False, "error": "未指定工作目录"}
        full_path = _resolve_path(path, work_dir, allow_outside=allow_outside)
        if not os.path.isfile(full_path):
            return {"success": False, "error": f"文件不存在: {path}"}

        ext = os.path.splitext(full_path)[1].lower()

        # ── Legacy .xls via xlrd ──
        if ext == ".xls":
            try:
                import xlrd
            except ImportError:
                return {"success": False,
                        "error": "读取 .xls 需要 xlrd，请运行: pip install xlrd"}
            return _read_xls(full_path, path, sheet, max_rows)

        wb = openpyxl.load_workbook(full_path, read_only=True, data_only=True)
        sheets = []
        for name in wb.sheetnames:
            ws = wb[name]
            sheets.append({
                "name": name, "index": wb.sheetnames.index(name),
                "row_count": ws.max_row or 0, "col_count": ws.max_column or 0,
            })

        if not sheet:
            wb.close()
            return {"success": True, "sheets": sheets, "data": [], "path": path}

        if sheet not in wb.sheetnames:
            wb.close()
            return {"success": False, "error": f"工作表不存在: {sheet}", "sheets": sheets}

        ws = wb[sheet]
        data = []
        headers = None
        row_count = 0
        for row in ws.iter_rows(values_only=True):
            if row_count >= max_rows:
                break
            row = [_norm(v) for v in row]
            if headers is None:
                headers = [str(c) if c is not None else f"Col{i}" for i, c in enumerate(row, 1)]
            else:
                data.append({headers[i]: v for i, v in enumerate(row) if i < len(headers)})
            row_count += 1

        wb.close()
        return {
            "success": True, "sheets": sheets, "data": data, "path": path,
            "headers": headers, "row_count": len(data), "truncated": row_count >= max_rows,
        }
    except ImportError:
        return {"success": False, "error": "openpyxl未安装，请运行: pip install openpyxl"}
    except ValueError as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        return {"success": False, "error": f"读取失败: {e}"}


def _read_xls(full_path: str, path: str, sheet: str = "", max_rows: int = 1000) -> dict[str, Any]:
    """Read a legacy .xls workbook via xlrd (Phase 8.1: .xls support)."""
    import xlrd
    wb = xlrd.open_workbook(full_path)
    sheets = []
    for i, name in enumerate(wb.sheet_names()):
        sh = wb.sheet_by_name(name)
        sheets.append({
            "name": name, "index": i,
            "row_count": sh.nrows, "col_count": sh.ncols,
        })

    if not sheet:
        return {"success": True, "sheets": sheets, "data": [], "path": path}

    if sheet not in wb.sheet_names():
        return {"success": False, "error": f"工作表不存在: {sheet}", "sheets": sheets}

    sh = wb.sheet_by_name(sheet)
    data = []
    headers = None
    row_count = 0
    for r in range(sh.nrows):
        if row_count >= max_rows:
            break
        row = [_norm(sh.cell_value(r, c)) for c in range(sh.ncols)]
        if headers is None:
            headers = [str(c) if c is not None else f"Col{i}" for i, c in enumerate(row, 1)]
        else:
            data.append({headers[i]: v for i, v in enumerate(row) if i < len(headers)})
        row_count += 1

    return {
        "success": True, "sheets": sheets, "data": data, "path": path,
        "headers": headers, "row_count": len(data), "truncated": row_count >= max_rows,
    }


def get_sheet_info(path: str, work_dir: str = "", allow_outside: bool = False) -> dict[str, Any]:
    """Get metadata about all sheets in an Excel workbook (.xlsx/.xls)."""
    try:
        import openpyxl
        if not work_dir:
            return {"success": False, "error": "未指定工作目录"}
        full_path = _resolve_path(path, work_dir, allow_outside=allow_outside)
        if not os.path.isfile(full_path):
            return {"success": False, "error": f"文件不存在: {path}"}

        ext = os.path.splitext(full_path)[1].lower()

        # Legacy .xls via xlrd
        if ext == ".xls":
            try:
                import xlrd
            except ImportError:
                return {"success": False,
                        "error": "读取 .xls 需要 xlrd，请运行: pip install xlrd"}
            wb = xlrd.open_workbook(full_path)
            sheets = []
            for i, name in enumerate(wb.sheet_names()):
                sh = wb.sheet_by_name(name)
                headers = []
                if sh.nrows > 0:
                    headers = [str(_norm(sh.cell_value(0, c))) if sh.cell_value(0, c) is not None else ""
                               for c in range(sh.ncols)]
                sheets.append({
                    "name": name, "index": i,
                    "row_count": sh.nrows, "col_count": sh.ncols,
                    "headers": headers,
                    "visible": True,
                })
            return {"success": True, "sheets": sheets, "path": path}

        wb = openpyxl.load_workbook(full_path, read_only=True, data_only=True)
        sheets = []
        for i, name in enumerate(wb.sheetnames):
            ws = wb[name]
            headers = []
            try:
                first_row = next(ws.iter_rows(min_row=1, max_row=1, values_only=True))
                headers = [str(c) if c is not None else "" for c in first_row]
            except StopIteration:
                pass
            sheets.append({
                "name": name, "index": i,
                "row_count": ws.max_row or 0, "col_count": ws.max_column or 0,
                "headers": headers,
                "visible": ws.sheet_state == "visible",
            })
        wb.close()
        return {"success": True, "sheets": sheets, "path": path}
    except ImportError:
        return {"success": False, "error": "openpyxl未安装"}
    except ValueError as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        return {"success": False, "error": f"读取失败: {e}"}


def write_excel(
    path: str,
    data: list[dict],
    sheet: str = "Sheet1",
    work_dir: str = "",
    allow_outside: bool = False,
) -> dict[str, Any]:
    """Write data to an Excel file."""
    try:
        import openpyxl
        from openpyxl.utils import get_column_letter
        if not work_dir:
            return {"success": False, "error": "未指定工作目录"}
        full_path = _resolve_path(path, work_dir, allow_outside=allow_outside)

        # Phase 17 P9：文件锁前置检测（Excel 打开时独占锁定，写入必败）
        if os.path.isfile(full_path):
            lock_err = ensure_file_writable(full_path)
            if lock_err:
                lock_err["path"] = path
                return lock_err

        if os.path.isfile(full_path):
            wb = openpyxl.load_workbook(full_path)
        else:
            wb = openpyxl.Workbook()

        if sheet in wb.sheetnames:
            ws = wb[sheet]
        else:
            ws = wb.active
            ws.title = sheet

        if not data:
            wb.save(full_path)
            wb.close()
            return {"success": True, "path": path, "rows_written": 0, "columns": []}

        columns = list(data[0].keys())
        for ci, col in enumerate(columns, 1):
            ws.cell(row=1, column=ci, value=col)
            ws.column_dimensions[get_column_letter(ci)].width = min(max(len(str(col)) * 1.3, 10), 40)

        for ri, row in enumerate(data, 2):
            for ci, col in enumerate(columns, 1):
                ws.cell(row=ri, column=ci, value=row.get(col))

        wb.save(full_path)
        wb.close()
        return {
            "success": True, "path": path, "rows_written": len(data),
            "columns": columns,
        }
    except ImportError:
        return {"success": False, "error": "openpyxl未安装"}
    except ValueError as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        return {"success": False, "error": f"写入失败: {e}"}


def analyze_excel(path: str, work_dir: str = "", allow_outside: bool = False) -> dict[str, Any]:
    """Analyze Excel file structure (.xlsx/.xls)."""
    try:
        import openpyxl
        if not work_dir:
            return {"success": False, "error": "未指定工作目录"}
        full_path = _resolve_path(path, work_dir, allow_outside=allow_outside)
        if not os.path.isfile(full_path):
            return {"success": False, "error": f"文件不存在: {path}"}

        ext = os.path.splitext(full_path)[1].lower()

        # Legacy .xls via xlrd
        if ext == ".xls":
            try:
                import xlrd
            except ImportError:
                return {"success": False,
                        "error": "读取 .xls 需要 xlrd，请运行: pip install xlrd"}
            wb = xlrd.open_workbook(full_path)
            sheets_analysis = []
            total_rows = 0
            key_fields = set()
            for name in wb.sheet_names():
                sh = wb.sheet_by_name(name)
                headers = []
                if sh.nrows > 0:
                    headers = [str(_norm(sh.cell_value(0, c))) if sh.cell_value(0, c) is not None else ""
                               for c in range(sh.ncols)]
                sample = []
                for r in range(1, min(sh.nrows, 10)):
                    sample.append([_norm(sh.cell_value(r, c)) for c in range(sh.ncols)])
                data_types = {}
                for hi, h in enumerate(headers):
                    types = set()
                    for row in sample:
                        val = row[hi] if hi < len(row) else None
                        if val is None:
                            types.add("None")
                        elif isinstance(val, (int, float)):
                            types.add("number")
                        else:
                            if any(kw in h.lower() for kw in ("id", "编号", "代码", "合同号", "合同")):
                                key_fields.add(h)
                            elif any(kw in h.lower() for kw in ("金额", "收入", "成本", "费用", "回款", "提成")):
                                key_fields.add(h)
                            elif any(kw in h.lower() for kw in ("日期", "时间")):
                                key_fields.add(h)
                            types.add("text")
                    data_types[h] = list(types) if types else ["unknown"]
                row_count = sh.nrows
                total_rows += row_count
                sheets_analysis.append({
                    "name": name, "headers": headers, "data_types": data_types,
                    "row_count": row_count, "col_count": sh.ncols,
                })
            return {
                "success": True,
                "summary": {
                    "sheet_count": len(wb.sheet_names()),
                    "total_rows": total_rows,
                    "key_fields_suggested": list(key_fields)[:10],
                },
                "sheets_analysis": sheets_analysis, "path": path,
            }

        wb = openpyxl.load_workbook(full_path, read_only=True, data_only=True)
        sheets_analysis = []
        total_rows = 0
        key_fields = set()
        sheet_names = list(wb.sheetnames)

        for name in sheet_names:
            ws = wb[name]
            headers = []
            data_types = {}
            try:
                first_row = next(ws.iter_rows(min_row=1, max_row=1, values_only=True))
                headers = [str(c) if c is not None else "" for c in first_row]
            except StopIteration:
                pass

            sample = []
            for row in ws.iter_rows(min_row=2, max_row=min(ws.max_row or 0, 10), values_only=True):
                sample.append(row)

            for hi, h in enumerate(headers):
                types = set()
                for row in sample:
                    val = row[hi] if hi < len(row) else None
                    if val is None:
                        types.add("None")
                    elif isinstance(val, (int, float)):
                        types.add("number")
                    elif isinstance(val, str):
                        if any(kw in h.lower() for kw in ("id", "编号", "代码", "合同号", "合同")):
                            key_fields.add(h)
                        elif any(kw in h.lower() for kw in ("金额", "收入", "成本", "费用", "回款", "提成")):
                            key_fields.add(h)
                        elif any(kw in h.lower() for kw in ("日期", "时间")):
                            key_fields.add(h)
                        types.add("text")
                    else:
                        types.add(type(val).__name__)
                data_types[h] = list(types) if types else ["unknown"]

            row_count = ws.max_row or 1
            total_rows += row_count
            sheets_analysis.append({
                "name": name, "headers": headers, "data_types": data_types,
                "row_count": row_count, "col_count": ws.max_column or 0,
            })

        wb.close()
        return {
            "success": True,
            "summary": {
                "sheet_count": len(sheet_names),
                "total_rows": total_rows,
                "key_fields_suggested": list(key_fields)[:10],
            },
            "sheets_analysis": sheets_analysis, "path": path,
        }
    except ImportError:
        return {"success": False, "error": "openpyxl未安装"}
    except ValueError as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        return {"success": False, "error": f"分析失败: {e}"}


def compare_excel_sheets(
    file1: str, sheet1: str,
    file2: str, sheet2: str,
    key_columns: list[str] | None = None,
    work_dir: str = "",
    allow_outside: bool = False,
) -> dict[str, Any]:
    """Compare two Excel sheets and return differences."""
    try:
        import openpyxl
        if not work_dir:
            return {"success": False, "error": "未指定工作目录"}
        fp1 = _resolve_path(file1, work_dir, allow_outside=allow_outside)
        fp2 = _resolve_path(file2, work_dir, allow_outside=allow_outside)

        wb1 = openpyxl.load_workbook(fp1, read_only=True, data_only=True)
        wb2 = openpyxl.load_workbook(fp2, read_only=True, data_only=True)

        ws1 = wb1[sheet1]
        ws2 = wb2[sheet2]

        def read_sheet(ws, keys):
            rows = {}
            headers = None
            for row in ws.iter_rows(values_only=True):
                row = [_norm(v) for v in row]
                if headers is None:
                    headers = [str(c) if c is not None else f"Col{i}" for i, c in enumerate(row, 1)]
                    if not keys:
                        keys = [h for h in headers if any(kw in h for kw in ("id", "ID", "编号", "代码", "合同", "序号"))]
                    if not keys and headers:
                        keys = [headers[0]]
                    continue
                d = {headers[i]: v for i, v in enumerate(row) if i < len(headers)}
                k = tuple(d.get(k, "") for k in keys)
                rows[k] = d
            return rows, keys, headers

        keys = key_columns
        rows1, keys, h1 = read_sheet(ws1, keys)
        rows2, _, h2 = read_sheet(ws2, keys)
        wb1.close()
        wb2.close()

        diffs = []
        matched = 0
        all_keys = set(rows1.keys()) | set(rows2.keys())
        compare_cols = [c for c in (set(h1) | set(h2)) if c not in (keys or [])]

        for k in all_keys:
            if k in rows1 and k in rows2:
                r1, r2 = rows1[k], rows2[k]
                all_same = True
                for col in compare_cols:
                    v1, v2 = r1.get(col), r2.get(col)
                    if str(v1) != str(v2):
                        diffs.append({
                            "type": "amount_mismatch", "key": str(k),
                            "field": col, "val1": str(v1), "val2": str(v2),
                        })
                        all_same = False
                if all_same:
                    matched += 1
            elif k in rows1:
                diffs.append({"type": "missing_in_target", "key": str(k), "source": str(rows1[k])})
            else:
                diffs.append({"type": "missing_in_source", "key": str(k), "source": str(rows2[k])})

        return {
            "success": True, "matched_count": matched, "diff_count": len(diffs),
            "diffs": diffs[:200],
            "only_in_file1": len([d for d in diffs if d["type"] == "missing_in_target"]),
            "only_in_file2": len([d for d in diffs if d["type"] == "missing_in_source"]),
            "summary": f"匹配{matched}条，差异{len(diffs)}条",
        }
    except ImportError:
        return {"success": False, "error": "openpyxl未安装"}
    except ValueError as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        return {"success": False, "error": f"对比失败: {e}"}
