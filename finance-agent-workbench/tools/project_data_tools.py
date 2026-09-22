"""Project data plane tools — Phase 14B/14C.

Phase 14B: import_excel_to_db / query_table / table_stats operate on the
SQLite project data plane (never on raw Excel files). Data stays in the
DB; only result subsets are returned to the LLM context (PRD §3.12.6).

Phase 14C: update_rows / insert_rows / delete_rows make parameterized,
cell-level changes with a full change log (project_data_changes);
export_project_data materializes the data plane back to Excel in two
modes (template rebuild / precise write-back).

Security:
  - table_name comes from project_data_sheets (always data_<file_id>_<idx>).
  - Column names are validated against the imported headers whitelist
    before being embedded in SQL; filter/update values are always
    parameterized.
"""

from __future__ import annotations

import os
from typing import Any, Callable

from storage.db import get_db
from storage.project_data_store import ProjectDataStore
from tools.excel_writeback import (detect_real_format, format_label,
                                   load_writer)
from tools.file_lock import ensure_file_writable
# Cap query results so a large table never floods the LLM context.
# Phase 17 P2: 500→5000（上万行处理，配合 aggregate 聚合控制返回量）
QUERY_LIMIT_CAP = 5000
# Aggregation functions allowed in table_stats.
AGG_FUNCS = {"sum", "avg", "count", "min", "max"}
# Write-back modes for export_project_data.
EXPORT_MODES = {"template", "precise"}


def _store() -> tuple[ProjectDataStore, Any]:
    db = get_db()
    return ProjectDataStore(db), db


def _file_and_sheet(store: ProjectDataStore, project_id: str,
                    file: str, sheet: str) -> tuple[dict, dict | None]:
    """Resolve file + sheet records from user-supplied names.

    Returns (file_rec, sheet_rec); raises ValueError with a readable
    message when not found.
    """
    file_rec = store.find_file_by_name(project_id, file)
    if not file_rec:
        raise ValueError(f"项目数据库中未找到数据文件「{file}」；请先导入")
    sheets = store.list_sheets(file_rec["id"])
    if not sheets:
        raise ValueError(f"数据文件「{file_rec['file_name']}」没有分表")
    if not sheet:
        return file_rec, sheets[0]
    for s in sheets:
        if s["sheet_name"] == sheet:
            return file_rec, s
    raise ValueError(
        f"工作表「{sheet}」不存在；可用: {', '.join(s['sheet_name'] for s in sheets)}"
    )


def _valid_columns(sheet: dict) -> dict[str, str]:
    """Map validated column name → logical type from headers whitelist."""
    mapping: dict[str, str] = {}
    for h in sheet.get("headers") or []:
        mapping[h["name"]] = h.get("type", "text")
    return mapping


def _quote(name: str) -> str:
    """Double-quote an already-validated identifier."""
    return f'"{name}"'


def _change_log(store: ProjectDataStore, file_id: str, sheet_name: str,
                row_index: int, op_type: str,
                columns: list[str], old_values: dict | None = None,
                new_values: dict | None = None,
                sheet_headers: list[str] | None = None,
                key_value: str = "") -> None:
    """Write cell-level change log entries for one data row.

    col_index is the column's position in the FULL header list (sheet_headers),
    not an index inside `columns` — precise write-back needs absolute columns.
    Phase 17 P5：col_name 固化字段名、key_value 固化行定位键（主键列值），
    日志自描述到字段级，展示/写回不再依赖数据表反查。
    """
    for col in columns:
        old_v = (old_values or {}).get(col)
        new_v = (new_values or {}).get(col)
        if op_type == "update" and old_v == new_v:
            continue  # unchanged cell — no log noise
        col_index = None
        if sheet_headers and col in sheet_headers:
            col_index = sheet_headers.index(col)
        store.log_change(
            file_id=file_id, sheet_name=sheet_name, row_index=row_index,
            op_type=op_type, col_index=col_index, col_name=str(col),
            key_value=key_value,
            old_value=old_v, new_value=new_v,
        )


