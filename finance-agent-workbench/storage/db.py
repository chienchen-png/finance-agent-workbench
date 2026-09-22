import sqlite3
from pathlib import Path
from typing import Set

from flask import Flask, g

from config.settings import DB_PATH

SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"


def _table_columns(db: sqlite3.Connection, table_name: str) -> Set[str]:
    rows = db.execute(f"PRAGMA table_info({table_name})").fetchall()
    return {row["name"] for row in rows}


def _ensure_model_schema(db: sqlite3.Connection) -> None:
    model_columns = _table_columns(db, "models")
    migrations = {
        "provider_id": "ALTER TABLE models ADD COLUMN provider_id TEXT",
        "capabilities": "ALTER TABLE models ADD COLUMN capabilities TEXT",
        "context_window": "ALTER TABLE models ADD COLUMN context_window INTEGER DEFAULT 8192",
    }
    for column, sql in migrations.items():
        if column not in model_columns:
            db.execute(sql)
    # 阶段 7.9.2：models.icon 字段（模型个性化 logo，AI 配置页唯一源头）
    if "icon" not in model_columns:
        db.execute("ALTER TABLE models ADD COLUMN icon TEXT")
    # 阶段 7.9.2：model_providers.icon 字段（供应商个性化 logo）
    provider_columns = _table_columns(db, "model_providers")
    if "icon" not in provider_columns:
        db.execute("ALTER TABLE model_providers ADD COLUMN icon TEXT")
    # Ensure deleted_presets table exists
    db.execute(
        """CREATE TABLE IF NOT EXISTS deleted_presets (
            id TEXT PRIMARY KEY,
            deleted_at TEXT NOT NULL
        )"""
    )
    # Phase 17: token_usage.reasoning_tokens 列（DeepSeek/GLM 思考模式
    # token 计数，2026-08-17 全量审计发现 core.py 收集但从未持久化）
    usage_columns = _table_columns(db, "token_usage")
    if "reasoning_tokens" not in usage_columns:
        db.execute("ALTER TABLE token_usage ADD COLUMN reasoning_tokens INTEGER")

    # Phase 17 P5：project_data_changes.col_name / key_value 列（字段级修改日志）
    change_columns = _table_columns(db, "project_data_changes")
    if "col_name" not in change_columns:
        db.execute("ALTER TABLE project_data_changes ADD COLUMN col_name TEXT")
    if "key_value" not in change_columns:
        db.execute("ALTER TABLE project_data_changes ADD COLUMN key_value TEXT")

    # 阶段 G：projects.work_mode 列（工作模式 manual=人工审批 / auto=全自动）
    project_columns = _table_columns(db, "projects")
    if "work_mode" not in project_columns:
        db.execute("ALTER TABLE projects ADD COLUMN work_mode TEXT NOT NULL DEFAULT 'manual'")


def get_db() -> sqlite3.Connection:
    """Return a per-request SQLite connection.  Created on first access.

    Phase 17 P14: smolagents 用 ThreadPoolExecutor 执行工具，工作线程会继承
    app context（contextvars 复制），导致 g.db 连接被工具线程跨线程使用 →
    sqlite3 抛 "objects created in a thread can only be used in that same thread"。
    这里显式 check_same_thread=False（WAL 模式下 SQLite 支持多线程访问，
    且同一 run 内工具串行执行，无并发写风险）。
    """
    if "db" not in g:
        g.db = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA journal_mode=WAL")
        g.db.execute("PRAGMA foreign_keys=ON")
    return g.db


def close_db(_error: object = None) -> None:
    """Close the request-scoped database connection."""
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db(app: Flask) -> None:
    """Run schema.sql inside an app context and register teardown."""
    with app.app_context():
        db = get_db()
        db.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        _ensure_model_schema(db)
        db.commit()
    app.teardown_appcontext(close_db)
