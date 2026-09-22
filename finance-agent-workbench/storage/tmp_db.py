"""tmp_db — 集成应用每次执行的临时数据库（2026-08-20 新增）。

背景（应用重构第一步）：
  数据核对与校验应用要求——每次执行的核对/审计/修改都发生在【独立临时库】：
    - 用户上传的 Excel → 导入到临时库（对个性化数据的重新识别，不缓存旧结果）
    - 所有核对/审计/修改操作 → 临时库 SQL（不污染 __app_recon__ 主库）
    - 最终修改 = 临时库 SQL 修改 + export_project_data 回写 Excel 两个过程
    - 任务结束保留 run.db 供报告追溯，可清理

实现：
  TmpRun 类管理一个 run 的生命周期：
    - 目录 data/tmp_runs/<run_id>/，run.db 为 SQLite 文件
    - 从 schema.sql 提取 project_data 相关表结构并建表（其余主库表不建）
    - 提供 sqlite3.Connection（check_same_thread=False，与主库一致）
  工具层通过 db_override 参数使用临时库连接（见 tools/reconcile_tool.py、
  tools/project_data_tools.py 的改造），不改变主库全局连接。
"""

from __future__ import annotations

import logging
import shutil
import sqlite3
import threading
import time
import uuid
from pathlib import Path

from config.settings import DATA_DIR

logger = logging.getLogger(__name__)

TMP_RUNS_DIR = DATA_DIR / "tmp_runs"

# project_data 相关的表（临时库只建这些，避免把 models/projects 等全局表带入）
PROJECT_DATA_TABLES = [
    "project_data_files",
    "project_data_sheets",
    "project_data_changes",
]


def _extract_schema(sql: str, table: str) -> str | None:
    """从 schema.sql 中提取某个表的 CREATE TABLE 语句（含完整列定义）。"""
    start = sql.find(f"CREATE TABLE {table}")
    if start < 0:
        start = sql.find(f"CREATE TABLE IF NOT EXISTS {table}")
    if start < 0:
        return None
    # 找到分号结尾
    end = sql.find(";", start)
    if end < 0:
        return None
    return sql[start:end + 1]


def ensure_tmp_dir() -> None:
    TMP_RUNS_DIR.mkdir(parents=True, exist_ok=True)


def cleanup_stale(max_age_sec: int = 86400, *, current_run_ids: set[str] | None = None) -> int:
    """清理超龄的临时运行目录（阶段 4 运行垃圾常态化清理）。

    规则（单机离线场景）：
      - 扫描 TMP_RUNS_DIR 下所有子目录，删除 mtime 超过 max_age_sec 的目录。
      - current_run_ids：正在进行的 run_id（活动 run），一律跳过（防误删）。
      - 返回清理的数量。

    触发时机：
      - Flask create_app() 启动时（防崩溃残留）
      - TmpRun.create() 开头（创建新 run 时顺带清超龄旧 run）
      - 应用执行结束后（见各 run 端点 finally 调 cleanup）
    """
    if not TMP_RUNS_DIR.exists():
        return 0
    now = time.time()
    current = set(current_run_ids or ())
    # 并上当前活动 run（内存注册表），双保险
    with _runs_lock:
        for rid in _active_runs:
            current.add(rid)
    removed = 0
    for child in TMP_RUNS_DIR.iterdir():
        if not child.is_dir():
            continue
        if child.name in current:
            continue
        try:
            mtime = child.stat().st_mtime
        except OSError:
            continue
        if (now - mtime) > max_age_sec:
            try:
                shutil.rmtree(child, ignore_errors=True)
                removed += 1
                logger.info("清理超龄临时运行目录 %s", child.name)
            except OSError as e:  # noqa: BLE001
                logger.warning("清理临时运行目录 %s 失败: %s", child.name, e)
    return removed


class TmpRun:
    """一次应用执行（校验/修改）的临时数据库生命周期。

    用法：
        run = TmpRun.create()
        db = run.db            # sqlite3.Connection
        store = ProjectDataStore(db)   # 用临时库的 store
        ... 导入/核对/修改 ...
        run.cleanup()          # 任务结束清理（或保留 trace 时 skip）
    """

    def __init__(self, run_id: str, db: sqlite3.Connection, dir: Path) -> None:
        self.run_id = run_id
        self.db = db
        self.dir = dir
        self._lock = threading.Lock()
        # 审计决策记录（多轮核对闭环，2026-08-20 第二步）：
        #   key = "side:key"（如 "base:合同A001"），value = decision 中文
        self.decisions: dict[str, str] = {}

    # ------------------------------------------------------------------
    @classmethod
    def create(cls, run_id: str | None = None) -> "TmpRun":
        ensure_tmp_dir()
        # 阶段 4：创建新 run 时顺带清理超龄的旧临时运行目录（防堆积）
        cleanup_stale(max_age_sec=86400)
        rid = run_id or uuid.uuid4().hex
        run_dir = TMP_RUNS_DIR / rid
        run_dir.mkdir(parents=True, exist_ok=True)
        db_path = run_dir / "run.db"
        db = sqlite3.connect(str(db_path), check_same_thread=False)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA foreign_keys=ON")

        # 建 project_data 表结构（从主 schema.sql 提取）
        schema = (Path(__file__).resolve().parent.parent / "storage" / "schema.sql")
        sql_text = schema.read_text(encoding="utf-8")
        for table in PROJECT_DATA_TABLES:
            stmt = _extract_schema(sql_text, table)
            if stmt:
                try:
                    db.execute(stmt)
                except sqlite3.Error as e:  # noqa: BLE001
                    logger.warning("临时库建表 %s 失败: %s", table, e)
        db.commit()
        logger.info("创建临时库 %s (%s)", rid, db_path)
        return cls(rid, db, run_dir)

    # ------------------------------------------------------------------
    def commit(self) -> None:
        with self._lock:
            self.db.commit()

    def cleanup(self) -> None:
        """删除临时库目录（含 run.db 与 WAL）。"""
        with self._lock:
            try:
                self.db.close()
            except sqlite3.Error:  # noqa: BLE001
                pass
            shutil.rmtree(self.dir, ignore_errors=True)
            logger.info("清理临时库 %s", self.run_id)


# ----------------------------------------------------------------------
# run 注册表（当前活动 run → TmpRun；应用执行期间查询）
# ----------------------------------------------------------------------

_active_runs: dict[str, TmpRun] = {}
_runs_lock = threading.Lock()


def register_run(run_id: str, run: TmpRun) -> None:
    with _runs_lock:
        _active_runs[run_id] = run


def get_run(run_id: str) -> TmpRun | None:
    with _runs_lock:
        return _active_runs.get(run_id)


def unregister_run(run_id: str) -> None:
    with _runs_lock:
        _active_runs.pop(run_id, None)


def list_runs() -> list[str]:
    with _runs_lock:
        return list(_active_runs.keys())