def import_excel_to_db(path: str, header_row: int | None = None,
                       project_id: str = "", work_dir: str = "") -> dict[str, Any]:
    """Import an Excel workbook into the project data plane.

    header_row: optional 1-based row number of the variable-name row, e.g.
    the LLM may first get a needs_anchor response, ask the user which row
    contains the headers, then retry with header_row=<N>.

    Returns a short confirmation ("已导入，含 N 个分表，M 行") so the LLM
    can immediately start querying via query_table / table_stats.
    """
    try:
        if not project_id:
            return {"success": False, "error": "未指定项目"}
        if not work_dir:
            return {"success": False, "error": "未指定工作目录"}
        from tools.project_data_importer import (
            NeedAnchorError, ProjectDataImporter,
        )
        db = get_db()
        # A single header_row from the LLM applies to every sheet that
        # needed a manual anchor (most financial files share one layout).
        anchor_rows = None
        if header_row is not None:
            try:
                hr = int(header_row)
                anchor_rows = {"__all__": hr}  # placeholder, resolved below
            except (TypeError, ValueError):
                return {"success": False, "error": "header_row 必须是整数（行号，从 1 开始）"}
        importer = ProjectDataImporter(db)
        try:
            result = importer.import_workbook(
                project_id, path, work_dir, anchor_rows=anchor_rows
            )
        except NeedAnchorError as exc:
            if header_row is None:
                # Ask the LLM to clarify with the user, then retry.
                sheets = [s for s in (exc.layouts or {})
                          if not exc.layouts[s].is_confident]
                return {
                    "success": False,
                    "needs_anchor": True,
                    "message": (
                        "无法自动识别数据表头所在行。请用 ask_user 询问用户"
                        "「变量名（表头）在第几行？」（从 1 开始），"
                        f"需要确认的工作表：{', '.join(sheets)}"
                    ),
                }
            # Retry with the user-confirmed anchor on every ambiguous sheet.
            hr = int(header_row) - 1  # 1-based user input → 0-based index
            ambiguous = {name: lay for name, lay in exc.layouts.items()
                         if not lay.is_confident}
            anchor_rows = {name: hr for name in ambiguous}
            result = importer.import_workbook(
                project_id, path, work_dir, anchor_rows=anchor_rows
            )
        if result.get("reused"):
            return {
                "success": True,
                "message": f"数据已存在（复用），文件含 {len(result['sheets'])} 个分表",
                "file_id": result["file_id"],
                "sheets": [
                    {"name": s["sheet_name"], "rows": s["row_count"]}
                    for s in result["sheets"]
                ],
            }
        file_rec = result.get("file") or {}
        return {
            "success": True,
            "message": f"已导入「{file_rec.get('file_name', path)}」，"
                       f"含 {file_rec.get('sheet_count', 0)} 个分表，"
                       f"{file_rec.get('total_rows', 0)} 行数据",
            "file_id": result["file_id"],
            "sheets": [
                {"name": s["sheet_name"], "rows": s["row_count"]}
                for s in result["sheets"]
            ],
        }
    except ValueError as e:
        return {"success": False, "error": str(e)}
    except Exception as e:  # noqa: BLE001
        return {"success": False, "error": f"导入失败: {e}"}


def query_table(file: str, sheet: str = "", columns: list | None = None,
                filters: dict | None = None, order_by: str = "",
                limit: int = 100, project_id: str = "",
                aggregate: dict | None = None,
                work_dir: str = "") -> dict[str, Any]:
    """Query a project data table (in-DB, never reads the Excel file).

    columns: list of field names to return (default: all).
    filters: {"字段名": 值} exact-match conditions (AND).
    order_by: "字段名" or "字段名:desc".
    limit: max rows returned (capped at 5000).
    aggregate: (Phase 17 P2) 分组聚合，如
        {"group_by": ["销售人员"], "metrics": ["sum(销售额)", "count(*)"]}
      返回聚合结果（几十行），上万行处理不爆上下文的推荐方式。
    """
    try:
        if not project_id:
            return {"success": False, "error": "未指定项目"}
        store, db = _store()
        file_rec, sheet_rec = _file_and_sheet(store, project_id, file, sheet)
        valid = _valid_columns(sheet_rec)
        table_name = sheet_rec["table_name"]

        # ── Aggregate mode (Phase 17 P2): GROUP BY + metrics, 返回聚合结果 ──
        if aggregate:
            if not isinstance(aggregate, dict):
                return {"success": False, "error": "aggregate 必须是 {group_by, metrics} 对象"}
            groups = aggregate.get("group_by") or []
            if isinstance(groups, str):
                groups = [groups]
            if not isinstance(groups, list):
                return {"success": False, "error": "group_by 必须是字段名或字段名数组"}
            bad_g = [g for g in groups if g not in valid]
            if bad_g:
                return {"success": False, "error": f"未知分组字段: {', '.join(bad_g)}"}
            metrics = aggregate.get("metrics") or []
            if not isinstance(metrics, list) or not metrics:
                return {"success": False, "error": "metrics 至少需要一个聚合表达式，如 'sum(销售额)' 或 'count(*)'"}
            metric_sql: list[str] = []
            metric_aliases: list[str] = []
            import re as _re
            for m in metrics:
                m = str(m).strip()
                mm = _re.match(r"^(sum|avg|count|min|max)\(([^()]*)\)$", m, _re.IGNORECASE)
                if not mm:
                    return {"success": False,
                            "error": f"聚合表达式 '{m}' 不合法；格式如 sum(销售额) / count(*) / avg(金额)"}
                fn = mm.group(1).lower()
                col = mm.group(2).strip()
                if col != "*":
                    if col not in valid:
                        return {"success": False, "error": f"未知聚合字段: {col}"}
                    expr = f"{fn.upper()}({_quote(col)})"
                else:
                    if fn != "count":
                        return {"success": False, "error": f"{fn} 需要指定字段，不能对 * 聚合"}
                    expr = "COUNT(*)"
                alias = f"_m{len(metric_sql)}"
                metric_sql.append(f"{expr} AS {_quote(alias)}")
                metric_aliases.append(alias)
            group_sql = ""
            if groups:
                group_sql = " GROUP BY " + ", ".join(_quote(g) for g in groups)
            order_by_agg = str(order_by or "").strip()
            order_sql = ""
            if order_by_agg:
                direction = "ASC"
                if ":" in order_by_agg:
                    order_by_agg, direction = order_by_agg.split(":", 1)
                order_by_agg = order_by_agg.strip()
                if direction.lower() not in ("asc", "desc"):
                    direction = "ASC"
                # 允许按聚合结果排序：_m0 或原始字段
                if order_by_agg.startswith("_m") and order_by_agg in metric_aliases:
                    order_sql = f" ORDER BY {_quote(order_by_agg)} {direction.upper()}"
                elif order_by_agg in valid:
                    order_sql = f" ORDER BY {_quote(order_by_agg)} {direction.upper()}"
            sel = ", ".join([_quote(g) for g in groups] + metric_sql)
            sql = f'SELECT {sel} FROM "{table_name}"{group_sql}{order_sql}'
            rows = db.execute(sql).fetchall()
            data = []
            for r in rows:
                d = dict(r)
                row_out: dict[str, Any] = {}
                for g in groups:
                    row_out[g] = d.get(g)
                for i, m in enumerate(metrics):
                    row_out[str(m)] = d.get(metric_aliases[i])
                data.append(row_out)
            return {
                "success": True,
                "file": file_rec["file_name"],
                "sheet": sheet_rec["sheet_name"],
                "aggregate": True,
                "group_by": groups,
                "metrics": metrics,
                "row_count": len(data),
                "truncated": False,
                "rows": data,
            }

        # ── Columns whitelist ──
        if columns:
            if not isinstance(columns, list):
                return {"success": False, "error": "columns 必须是字段名数组"}
            bad = [c for c in columns if c not in valid]
            if bad:
                return {"success": False, "error": f"未知字段: {', '.join(bad)}"}
            select_cols = ", ".join(_quote(c) for c in columns)
        else:
            select_cols = "*"

        # ── Filters (parameterized, keys validated) ──
        where_sql = ""
        params: list[Any] = []
        if filters:
            if not isinstance(filters, dict):
                return {"success": False, "error": "filters 必须是 {字段: 值} 对象"}
            conds = []
            for k, v in filters.items():
                if k not in valid:
                    return {"success": False, "error": f"未知字段: {k}"}
                conds.append(f"{_quote(k)} = ?")
                params.append(v)
            where_sql = " WHERE " + " AND ".join(conds)

        # ── Order by (validated) ──
        order_sql = ""
        if order_by:
            order_by = str(order_by).strip()
            direction = "ASC"
            if ":" in order_by:
                order_by, direction = order_by.split(":", 1)
            order_by = order_by.strip()
            if order_by not in valid:
                return {"success": False, "error": f"未知字段: {order_by}"}
            if direction.lower() not in ("asc", "desc"):
                direction = "ASC"
            order_sql = f" ORDER BY {_quote(order_by)} {direction.upper()}"

        # ── Limit (capped) ──
        try:
            limit = max(1, min(int(limit), QUERY_LIMIT_CAP))
        except (TypeError, ValueError):
            limit = 100

        sql = (f'SELECT {select_cols} FROM "{table_name}"'
               f"{where_sql}{order_sql} LIMIT {limit}")
        rows = db.execute(sql, params).fetchall()
        data = [dict(r) for r in rows]
        return {
            "success": True,
            "file": file_rec["file_name"],
            "sheet": sheet_rec["sheet_name"],
            "columns": columns or list(valid.keys()),
            "row_count": len(data),
            "truncated": len(data) >= limit,
            "rows": data,
        }
    except ValueError as e:
        return {"success": False, "error": str(e)}
    except Exception as e:  # noqa: BLE001
        return {"success": False, "error": f"查询失败: {e}"}


