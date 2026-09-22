"""project_data_files / project_data_sheets CRUD — Phase 14A.

The project data plane stores imported Excel workbooks as typed SQLite
tables (data_<file_id>_<idx>) plus metadata in project_data_files and
project_data_sheets.  This module owns all CRUD for those two tables and
the dynamic per-sheet data tables.

Phase 14C will add project_data_changes (cell-level change log).
"""

from __future__ import annotations

import json
import uuid
from sqlite3 import Connection
from typing import Any

from storage._utils import iso_now, row_to_dict


class ProjectDataStore:
    """CRUD wrapper for the project data plane tables."""

    def __init__(self, db: Connection) -> None:
        self.db = db

    # ------------------------------------------------------------------
    # Files
    # ------------------------------------------------------------------
    def create_file(
        self,
        project_id: str,
        source_path: str,
        file_name: str,
        file_hash: str,
        fmt: str,
    ) -> dict:
        now = iso_now()
        fid = uuid.uuid4().hex
        self.db.execute(
            """INSERT INTO project_data_files
               (id, project_id, source_path, file_name, file_hash, format,
                sheet_count, total_rows, status, error_message, meta_json,
                created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, 0, 0, 'importing', NULL, NULL, ?, ?)""",
            (fid, project_id, source_path, file_name, file_hash, fmt, now, now),
        )
        self.db.commit()
        return self.get_file(fid)

    def get_file(self, file_id: str) -> dict:
        row = self.db.execute(
            "SELECT * FROM project_data_files WHERE id = ?", (file_id,)
        ).fetchone()
        return row_to_dict(row)

    def get_file_by_hash(self, project_id: str, file_hash: str) -> dict:
        row = self.db.execute(
            """SELECT * FROM project_data_files
               WHERE project_id = ? AND file_hash = ? AND status = 'done'
               ORDER BY updated_at DESC LIMIT 1""",
            (project_id, file_hash),
        ).fetchone()
        return row_to_dict(row)

    def find_file_by_source(self, project_id: str, source_path: str) -> dict:
        row = self.db.execute(
            """SELECT * FROM project_data_files
               WHERE project_id = ? AND source_path = ?
               ORDER BY updated_at DESC LIMIT 1""",
            (project_id, source_path),
        ).fetchone()
        return row_to_dict(row)

    def find_file_by_name(self, project_id: str, name: str) -> dict:
        """Find a done file by exact file_name, or by source_path suffix match.

        Used by query_table / table_stats when the LLM passes a file name.
        """
        if not name:
            return {}
        rows = self.db.execute(
            """SELECT * FROM project_data_files
               WHERE project_id = ? AND status = 'done'
               ORDER BY updated_at DESC""",
            (project_id,),
        ).fetchall()
        name = name.strip()
        lowered = name.lower()
        for r in rows:
            d = dict(r)
            if d.get("file_name") == name:
                return d
        for r in rows:
            d = dict(r)
            if d.get("file_name", "").lower() == lowered:
                return d
        for r in rows:
            d = dict(r)
            src = d.get("source_path") or ""
            if src.lower().endswith(lowered):
                return d
        return {}

    def list_files(self, project_id: str) -> list[dict]:
        rows = self.db.execute(
            """SELECT * FROM project_data_files
               WHERE project_id = ?
               ORDER BY updated_at DESC""",
            (project_id,),
        ).fetchall()
        files = [row_to_dict(r) for r in rows]
        if not files:
            return []
        sheet_rows = self.db.execute(
            """SELECT file_id, sheet_name, sheet_index, row_count,
                      col_count, headers_json
               FROM project_data_sheets
               WHERE file_id IN ({})
               ORDER BY sheet_index""".format(
                ",".join("?" * len(files))
            ),
            tuple(f["id"] for f in files),
        ).fetchall()
        by_file: dict[str, list[dict]] = {}
        for sr in sheet_rows:
            d = dict(sr)
            try:
                d["headers"] = json.loads(d.pop("headers_json") or "[]")
            except Exception:
                d["headers"] = []
            by_file.setdefault(sr["file_id"], []).append(d)
        for f in files:
            f["sheets"] = by_file.get(f["id"], [])
        return files

    def update_file(self, file_id: str, **fields: Any) -> dict:
        """Update a file record with whitelisted columns; returns fresh row."""
        allowed = {
            "status", "error_message", "sheet_count", "total_rows",
            "meta_json", "file_hash", "source_path", "file_name", "format",
        }
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return self.get_file(file_id)
        sets = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [iso_now(), file_id]
        self.db.execute(
            f"UPDATE project_data_files SET {sets}, updated_at = ? WHERE id = ?",
            values,
        )
        self.db.commit()
        return self.get_file(file_id)

    def delete_file(self, file_id: str) -> bool:
        self.cleanup_sheets(file_id)
        self.clear_changes(file_id)
        cur = self.db.execute(
            "DELETE FROM project_data_files WHERE id = ?", (file_id,)
        )
        self.db.commit()
        return cur.rowcount > 0

    # ------------------------------------------------------------------
    # Sheets + dynamic data tables
    # ------------------------------------------------------------------
    def create_sheet(
        self,
        file_id: str,
        sheet_name: str,
        sheet_index: int,
        table_name: str,
        row_count: int,
        col_count: int,
        headers: list[dict],
    ) -> dict:
        self.db.execute(
            """INSERT INTO project_data_sheets
               (file_id, sheet_name, sheet_index, table_name,
                row_count, col_count, headers_json)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (file_id, sheet_name, sheet_index, table_name,
             row_count, col_count, json.dumps(headers, ensure_ascii=False)),
        )
        self.db.commit()
        row = self.db.execute(
            """SELECT * FROM project_data_sheets
               WHERE file_id = ? AND sheet_index = ?""",
            (file_id, sheet_index),
        ).fetchone()
        return row_to_dict(row)

    def list_sheets(self, file_id: str) -> list[dict]:
        rows = self.db.execute(
            """SELECT * FROM project_data_sheets
               WHERE file_id = ? ORDER BY sheet_index""",
            (file_id,),
        ).fetchall()
        sheets = []
        for r in rows:
            d = dict(r)
            try:
                d["headers"] = json.loads(d.pop("headers_json") or "[]")
            except Exception:
                d["headers"] = []
            sheets.append(d)
        return sheets

    def create_data_table(self, table_name: str, columns: list[dict]) -> None:
        """Create a typed data table from column defs
        [{"name": ..., "type": ...}, ...] (all column names sanitized)."""
        col_sql = ", ".join(
            f'"{c["name"]}" {c["type"]}' for c in columns
        )
        self.db.execute(
            f"""CREATE TABLE IF NOT EXISTS "{table_name}"
                (id INTEGER PRIMARY KEY AUTOINCREMENT, {col_sql})"""
        )
        self.db.commit()

    def insert_rows(
        self, table_name: str, columns: list[str], rows: list[list]
    ) -> int:
        if not rows:
            return 0
        placeholders = ", ".join("?" * len(columns))
        col_names = ", ".join(f'"{c}"' for c in columns)
        self.db.executemany(
            f'INSERT INTO "{table_name}" ({col_names}) VALUES ({placeholders})',
            [tuple(r) for r in rows],
        )
        self.db.commit()
        return len(rows)

    def cleanup_sheets(self, file_id: str) -> None:
        """Drop all data tables for a file and remove its sheet rows."""
        rows = self.db.execute(
            "SELECT table_name FROM project_data_sheets WHERE file_id = ?",
            (file_id,),
        ).fetchall()
        for r in rows:
            self._drop_table(r["table_name"])
        self.db.execute(
            "DELETE FROM project_data_sheets WHERE file_id = ?", (file_id,)
        )
        self.db.commit()

    def _drop_table(self, table_name: str) -> None:
        # table_name is always generated internally as data_<file_id>_<idx>
        if not table_name.startswith("data_"):
            return
        self.db.execute(f'DROP TABLE IF EXISTS "{table_name}"')
        self.db.commit()

    # ------------------------------------------------------------------
    # Phase 14C: change log
    # ------------------------------------------------------------------
    def log_change(self, file_id: str, sheet_name: str, row_index: int,
                   op_type: str, col_index: int | None = None,
                   old_value: Any = None, new_value: Any = None,
                   run_id: str = "") -> None:
        """Write one cell-level change into project_data_changes."""
        self.db.execute(
            """INSERT INTO project_data_changes
               (file_id, sheet_name, row_index, col_index,
                old_value, new_value, op_type, run_id, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (file_id, sheet_name, row_index, col_index,
             _jsonable(old_value), _jsonable(new_value),
             op_type, run_id, iso_now()),
        )

    def log_change(self, file_id: str, sheet_name: str, row_index: int,
                   op_type: str, col_index: int | None = None,
                   old_value: Any = None, new_value: Any = None,
                   run_id: str = "", col_name: str = "",
                   key_value: str = "") -> None:
        """Write one cell-level change into project_data_changes.

        Phase 17 P5: col_name 固化字段名、key_value 固化行定位键（主键列值），
        使日志自描述到字段级——写回引擎按 col_index 精确定位，
        展示层直接读 col_name/key_value，不依赖数据表反查。
        """
        self.db.execute(
            """INSERT INTO project_data_changes
               (file_id, sheet_name, row_index, col_index, col_name,
                key_value, old_value, new_value, op_type, run_id, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (file_id, sheet_name, row_index, col_index, col_name,
             key_value, _jsonable(old_value), _jsonable(new_value),
             op_type, run_id, iso_now()),
        )

    def list_changes(self, file_id: str, limit: int = 200, offset: int = 0,
                     sheet: str = "", op: str = "") -> list[dict]:
        """Phase 17 P5：正序（按执行顺序）返回变更日志，支持分页与过滤。"""
        sql = "SELECT * FROM project_data_changes WHERE file_id = ?"
        params: list = [file_id]
        if sheet:
            sql += " AND sheet_name = ?"
            params.append(sheet)
        if op:
            sql += " AND op_type = ?"
            params.append(op)
        sql += " ORDER BY id ASC LIMIT ? OFFSET ?"
        params += [limit, offset]
        rows = self.db.execute(sql, params).fetchall()
        return [row_to_dict(r) for r in rows]

    def count_changes(self, file_id: str) -> dict[str, int]:
        """按操作类型统计变更数（摘要角标/写回预览用）。"""
        rows = self.db.execute(
            "SELECT op_type, COUNT(*) AS n FROM project_data_changes "
            "WHERE file_id = ? GROUP BY op_type",
            (file_id,),
        ).fetchall()
        summary = {"update": 0, "insert": 0, "delete": 0, "total": 0}
        for r in rows:
            key = r["op_type"] or "update"
            summary[key] = summary.get(key, 0) + int(r["n"])
            summary["total"] += int(r["n"])
        return summary

    def clear_changes(self, file_id: str) -> None:
        self.db.execute(
            "DELETE FROM project_data_changes WHERE file_id = ?", (file_id,)
        )
        self.db.commit()

    # ------------------------------------------------------------------
    # Phase 14C: row operations on dynamic data tables
    # ------------------------------------------------------------------
    def fetch_rows(self, table_name: str, columns: list[str],
                   filters: dict) -> list[dict]:
        """Select rows matching exact filters; returns dicts keyed by column."""
        where_sql, params = self._filters_sql(filters)
        cols = ", ".join(_q(c) for c in columns)
        rows = self.db.execute(
            f'SELECT id, {cols} FROM "{table_name}"{where_sql}', params
        ).fetchall()
        return [dict(r) for r in rows]

    def update_rows(self, table_name: str, filters: dict,
                    updates: dict, extra_cols: list | None = None) -> list[dict]:
        """Update matching rows; returns rows with their prior cell values
        (used by the caller to write the change log).

        extra_cols: 额外查询列（如主键列），让返回行携带行定位键。
        """
        where_sql, where_params = self._filters_sql(filters)
        cols = ", ".join(
            _q(c) for c in dict.fromkeys(list(updates) + (extra_cols or []))
        )
        rows = self.db.execute(
            f'SELECT id, {cols} FROM "{table_name}"{where_sql}', where_params
        ).fetchall()
        if not rows:
            return []
        set_sql = ", ".join(f"{_q(c)} = ?" for c in updates)
        params = list(updates.values()) + where_params
        self.db.execute(
            f'UPDATE "{table_name}" SET {set_sql}{where_sql}', params
        )
        self.db.commit()
        return [dict(r) for r in rows]

    def delete_rows(self, table_name: str, filters: dict) -> list[dict]:
        """Delete matching rows; returns the deleted rows (for change log)."""
        where_sql, params = self._filters_sql(filters)
        cols = "*"
        rows = self.db.execute(
            f'SELECT {cols} FROM "{table_name}"{where_sql}', params
        ).fetchall()
        if rows:
            self.db.execute(
                f'DELETE FROM "{table_name}"{where_sql}', params
            )
            self.db.commit()
        return [dict(r) for r in rows]

    def insert_row(self, table_name: str, columns: list[str],
                   values: list) -> dict:
        """Insert one row; returns the inserted row (for change log)."""
        cols = ", ".join(_q(c) for c in columns)
        placeholders = ", ".join("?" * len(values))
        cur = self.db.execute(
            f'INSERT INTO "{table_name}" ({cols}) VALUES ({placeholders})',
            list(values),
        )
        self.db.commit()
        row_id = cur.lastrowid
        row = self.db.execute(
            f'SELECT * FROM "{table_name}" WHERE id = ?', (row_id,)
        ).fetchone()
        return dict(row) if row else {}

    def _filters_sql(self, filters: dict) -> tuple[str, list]:
        """Build parameterized WHERE clause from exact-match filters."""
        if not filters:
            return "", []
        conds = []
        params: list = []
        for k, v in filters.items():
            conds.append(f"{_q(k)} = ?")
            params.append(v)
        return " WHERE " + " AND ".join(conds), params


def _q(name: str) -> str:
    """Double-quote an identifier (caller guarantees it is whitelisted)."""
    return f'"{name}"'


def _jsonable(value: Any) -> str:
    """Stringify a cell value for the change log (None → '')."""
    if value is None:
        return ""
    return json.dumps(value, ensure_ascii=False, default=str)


# Re-export for tools layer
__all__ = ["ProjectDataStore", "_q", "_jsonable"]
