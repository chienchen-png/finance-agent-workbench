"""dashboard.py — 工作台总览（Dashboard / 数据大屏）聚合端点（D2）。

设计文档：`docs/工作台总览设计方案.md` §3.1
一次调用返回大屏全部数据（避免前端 N 次请求）：
  status / projects / apps / usage（会话时长主指标）/ time_trend /
  active_hours / run_status / activity / errors_today

实现要点（v1.2 会话计时器口径）：
  - 时间主指标来自 app_sessions（软件打开会话时长），Python 逐会话按天切分
  - 查询前先 _close_stale()（排除当前 APP_SESSION_ID），避免无限长会话
  - 每子查询独立 try/except 容错，任何失败返回空数组/0，不阻塞整体
  - 零 token_usage / 零智能体依赖（v1.1 评审确认去掉 Token/智能体统计）
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from flask import Blueprint, current_app, request

from routes._utils import success
from storage._utils import iso_now
from storage.db import get_db
from storage.session_store import SessionStore

logger = logging.getLogger(__name__)

dashboard_bp = Blueprint("dashboard_api", __name__, url_prefix="/api/dashboard")

# 集成应用入口（与前端 NavSidebar APP_NAV / 隐藏项目命名约定一致）
_APPS = [
    {
        "id": "app-sales-check",
        "name": "数据核对与校验",
        "project_name": "__app_recon__",
        "desc": "两表金额核对与审计（确定性核对 + LLM 报告）",
    },
    {
        "id": "app-finmod",
        "name": "财务建模与分析",
        "project_name": "__app_finmod__",
        "desc": "AI 引导式财务建模：多文件合并 + 宏观建模 + 报告生成",
    },
]

# runs 终态（completed_at 非空才计入任务耗时）
_TERMINAL_STATUSES = ("completed", "stopped", "failed")


def _parse_ts(text: str | None) -> datetime | None:
    """ISO-8601 → aware UTC datetime（会话 start/end 均为 iso_now UTC）。"""
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _day_start(dt: datetime) -> datetime:
    """UTC 日边界（与 token_store date('now') 口径一致）。"""
    return dt.replace(hour=0, minute=0, second=0, microsecond=0)


def _all_sessions(db) -> list[dict]:
    """读取全部会话并解析时间戳。

    已结束会话（closed/stale）用 end_at；当前 open 会话（end_at 为空，
    即正在运行的会话）用**当前时间**作临时 end——「打开即计时」口径，
    今日时长/趋势包含进行中的会话（否则大屏打开时今日时长恒为 0）。
    """
    now = _utc_now()
    sessions = []
    rows = db.execute(
        "SELECT start_at, end_at FROM app_sessions WHERE end_at IS NOT NULL "
        "OR status = 'open'"
    ).fetchall()
    for row in rows:
        start = _parse_ts(row["start_at"])
        end = _parse_ts(row["end_at"]) or now
        if start is None or end is None or end <= start:
            continue
        sessions.append({"start": start, "end": end})
    return sessions


def _split_day_slices(start: datetime, end: datetime) -> list[tuple[datetime, datetime, datetime]]:
    """把一个会话切分为逐日片段 [(day_start, seg_start, seg_end), ...]。

    跨午夜会话分别计入两天：min(end, 次日00:00) − max(start, 当日00:00)。
    day_start 为 UTC 日边界（与 date('now') 一致）。
    """
    slices: list[tuple[datetime, datetime, datetime]] = []
    cursor = start
    while cursor < end:
        ds = _day_start(cursor)
        next_day = ds + timedelta(days=1)
        seg_end = min(end, next_day)
        slices.append((ds, cursor, seg_end))
        cursor = next_day
    return slices


def _duration_in_window(sessions: list[dict], win_start: datetime, win_end: datetime) -> int:
    """返回落在 [win_start, win_end) 窗口内的会话时长之和（秒）。"""
    total = 0
    for s in sessions:
        if s["end"] <= win_start or s["start"] >= win_end:
            continue
        for _ds, seg_start, seg_end in _split_day_slices(s["start"], s["end"]):
            # 该日片段与窗口求交
            a = max(seg_start, win_start)
            b = min(seg_end, win_end)
            if b > a:
                total += int((b - a).total_seconds())
    return total


def _sessions_count_in_window(sessions: list[dict], win_start: datetime, win_end: datetime) -> int:
    """窗口内「开始于窗口内」的会话数（打开次数口径）。"""
    return sum(1 for s in sessions if win_start <= s["start"] < win_end)


def _avg_session_duration(sessions: list[dict], days: int) -> int:
    """近 N 天会话时长均值（秒）；无会话返回 0。"""
    now = _utc_now()
    start = _day_start(now) - timedelta(days=days - 1)
    end = _day_start(now) + timedelta(days=1)
    durations = [int((s["end"] - s["start"]).total_seconds())
                 for s in sessions if start <= s["start"] < end]
    if not durations:
        return 0
    return round(sum(durations) / len(durations))


def _run_count_in_day(db, day_offset: int) -> int:
    """偏移 day_offset 天的运行次数（0=今天，1=昨天）。"""
    row = db.execute(
        """SELECT COUNT(*) AS c FROM runs
           WHERE date(created_at) = date('now', ?)""",
        (f"-{day_offset} days",),
    ).fetchone()
    return int(row["c"]) if row else 0


# ------------------------------------------------------------------
# 各子查询（独立容错）
# ------------------------------------------------------------------
def _status_snapshot(db) -> dict:
    try:
        default = db.execute(
            "SELECT name FROM models WHERE is_default = 1 LIMIT 1"
        ).fetchone()
        provider = db.execute(
            "SELECT COUNT(*) AS c FROM model_providers"
        ).fetchone()
        avail = db.execute(
            "SELECT COUNT(*) AS c FROM models WHERE status = 'available'"
        ).fetchone()
        skill_count = 0
        try:
            from agent.skill_loader import list_skills
            skill_count = len(list_skills())
        except Exception:
            pass
        return {
            "backend_ok": True,
            "default_model": default["name"] if default else "",
            "model_provider_count": int(provider["c"]) if provider else 0,
            "available_model_count": int(avail["c"]) if avail else 0,
            "skill_count": skill_count,
        }
    except Exception:
        logger.exception("dashboard status_snapshot failed")
        return {"backend_ok": False, "default_model": "",
                "model_provider_count": 0, "available_model_count": 0, "skill_count": 0}


def _projects_summary(db, limit: int = 5) -> dict:
    try:
        rows = db.execute(
            "SELECT id, name, description, default_model, updated_at FROM projects ORDER BY updated_at DESC"
        ).fetchall()
        visible = [dict(r) for r in rows
                   if not str(r["name"] or "").startswith("__app_")]
        app_count = sum(1 for r in rows if str(r["name"] or "").startswith("__app_"))
        # 可见项目 run_count（按 project_id 聚合）
        run_counts: dict[str, int] = {}
        for r in db.execute("SELECT project_id, COUNT(*) AS c FROM runs GROUP BY project_id"):
            run_counts[r["project_id"]] = int(r["c"])
        recent = []
        for p in visible[:limit]:
            item = dict(p)
            item["run_count"] = run_counts.get(item["id"], 0)
            recent.append(item)
        return {"total": len(visible), "app_count": app_count, "recent": recent}
    except Exception:
        logger.exception("dashboard projects_summary failed")
        return {"total": 0, "app_count": 0, "recent": []}


def _apps_summary(db) -> list[dict]:
    """应用入口卡：含应用内 run 数 + 任务累计耗时（终态 completed_at）。"""
    try:
        # 隐藏应用项目 id → name 映射
        proj_map: dict[str, str] = {}
        for r in db.execute("SELECT id, name FROM projects WHERE name LIKE '__app_%'"):
            proj_map[r["name"]] = r["id"]
        result = []
        for spec in _APPS:
            pid = proj_map.get(spec["project_name"])
            runs = 0
            duration_sec = 0
            if pid:
                run_row = db.execute(
                    "SELECT COUNT(*) AS c FROM runs WHERE project_id = ?", (pid,)
                ).fetchone()
                runs = int(run_row["c"]) if run_row else 0
                dur_row = db.execute(
                    """SELECT COALESCE(SUM(
                           (julianday(completed_at) - julianday(created_at)) * 86400), 0) AS d
                       FROM runs WHERE project_id = ? AND completed_at IS NOT NULL""",
                    (pid,),
                ).fetchone()
                duration_sec = int(round(dur_row["d"])) if dur_row and dur_row["d"] else 0
            result.append({
                "id": spec["id"],
                "name": spec["name"],
                "desc": spec["desc"],
                "runs": runs,
                "duration_sec": duration_sec,
            })
        return result
    except Exception:
        logger.exception("dashboard apps_summary failed")
        return []


def _usage_summary(db, sessions: list[dict], days: int) -> dict:
    try:
        now = _utc_now()
        today = _day_start(now)
        tomorrow = today + timedelta(days=1)
        yesterday = today - timedelta(days=1)
        # 会话口径（主指标）
        today_duration = _duration_in_window(sessions, today, tomorrow)
        yesterday_duration = _duration_in_window(sessions, yesterday, today)
        sessions_7d = _sessions_count_in_window(
            sessions, today - timedelta(days=days - 1), tomorrow)
        avg_duration = _avg_session_duration(sessions, days)
        # 任务口径（补充）
        today_runs = _run_count_in_day(db, 0)
        yesterday_runs = _run_count_in_day(db, 1)
        today_success = int(db.execute(
            """SELECT COUNT(*) AS c FROM runs
               WHERE date(created_at) = date('now') AND status = 'completed'"""
        ).fetchone()["c"])
        today_failed = int(db.execute(
            """SELECT COUNT(*) AS c FROM runs
               WHERE date(created_at) = date('now') AND status = 'failed'"""
        ).fetchone()["c"])
        return {
            "today_duration_sec": today_duration,
            "yesterday_duration_sec": yesterday_duration,
            "today_runs": today_runs,
            "yesterday_runs": yesterday_runs,
            "today_success": today_success,
            "today_failed": today_failed,
            "avg_duration_sec": avg_duration,
            "avg_runs_per_day": round(today_runs / days, 1) if days else 0,
            "sessions_7d": sessions_7d,
        }
    except Exception:
        logger.exception("dashboard usage_summary failed")
        return {"today_duration_sec": 0, "yesterday_duration_sec": 0,
                "today_runs": 0, "yesterday_runs": 0, "today_success": 0,
                "today_failed": 0, "avg_duration_sec": 0, "avg_runs_per_day": 0,
                "sessions_7d": 0}


def _time_trend(db, sessions: list[dict], days: int) -> list[dict]:
    """7 日使用时长趋势：逐日 {day, duration_sec, sessions}（含 0 的天，旧→新）。"""
    try:
        today = _day_start(_utc_now())
        trend = []
        for offset in range(days - 1, -1, -1):
            ds = today - timedelta(days=offset)
            de = ds + timedelta(days=1)
            trend.append({
                "day": ds.strftime("%Y-%m-%d"),
                "duration_sec": _duration_in_window(sessions, ds, de),
                "sessions": _sessions_count_in_window(sessions, ds, de),
            })
        return trend
    except Exception:
        logger.exception("dashboard time_trend failed")
        return []


def _active_hours(db, sessions: list[dict], days: int) -> list[dict]:
    """活跃时段分布：近 N 天按会话开始小时分组（24h 全量补 0）。"""
    try:
        today = _day_start(_utc_now())
        start = today - timedelta(days=days - 1)
        buckets = {h: {"hour": h, "sessions": 0, "duration_sec": 0} for h in range(24)}
        for s in sessions:
            if s["start"] < start or s["start"] >= today + timedelta(days=1):
                continue
            h = s["start"].hour
            buckets[h]["sessions"] += 1
            # 该会话落在近 N 天窗口内的总时长计入开始小时
            for _ds, seg_start, seg_end in _split_day_slices(s["start"], s["end"]):
                a = max(seg_start, start)
                b = min(seg_end, today + timedelta(days=1))
                if b > a:
                    buckets[h]["duration_sec"] += int((b - a).total_seconds())
        return [buckets[h] for h in range(24)]
    except Exception:
        logger.exception("dashboard active_hours failed")
        return [{"hour": h, "sessions": 0, "duration_sec": 0} for h in range(24)]


def _run_status(db, days: int) -> list[dict]:
    try:
        rows = db.execute(
            """SELECT status, COUNT(*) AS c FROM runs
               WHERE created_at >= datetime('now', ?)
               GROUP BY status ORDER BY c DESC""",
            (f"-{days} days",),
        ).fetchall()
        return [{"status": r["status"], "count": int(r["c"])} for r in rows]
    except Exception:
        logger.exception("dashboard run_status failed")
        return []


def _activity_feed(db, limit: int = 10) -> list[dict]:
    """最近活动流：local_logs + runs 合并，按时间倒序，每条含单次耗时。"""
    try:
        items: list[dict] = []
        # runs（任务维度，含耗时）
        for r in db.execute(
            "SELECT id, project_id, title, status, created_at, completed_at, "
            "progress_message, error_message FROM runs "
            "ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ):
            dur = None
            start = _parse_ts(r["created_at"])
            end = _parse_ts(r["completed_at"])
            if start and end and end > start:
                dur = int((end - start).total_seconds())
            status = r["status"] if r["status"] in _TERMINAL_STATUSES else "running"
            items.append({
                "ts": r["created_at"],
                "type": "run",
                "title": (r["title"] or "").split("\n")[0][:80] or "运行任务",
                "status": status,
                "run_id": r["id"],
                "project_id": r["project_id"],
                "duration_sec": dur,
                "detail": (r["error_message"] or r["progress_message"] or "")[:200],
            })
        # local_logs（事件维度）
        for r in db.execute(
            "SELECT project_id, event_type, event_summary, status, detail, created_at "
            "FROM local_logs ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ):
            log_status = "failed" if r["status"] in ("error", "failed") else "success"
            items.append({
                "ts": r["created_at"],
                "type": "log",
                "title": r["event_summary"] or r["event_type"],
                "status": log_status,
                "run_id": None,
                "project_id": r["project_id"],
                "duration_sec": None,
                "detail": (r["detail"] or "")[:200],
            })
        items.sort(key=lambda x: x["ts"], reverse=True)
        return items[:limit]
    except Exception:
        logger.exception("dashboard activity_feed failed")
        return []


def _errors_today(db) -> int:
    try:
        row = db.execute(
            """SELECT COUNT(*) AS c FROM local_logs
               WHERE status IN ('error', 'failed') AND date(created_at) = date('now')"""
        ).fetchone()
        return int(row["c"]) if row else 0
    except Exception:
        logger.exception("dashboard errors_today failed")
        return 0


# ------------------------------------------------------------------
# GET /api/dashboard/summary?days=7&limit=10
# ------------------------------------------------------------------
@dashboard_bp.get("/summary")
def dashboard_summary():
    """一次调用返回大屏全部数据（容错，任何子查询失败返回空数组/0）。"""
    try:
        days = max(1, min(int(request.args.get("days", 7)), 90))
        limit = max(1, min(int(request.args.get("limit", 10)), 50))
    except (TypeError, ValueError):
        days, limit = 7, 10

    db = get_db()
    # 会话收尾兜底：收尾旧 open 会话，但排除当前会话（方案 §3.1）
    current_sid = current_app.config.get("APP_SESSION_ID", "")
    try:
        SessionStore(db)._close_stale(exclude_id=current_sid)
    except Exception:
        logger.exception("dashboard close_stale failed")

    sessions = _all_sessions(db)

    data = {
        "ts": iso_now(),
        "status": _status_snapshot(db),
        "projects": _projects_summary(db),
        "apps": _apps_summary(db),
        "usage": _usage_summary(db, sessions, days),
        "time_trend": _time_trend(db, sessions, days),
        "active_hours": _active_hours(db, sessions, days),
        "run_status": _run_status(db, days),
        "activity": _activity_feed(db, limit),
        "errors_today": _errors_today(db),
    }
    return success(data)