def table_stats(file: str, sheet: str = "", group_by: str = "",
                agg: str = "sum", agg_column: str = "",
                project_id: str = "", work_dir: str = "") -> dict[str, Any]:
    """Aggregate a project data table (sum/avg/count/min/max, optional group)."""
    try:
        if not project_id:
            return {"success": False, "error": "未指定项目"}
        store, db = _store()
        file_rec, sheet_rec = _file_and_sheet(store, project_id, file, sheet)
        valid = _valid_columns(sheet_rec)
        table_name = sheet_rec["table_name"]

        func = str(agg or "sum").strip().lower()
        if func not in AGG_FUNCS:
            return {"success": False, "error": f"不支持的聚合: {agg}；可用 {sorted(AGG_FUNCS)}"}

        # ── agg_column (required for all except count) ──
        if func == "count":
            expr = "COUNT(*)"
        else:
            if not agg_column or agg_column not in valid:
                return {"success": False, "error": f"缺少有效的 agg_column；可用字段: {', '.join(valid)}"}
            expr = f"{func.upper()}({_quote(agg_column)})"

        # ── group_by (validated) ──
        group_sql = ""
        if group_by:
            if group_by not in valid:
                return {"success": False, "error": f"未知分组字段: {group_by}"}
            group_sql = f" GROUP BY {_quote(group_by)}"

        if group_by:
            sql = (f'SELECT {_quote(group_by)} AS group_key, {expr} AS value '
                   f'FROM "{table_name}"{group_sql} ORDER BY group_key')
            rows = db.execute(sql).fetchall()
            groups = [
                {"group": r["group_key"], "value": r["value"]}
                for r in rows
            ]
            return {
                "success": True,
                "file": file_rec["file_name"],
                "sheet": sheet_rec["sheet_name"],
                "agg": func,
                "agg_column": agg_column or "*",
                "group_by": group_by,
                "groups": groups,
                "row_count": len(groups),
            }

        sql = f'SELECT {expr} AS value FROM "{table_name}"'
        value = db.execute(sql).fetchone()["value"]
        return {
            "success": True,
            "file": file_rec["file_name"],
            "sheet": sheet_rec["sheet_name"],
            "agg": func,
            "agg_column": agg_column or "*",
            "value": value,
        }
    except ValueError as e:
        return {"success": False, "error": str(e)}
    except Exception as e:  # noqa: BLE001
        return {"success": False, "error": f"统计失败: {e}"}


