from __future__ import annotations

from flask import Blueprint, request

from routes._utils import error, payload, success
from storage.db import get_db
from storage.log_store import LogStore
from storage.project_store import ProjectStore

projects_bp = Blueprint("projects_api", __name__, url_prefix="/api/projects")


def _is_hidden_project(name: str) -> bool:
    """集成应用内部隐藏项目判定（`__app_` 前缀命名约定，与应用端 ensureAppProject 一致）。"""
    return str(name or "").startswith("__app_")


def _log(db, event_type: str, summary: str, project_id: str | None = None,
         status: str = "success", detail: str | None = None) -> None:
    """Best-effort local_logs write (PRD §3.8 最简化本地日志)."""
    try:
        LogStore(db).write(event_type=event_type, project_id=project_id,
                           event_summary=summary, status=status, detail=detail)
    except Exception:
        pass


@projects_bp.get("")
def list_projects():
    """项目列表。

    默认**隐藏集成应用的内部项目**（`__app_` 前缀，如 __app_recon__/__app_finmod__），
    不污染用户项目列表（前端侧边栏 + 本接口双保险，隐藏下沉到后端权威层）。
    应用内部（ensureAppProject）传 `?include_hidden=1` 显式查找/复用隐藏项目，
    避免因默认过滤导致每次进入应用都新建隐藏项目（历史曾出现重复 __app_recon__）。
    """
    keyword = request.args.get("q", "").strip()
    include_hidden = request.args.get("include_hidden", "").strip() in ("1", "true", "yes")
    store = ProjectStore(get_db())
    projects = store.search_by_name(keyword) if keyword else store.get_all()
    if not include_hidden:
        projects = [p for p in projects if not _is_hidden_project(p.get("name") or "")]
    return success(projects)


@projects_bp.post("")
def create_project():
    data = payload()
    name = str(data.get("name", "")).strip()
    work_dir = str(data.get("work_dir", "")).strip()
    if not name:
        return error("项目名称不能为空")
    if not work_dir:
        return error("工作目录不能为空")

    db = get_db()
    store = ProjectStore(db)
    project = store.create(
        name,
        work_dir,
        description=(data.get("description") or None),
        year=data.get("year") or None,
        quarter=data.get("quarter") or None,
        default_agent=data.get("default_agent") or None,
        default_model=data.get("default_model") or None,
        work_mode=data.get("work_mode") or "manual",
    )
    _log(db, "project.create", f"创建项目「{name}」", project_id=project.get("id"),
         detail=f"work_dir={work_dir}")
    return success(project, 201)


@projects_bp.get("/<project_id>")
def get_project(project_id: str):
    project = ProjectStore(get_db()).get_by_id(project_id)
    if not project:
        return error("项目不存在", 404)
    return success(project)


@projects_bp.put("/<project_id>")
def update_project(project_id: str):
    data = payload()
    store = ProjectStore(get_db())
    project = store.update(
        project_id,
        name=(data.get("name") or None),
        description=(data.get("description") or None),
        year=data.get("year") or None,
        quarter=data.get("quarter") or None,
        default_agent=data.get("default_agent") or None,
        default_model=data.get("default_model") or None,
        work_mode=data.get("work_mode") or None,
    )
    if not project:
        return error("项目不存在", 404)
    return success(project)


@projects_bp.delete("/<project_id>")
def delete_project(project_id: str):
    db = get_db()
    deleted = ProjectStore(db).delete(project_id)
    if not deleted:
        return error("项目不存在", 404)
    _log(db, "project.delete", f"删除项目 {project_id}", project_id=project_id)
    return success({"id": project_id})