# ==================================================================
# Phase 14D: cross-table join reconciliation
# ==================================================================

# SQLite supports RIGHT JOIN only from 3.39; this environment ships 3.32.
JOIN_MODES = {"inner", "left"}


def join_tables(left_file: str, right_file: str, left_key: str,
                right_key: str, left_sheet: str = "", right_sheet: str = "",
                columns: list | None = None, how: str = "inner",
                limit: int = 100, project_id: str = "",
                work_dir: str = "") -> dict[str, Any]:
    """Join two project data tables on a key column (in-DB reconciliation).

    left_file/right_file: data file names (e.g. 2026Q2_流水.xlsx).
    left_key/right_key:   join key column names on each side.
    left_sheet/right_sheet: sheet names (default: first sheet of each file).
    columns:              optional list of output columns:
                            "字段"        → from left table (or right if only there)
                            "left:字段"   → explicitly from the left table
                            "right:字段"  → explicitly from the right table (aliased "R_字段")
                          Default: all left columns + all right non-key columns.
    how:                  "inner" | "left" (RIGHT JOIN unsupported by SQLite 3.32).
    limit:                max result rows (capped at 500).
    """
    try:
        if not project_id:
            return {"success": False, "error": "未指定项目"}
        how = str(how or "inner").strip().lower()
        if how not in JOIN_MODES:
            return {"success": False,
                    "error": f"不支持的连接类型: {how}；当前 SQLite 仅支持 {sorted(JOIN_MODES)}"
                             f"（RIGHT JOIN 需 SQLite ≥ 3.39）"}
        store, db = _store()
        left_file_rec, left_sheet_rec = _file_and_sheet(
            store, project_id, left_file, left_sheet
        )
        right_file_rec, right_sheet_rec = _file_and_sheet(
            store, project_id, right_file, right_sheet
        )
        left_valid = _valid_columns(left_sheet_rec)
        right_valid = _valid_columns(right_sheet_rec)

        if left_key not in left_valid:
            return {"success": False,
                    "error": f"左表未知字段: {left_key}；可用: {', '.join(left_valid)}"}
        if right_key not in right_valid:
            return {"success": False,
                    "error": f"右表未知字段: {right_key}；可用: {', '.join(right_valid)}"}

        left_table = left_sheet_rec["table_name"]
        right_table = right_sheet_rec["table_name"]

        # ── Build SELECT column list ──
        select_parts: list[str] = []
        if columns:
            if not isinstance(columns, list):
                return {"success": False, "error": "columns 必须是字段名数组"}
            for col_spec in columns:
                col_spec = str(col_spec).strip()
                if col_spec.startswith("left:"):
                    name = col_spec[5:].strip()
                    if name not in left_valid:
                        return {"success": False, "error": f"左表未知字段: {name}"}
                    select_parts.append(f'L.{_quote(name)} AS {_quote(name)}')
                elif col_spec.startswith("right:"):
                    name = col_spec[6:].strip()
                    if name not in right_valid:
                        return {"success": False, "error": f"右表未知字段: {name}"}
                    select_parts.append(f'R.{_quote(name)} AS {_quote("R_" + name)}')
                else:
                    if col_spec in left_valid:
                        select_parts.append(
                            f'L.{_quote(col_spec)} AS {_quote(col_spec)}'
                        )
                    elif col_spec in right_valid:
                        select_parts.append(
                            f'R.{_quote(col_spec)} AS {_quote("R_" + col_spec)}'
                        )
                    else:
                        return {"success": False,
                                "error": f"未知字段: {col_spec}（左右表均无）"}
        else:
            # Default: all left columns + all right non-key columns.
            for name in left_valid:
                select_parts.append(f'L.{_quote(name)} AS {_quote(name)}')
            for name in right_valid:
                if name == right_key:
                    continue
                alias = name if name not in left_valid else f"R_{name}"
                select_parts.append(f'R.{_quote(name)} AS {_quote(alias)}')

        try:
            limit = max(1, min(int(limit), QUERY_LIMIT_CAP))
        except (TypeError, ValueError):
            limit = 100

        join_kw = "JOIN" if how == "inner" else "LEFT JOIN"
        sql = (
            f'SELECT {", ".join(select_parts)} '
            f'FROM "{left_table}" AS L {join_kw} "{right_table}" AS R '
            f'ON L.{_quote(left_key)} = R.{_quote(right_key)} '
            f'LIMIT {limit}'
        )
        rows = db.execute(sql).fetchall()
        data = [dict(r) for r in rows]
        return {
            "success": True,
            "left_file": left_file_rec["file_name"],
            "left_sheet": left_sheet_rec["sheet_name"],
            "right_file": right_file_rec["file_name"],
            "right_sheet": right_sheet_rec["sheet_name"],
            "how": how,
            "row_count": len(data),
            "truncated": len(data) >= limit,
            "rows": data,
        }
    except ValueError as e:
        return {"success": False, "error": str(e)}
    except Exception as e:  # noqa: BLE001
        return {"success": False, "error": f"连接查询失败: {e}"}


# ==================================================================
# Phase 14C: parameterized cell-level changes + change log
# ==================================================================

def update_rows(file: str, sheet: str = "", filters: dict | None = None,
                updates: dict | None = None, project_id: str = "",
                work_dir: str = "") -> dict[str, Any]:
    """Update matching rows in a project data table (cell-level change log).

    filters: {"字段名": 值} exact-match conditions (AND) locating the rows.
    updates: {"字段名": 新值} values to set on every matching row.
    Returns affected row count and the number of logged cell changes.
    """
    try:
        if not project_id:
            return {"success": False, "error": "未指定项目"}
        if not updates or not isinstance(updates, dict):
            return {"success": False, "error": "updates 必须是 {字段: 新值} 对象"}
        if not filters or not isinstance(filters, dict):
            return {"success": False, "error": "filters 必须是 {字段: 值} 对象，"
                                                "为避免误改全部行必须指定定位条件"}
        store, db = _store()
        file_rec, sheet_rec = _file_and_sheet(store, project_id, file, sheet)
        valid = _valid_columns(sheet_rec)
        table_name = sheet_rec["table_name"]

        bad = [k for k in filters if k not in valid] + \
              [k for k in updates if k not in valid]
        if bad:
            return {"success": False, "error": f"未知字段: {', '.join(set(bad))}"}

        # fetch prior values (for change log) then update
        prior = store.fetch_rows(
            table_name, list(updates.keys()), filters
        )
        if not prior:
            return {"success": False, "error": "没有匹配到任何行",
                    "matched": 0, "changed_cells": 0}
        headers = [h["name"] for h in sheet_rec.get("headers") or []]
        key_col = headers[0] if headers else None
        affected = store.update_rows(
            table_name, filters, updates,
            extra_cols=[key_col] if key_col else None,
        )

        for old in affected:
            _change_log(
                store, file_rec["id"], sheet_rec["sheet_name"],
                row_index=old["id"], op_type="update",
                columns=list(updates.keys()),
                old_values={c: old.get(c) for c in updates},
                new_values=updates,
                sheet_headers=headers,
                key_value=old.get(key_col) if key_col else "",
            )
        store.db.commit()
        return {
            "success": True,
            "file": file_rec["file_name"],
            "sheet": sheet_rec["sheet_name"],
            "matched": len(affected),
            "changed_cells": len(affected) * len(updates),
            "message": f"已更新 {len(affected)} 行 × {len(updates)} 列",
        }
    except ValueError as e:
        return {"success": False, "error": str(e)}
    except Exception as e:  # noqa: BLE001
        return {"success": False, "error": f"更新失败: {e}"}


def insert_rows(file: str, sheet: str = "", rows: list | None = None,
                project_id: str = "", work_dir: str = "") -> dict[str, Any]:
    """Insert new rows into a project data table (cell-level change log).

    rows: list of {"字段名": 值} dicts; all rows must use the same columns.
    """
    try:
        if not project_id:
            return {"success": False, "error": "未指定项目"}
        if not rows or not isinstance(rows, list):
            return {"success": False, "error": "rows 必须是 {字段: 值} 对象数组"}
        store, db = _store()
        file_rec, sheet_rec = _file_and_sheet(store, project_id, file, sheet)
        valid = _valid_columns(sheet_rec)
        table_name = sheet_rec["table_name"]

        # Normalize column set from the first row
        columns = list(rows[0].keys())
        bad = [c for c in columns if c not in valid]
        if bad:
            return {"success": False, "error": f"未知字段: {', '.join(bad)}"}

        inserted_ids: list[int] = []
        for r in rows:
            if not isinstance(r, dict):
                return {"success": False, "error": "rows 每项必须是对象"}
            values = [r.get(c) for c in columns]
            new_row = store.insert_row(table_name, columns, values)
            if new_row:
                inserted_ids.append(new_row["id"])
                headers = [h["name"] for h in sheet_rec.get("headers") or []]
                key_col = headers[0] if headers else None
                _change_log(
                    store, file_rec["id"], sheet_rec["sheet_name"],
                    row_index=new_row["id"], op_type="insert",
                    columns=columns,
                    new_values={c: new_row.get(c) for c in columns},
                    sheet_headers=headers,
                    key_value=new_row.get(key_col) if key_col else "",
                )
        store.db.commit()
        return {
            "success": True,
            "file": file_rec["file_name"],
            "sheet": sheet_rec["sheet_name"],
            "inserted": len(inserted_ids),
            "row_ids": inserted_ids,
            "message": f"已插入 {len(inserted_ids)} 行",
        }
    except ValueError as e:
        return {"success": False, "error": str(e)}
    except Exception as e:  # noqa: BLE001
        return {"success": False, "error": f"插入失败: {e}"}