@projects_bp.post("/<project_id>/duplicate")
def duplicate_project(project_id: str):
    """创建项目副本（阶段 7：共享工作目录，复制数据平面 + 上下文）。

    v2.4 决策（与 Codex 会话复制一致）：副本共享 work_dir（不复制物理文件），
    但复制 project_data_files/sheets + data_* 表 + conversations/messages，
    使副本可独立对话/改数。
    """
    db = get_db()
    store = ProjectStore(db)
    src = store.get_by_id(project_id)
    if not src:
        return error("项目不存在", 404)

    # 1. 创建项目记录（共享 work_dir，名称加「副本」后缀）
    import uuid
    new_id = uuid.uuid4().hex
    dup_name = f"{src.get('name')} 副本"
    db.execute(
        """INSERT INTO projects (id, name, description, work_dir, year, quarter,
           default_agent, default_model, work_mode, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (new_id, dup_name, src.get("description"), src.get("work_dir"),
         src.get("year"), src.get("quarter"),
         src.get("default_agent"), src.get("default_model"),
         src.get("work_mode", "manual"), _now_iso(), _now_iso()),
    )

    # 2. 复制上下文（conversations + messages）
    conv_rows = db.execute(
        "SELECT id, title, created_at FROM conversations WHERE project_id = ?",
        (project_id,),
    ).fetchall()
    for conv in conv_rows:
        new_conv_id = uuid.uuid4().hex
        db.execute(
            "INSERT INTO conversations (id, project_id, title, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            (new_conv_id, new_id, conv["title"], conv["created_at"] or _now_iso(), _now_iso()),
        )
        msg_rows = db.execute(
            "SELECT role, content, agent_id, model_id, tokens_used, created_at FROM messages WHERE conversation_id = ?",
            (conv["id"],),
        ).fetchall()
        for m in msg_rows:
            db.execute(
                """INSERT INTO messages
                   (id, conversation_id, role, content, agent_id, model_id, tokens_used, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (uuid.uuid4().hex, new_conv_id, m["role"], m["content"],
                 m["agent_id"], m["model_id"], m["tokens_used"],
                 m["created_at"] or _now_iso()),
            )

    # 3. 复制数据平面（project_data_files/sheets + data_* 表）
    file_rows = db.execute(
        "SELECT * FROM project_data_files WHERE project_id = ?", (project_id,),
    ).fetchall()
    for fr in file_rows:
        new_file_id = uuid.uuid4().hex
        db.execute(
            """INSERT INTO project_data_files
               (id, project_id, source_path, file_name, file_hash, format,
                sheet_count, total_rows, status, error_message, meta_json, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (new_file_id, new_id, fr["source_path"], fr["file_name"], fr["file_hash"],
             fr["format"], fr["sheet_count"], fr["total_rows"], fr["status"],
             fr["error_message"], fr["meta_json"],
             fr["created_at"] or _now_iso(), _now_iso()),
        )
        # 复制 sheets + data_* 表
        sheet_rows = db.execute(
            "SELECT * FROM project_data_sheets WHERE file_id = ?", (fr["id"],),
        ).fetchall()
        for sr in sheet_rows:
            src_table = sr["table_name"]
            new_table = src_table.replace(fr["id"], new_file_id) if fr["id"] in src_table else f"data_{new_file_id}_{sr['sheet_index']}"
            # 复制表结构 + 数据
            db.execute(f'CREATE TABLE IF NOT EXISTS "{new_table}" AS SELECT * FROM "{src_table}"')
            # sheets.id 是 INTEGER AUTOINCREMENT，传 NULL 自动分配
            db.execute(
                """INSERT INTO project_data_sheets
                   (id, file_id, sheet_name, sheet_index, table_name, row_count, col_count, headers_json)
                   VALUES (NULL, ?, ?, ?, ?, ?, ?, ?)""",
                (new_file_id, sr["sheet_name"], sr["sheet_index"],
                 new_table, sr["row_count"], sr["col_count"], sr["headers_json"]),
            )

    db.commit()
    _log(db, "project.duplicate", f"创建副本「{dup_name}」", project_id=new_id,
         detail=f"source={project_id} work_dir={src.get('work_dir')}")
    return success(store.get_by_id(new_id), 201)


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()