def delete_rows(file: str, sheet: str = "", filters: dict | None = None,
                project_id: str = "", work_dir: str = "") -> dict[str, Any]:
    """Delete matching rows from a project data table (cell-level change log).

    filters: {"字段名": 值} exact-match conditions (AND). Required — deleting
    all rows at once is not allowed without an explicit confirm flag.
    """
    try:
        if not project_id:
            return {"success": False, "error": "未指定项目"}
        if not filters or not isinstance(filters, dict) or not filters:
            return {"success": False, "error": "filters 必须指定定位条件，"
                                                "禁止无条件删除"}
        store, db = _store()
        file_rec, sheet_rec = _file_and_sheet(store, project_id, file, sheet)
        valid = _valid_columns(sheet_rec)
        table_name = sheet_rec["table_name"]

        bad = [k for k in filters if k not in valid]
        if bad:
            return {"success": False, "error": f"未知字段: {', '.join(bad)}"}

        deleted = store.delete_rows(table_name, filters)
        if not deleted:
            return {"success": False, "error": "没有匹配到任何行",
                    "deleted": 0}

        headers = [h["name"] for h in sheet_rec.get("headers") or []]
        for row in deleted:
            _change_log(
                store, file_rec["id"], sheet_rec["sheet_name"],
                row_index=row.get("id", 0), op_type="delete",
                columns=headers,
                old_values={c: row.get(c) for c in headers},
                sheet_headers=headers,
                key_value=row.get(headers[0]) if headers else "",
            )
        store.db.commit()
        return {
            "success": True,
            "file": file_rec["file_name"],
            "sheet": sheet_rec["sheet_name"],
            "deleted": len(deleted),
            "message": f"已删除 {len(deleted)} 行",
        }
    except ValueError as e:
        return {"success": False, "error": str(e)}
    except Exception as e:  # noqa: BLE001
        return {"success": False, "error": f"删除失败: {e}"}


# ==================================================================
# Phase 14C: materialize the data plane back to Excel
# ==================================================================

def export_project_data(file: str, mode: str = "template", sheet: str = "",
                        project_id: str = "", work_dir: str = "",
                        progress: Callable[[float, str], None] | None = None
                        ) -> dict[str, Any]:
    """Write the project data plane back to the source Excel workbook.

    mode:
      template — keep the original workbook (styles/merged cells), rebuild
                 every data cell for every imported sheet; deleted rows are
                 physically removed from the sheet.
      precise  — only write the cells recorded in project_data_changes
                 (update/insert); delete rows are skipped (risky to shift).

    progress: 可选回调 progress(percent 0-100, message) —— 异步任务上报进度用
    （Phase 17 P7：贴边框进度条。不传则同步执行、无进度上报，向后兼容）。
    """
    def report(p: float, msg: str = "") -> None:
        if progress is None:
            return
        try:
            progress(max(0.0, min(100.0, p)), msg)
        except Exception:  # noqa: BLE001
            pass

    try:
        if not project_id:
            return {"success": False, "error": "未指定项目"}
        if not work_dir:
            return {"success": False, "error": "未指定工作目录"}
        mode = str(mode or "template").strip().lower()
        if mode not in EXPORT_MODES:
            return {"success": False, "error": f"不支持的导出模式: {mode}；"
                                                f"可用 {sorted(EXPORT_MODES)}"}

        store, db = _store()
        file_rec = store.find_file_by_name(project_id, file)
        if not file_rec:
            return {"success": False, "error": f"项目数据库中未找到数据文件「{file}」"}
        from tools.project_data_importer import _resolve_work_path
        full_path = _resolve_work_path(work_dir, file_rec["source_path"])
        if not os.path.isfile(full_path):
            return {"success": False,
                    "error": f"源文件不存在: {file_rec['source_path']}"}

        # Phase 17 P9：写回前文件锁检测（Excel 打开时独占锁定，写回必败）
        lock_err = ensure_file_writable(full_path)
        if lock_err:
            return lock_err

        # 阶段 7.9 / Phase 17 P4：不再按扩展名一刀切——先做真实格式检测
        # （magic bytes）。真 .xls 走 xlwt 后端写回；假 .xls（HTML/XML）
        # 无法安全原地写回，改生成 .xlsx 转换副本。
        real_fmt = detect_real_format(full_path)

        if real_fmt in ("xlsx", "xls"):
            writer = load_writer(full_path, real_fmt)
            report(8, "工作簿加载完成，开始写单元格")
            try:
                if mode == "template":
                    sheets = store.list_sheets(file_rec["id"])
                    written = _export_template(writer, store, file_rec, sheets,
                                               progress=progress,
                                               pbase=12.0, pspan=68.0)
                else:
                    written = _export_precise(writer, store, file_rec,
                                              progress=progress,
                                              pbase=12.0, pspan=68.0)
                report(84, "单元格写入完成，保存文件")
                writer.save()
            finally:
                writer.close()
            report(92, "文件已保存，更新元数据")

            # Source file now matches the data plane → refresh stored hash so
            # the index page keeps showing synced=true (14D uses it for drift).
            from tools.project_data_importer import sha256_file
            store.update_file(file_rec["id"], file_hash=sha256_file(full_path))
            report(100, "写回完成")

            return {
                "success": True,
                "file": file_rec["file_name"],
                "mode": mode,
                "format": real_fmt,
                "path": file_rec["source_path"],
                "written_cells": written,
                "message": f"已按「{mode}」模式回写（{format_label(real_fmt)}），"
                           f"共写入 {written} 个单元格",
            }

        # ── 假 .xls（HTML/SpreadsheetML）等非 Excel 二进制：转换副本兜底 ──
        report(15, "非 Excel 二进制，生成转换副本")
        written, converted_path = _export_converted_copy(
            store, file_rec, full_path, real_fmt)
        report(100, "转换副本已生成")
        return {
            "success": True,
            "file": file_rec["file_name"],
            "mode": mode,
            "format": real_fmt,
            "path": file_rec["source_path"],
            "converted_path": os.path.relpath(converted_path, work_dir),
            "written_cells": written,
            "message": (
                f"原文件实际是{format_label(real_fmt)}，并非真 Excel 二进制，"
                "无法安全原地写回（避免破坏原格式）。已生成转换副本 "
                f"「{os.path.basename(converted_path)}」并写入全部 {written} 个"
                "单元格，请用 Excel 打开该副本核对。"
            ),
        }
    except ValueError as e:
        return {"success": False, "error": str(e)}
    except Exception as e:  # noqa: BLE001
        return {"success": False, "error": f"导出失败: {e}"}


def _layouts_of(file_rec: dict) -> dict:
    """解析导入时记录的每 sheet 布局（header_row 等，0-based）。"""
    import json
    try:
        meta = json.loads(file_rec.get("meta_json") or "{}")
    except Exception:
        meta = {}
    return meta.get("layouts") or {}


def _export_template(writer, store: ProjectDataStore, file_rec: dict,
                     sheets: list[dict],
                     progress: Callable[[float, str], None] | None = None,
                     pbase: float = 0.0, pspan: float = 100.0) -> int:
    """Rebuild every imported sheet from its data table (keep Excel styles)."""
    layouts = _layouts_of(file_rec)
    written = 0
    # Phase 17 P7：预计算总单元格数（每 sheet: 表头 + 数据行 × 字段）
    total_cells = sum(
        len([h for h in (s.get("headers") or [])]) * (1 + int(s.get("row_count") or 0))
        for s in sheets if writer.has(s["sheet_name"])
    ) or 1
    for sheet_rec in sheets:
        sheet_name = sheet_rec["sheet_name"]
        if not writer.has(sheet_name):
            continue
        headers = [h["name"] for h in sheet_rec.get("headers") or []]
        if not headers:
            continue
        # 财务报表常有标题/制表日期行，表头不在第 1 行——用导入时检测到的
        # header_row（0-based）定位，避免把表头/数据错写到标题行。
        lay = layouts.get(sheet_name) or {}
        header_row = int(lay.get("header_row", 0) or 0)  # 0-based
        # Read the current data plane content ordered by id.
        data_rows = _read_all(store, sheet_rec["table_name"], headers)
        # Write header row at its real position (Excel 1-based = header_row + 1)
        for c, name in enumerate(headers, start=1):
            writer.set_cell(sheet_name, header_row + 1, c, name)
            written += 1
        # Write data rows starting right after the header row
        for i, row in enumerate(data_rows, start=header_row + 2):
            for c, name in enumerate(headers, start=1):
                writer.set_cell(sheet_name, i, c, row.get(name))
                written += 1
                if progress and written % 50 == 0:
                    progress(pbase + pspan * written / total_cells,
                             f"写入单元格 {written}/{total_cells}")
        # Remove trailing rows that no longer exist in the data plane
        # （.xls 后端 delete_rows 退化为清空单元格，避免行错位）
        expect_last = header_row + 1 + len(data_rows)
        max_row = writer.max_row(sheet_name) or 0
        if expect_last < max_row:
            writer.delete_rows(sheet_name, expect_last + 1,
                               max_row - expect_last)
    if progress:
        progress(pbase + pspan, "单元格写入完成")
    return written


def _read_all(store: ProjectDataStore, table_name: str,
              headers: list[str]) -> list[dict]:
    cols = ", ".join(f'"{c}"' for c in headers)
    rows = store.db.execute(
        f'SELECT {cols} FROM "{table_name}" ORDER BY id'
    ).fetchall()
    return [dict(r) for r in rows]


def _export_precise(writer, store: ProjectDataStore, file_rec: dict,
                    progress: Callable[[float, str], None] | None = None,
                    pbase: float = 0.0, pspan: float = 100.0) -> int:
    """Write only the cells recorded in project_data_changes.

    Rows are located by their position in the id-ordered data table (not the
    raw id), so inserted/deleted rows never land at the wrong Excel row.
    """
    layouts = _layouts_of(file_rec)
    written = 0
    changes = store.list_changes(file_rec["id"], limit=2000)
    total = max(len(changes), 1)
    # sheet_name -> {data_id: row_seq (1-based data row order)}
    row_seq_cache: dict[str, dict] = {}
    sheet_tables: dict[str, str] = {}
    for s in store.list_sheets(file_rec["id"]):
        sheet_tables[s["sheet_name"]] = s["table_name"]
    for idx, ch in enumerate(changes):
        sheet_name = ch["sheet_name"]
        if not writer.has(sheet_name):
            continue
        op = ch["op_type"]
        if op not in ("update", "insert"):
            continue  # deletes shift rows — skipped in precise mode
        row_index = ch["row_index"]
        col_index = ch["col_index"]
        if row_index is None or col_index is None:
            continue
        if sheet_name not in row_seq_cache:
            table_name = sheet_tables.get(sheet_name)
            if not table_name:
                row_seq_cache[sheet_name] = {}
            else:
                ids = store.db.execute(
                    f'SELECT id FROM "{table_name}" ORDER BY id'
                ).fetchall()
                row_seq_cache[sheet_name] = {
                    r["id"]: i + 1 for i, r in enumerate(ids)
                }
        row_seq = row_seq_cache[sheet_name].get(row_index)
        if row_seq is None:
            continue
        lay = layouts.get(sheet_name) or {}
        header_row = int(lay.get("header_row", 0) or 0)  # 0-based
        # Excel 行 = header_row + 1（表头） + row_seq（数据序号）
        writer.set_cell(sheet_name, header_row + 1 + row_seq, col_index + 1,
                        _unjsonable(ch["new_value"]))
        written += 1
        if progress and written % 20 == 0:
            progress(pbase + pspan * idx / total, f"写回 {written} 处")
    if progress:
        progress(pbase + pspan, "单元格写入完成")
    return written


def _export_converted_copy(store: ProjectDataStore, file_rec: dict,
                           full_path: str, real_fmt: str) -> tuple[int, str]:
    """从数据平面重建一个 .xlsx 转换副本（用于非 Excel 二进制的假 .xls 等）。

    原文件（HTML/SpreadsheetML/文本）保持不动，避免破坏其格式；
    副本写入全部 sheet 的数据，供用户用 Excel 打开核对。
    """
    import openpyxl
    dirname = os.path.dirname(full_path)
    base = os.path.splitext(os.path.basename(full_path))[0]
    converted_path = os.path.join(dirname, f"{base}.转换.xlsx")
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    written = 0
    try:
        for sheet_rec in store.list_sheets(file_rec["id"]):
            headers = [h["name"] for h in sheet_rec.get("headers") or []]
            if not headers:
                continue
            title = sheet_rec["sheet_name"]
            if len(title) > 31:  # openpyxl 限制：工作表名 ≤ 31 字符
                title = title[:31]
            ws = wb.create_sheet(title=title)
            data_rows = _read_all(store, sheet_rec["table_name"], headers)
            for c, name in enumerate(headers, start=1):
                ws.cell(row=1, column=c, value=name)
            for i, row in enumerate(data_rows, start=2):
                for c, name in enumerate(headers, start=1):
                    ws.cell(row=i, column=c, value=row.get(name))
                    written += 1
        wb.save(converted_path)
    finally:
        wb.close()
    return written, converted_path


def _unjsonable(value: str) -> Any:
    """Restore a change-log value back to its Python literal (best effort)."""
    if value == "":
        return None
    import json
    try:
        return json.loads(value)
    except (ValueError, TypeError):
        return value


# ==================================================================
# 智能体优化 3.0（阶段 C）：数据索引按需化
#   list_data_files  → 文件清单（文件名+分表数+行数，~50 token）
#   get_table_index  → 单表索引（字段名/类型/行数，~100 token）
# 取代 `_build_project_data_instructions` 的全量字段注入——从
# 「常驻全部索引」改为「按需读单表」，直击省算力。
# ==================================================================


def list_data_files(project_id: str = "", work_dir: str = "") -> dict[str, Any]:
    """列出项目数据库已导入的数据文件清单（仅元数据，不读数据）。

    返回每个文件的：文件名、源路径、分表数、分表清单（表名+行数）、
    总行数。AI 用此工具了解「有哪些数据可用」，字段明细按需用
    get_table_index 读单表。
    """
    if not project_id:
        return {"success": False, "message": "缺少 project_id"}
    try:
        store, _ = _store()
        files = store.list_files(project_id)
        items = []
        for f in files:
            if f.get("status") != "done":
                continue
            sheets = f.get("sheets") or []
            items.append({
                "file": f.get("file_name"),
                "source_path": f.get("source_path"),
                "sheet_count": f.get("sheet_count", 0),
                "total_rows": f.get("total_rows", 0),
                "sheets": [
                    {"sheet": s.get("sheet_name"),
                     "rows": s.get("row_count", 0)}
                    for s in sheets
                ],
            })
        return {
            "success": True,
            "count": len(items),
            "files": items,
            "message": f"共 {len(items)} 个已导入数据文件；查字段用 get_table_index(file, sheet)",
        }
    except Exception as e:  # noqa: BLE001
        return {"success": False, "message": f"list_data_files 失败: {e}"}


def get_table_index(file: str, sheet: str = "",
                    project_id: str = "", work_dir: str = "") -> dict[str, Any]:
    """返回单表索引：字段名/类型/行数（~100 token，按需读）。

    file: 数据文件标识（文件名或库文件名）；sheet: 工作表名（默认第一个）。
    返回该表的完整字段清单（名称+类型）与行数，供 AI 定位候选匹配键
    与目标金额列。
    """
    if not project_id:
        return {"success": False, "message": "缺少 project_id"}
    try:
        store, _ = _store()
        file_rec, sheet_rec = _file_and_sheet(store, project_id, file, sheet)
        headers = _valid_columns(sheet_rec) if sheet_rec else {}
        return {
            "success": True,
            "file": file_rec.get("file_name"),
            "sheet": sheet_rec.get("sheet_name") if sheet_rec else "",
            "row_count": sheet_rec.get("row_count", 0) if sheet_rec else 0,
            "col_count": sheet_rec.get("col_count", 0) if sheet_rec else 0,
            "columns": [
                {"name": name, "type": typ} for name, typ in headers.items()
            ],
            "message": f"共 {len(headers)} 列；用 query_table/table_stats 查数据",
        }
    except ValueError as e:
        return {"success": False, "message": str(e)}
    except Exception as e:  # noqa: BLE001
        return {"success": False, "message": f"get_table_index 失败: {e}"}
