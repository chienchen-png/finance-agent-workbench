# -*- coding: utf-8 -*-
"""_test_dashboard_d2 — 工作台总览 D2 聚合端点验收测试。

用法：python scripts/_test_dashboard_d2.py
覆盖（设计方案 §八 验收标准 9）：
  1. GET /api/dashboard/summary 各字段存在且类型正确（status/projects/apps/
     usage/time_trend/active_hours/run_status/activity/errors_today）
  2. 会话按天切分正确（含跨午夜会话分别计入两天）
  3. 空库容错（空数组/0，不崩溃）
  4. _close_stale 排除当前会话（exclude_id 不误杀当前 open 会话）
  5. open 会话（end_at 为空）不计入时长统计
"""

import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone

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


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def _mk_test_app(db_path: str):
    """用临时 DB 构建 Flask app（真实 schema + 会话钩子）。

    注意：storage.db.get_db、config.settings 与 storage.session_store 都在
    模块导入时绑定 DB_PATH，必须同时 patch 三个模块，且测试进程结束前
    不恢复（独立进程，无副作用）。
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
    # 准备临时 DB：完整 schema + 种子数据
    # ---------------------------------------------------------------
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    import sqlite3
    from pathlib import Path
    schema = Path(r"d:\Finance Recon Agent\finance-agent-workbench\storage\schema.sql")
    conn = sqlite3.connect(db_path)
    conn.executescript(schema.read_text(encoding="utf-8"))
    conn.commit()

    now = datetime.now(timezone.utc)
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)

    # 种子：模型/供应商/项目/运行/日志/会话
    conn.execute(
        "INSERT INTO model_providers (id, name, api_url, created_at, updated_at) "
        "VALUES ('p1', 'test-provider', 'http://x', ?, ?)", (now.isoformat(), now.isoformat()))
    conn.execute(
        "INSERT INTO models (id, provider_id, name, api_url, type, is_default, status, "
        "created_at, updated_at) VALUES ('m1', 'p1', 'test-model', 'http://x', 'chat', "
        "1, 'available', ?, ?)", (now.isoformat(), now.isoformat()))
    conn.execute(
        "INSERT INTO projects (id, name, work_dir, created_at, updated_at) "
        "VALUES ('proj1', '可见项目A', 'wd', ?, ?)", (now.isoformat(), now.isoformat()))
    conn.execute(
        "INSERT INTO projects (id, name, work_dir, created_at, updated_at) "
        "VALUES ('app1', '__app_recon__', 'wd', ?, ?)", (now.isoformat(), now.isoformat()))

    # runs：1 个完成（今天），1 个进行中（今天）
    conn.execute(
        "INSERT INTO runs (id, project_id, title, status, created_at, updated_at, completed_at) "
        "VALUES ('r1', 'proj1', '任务A', 'completed', ?, ?, ?)",
        ((today + timedelta(hours=9)).isoformat(),
         (today + timedelta(hours=9, minutes=2)).isoformat(),
         (today + timedelta(hours=9, minutes=2)).isoformat()))
    conn.execute(
        "INSERT INTO runs (id, project_id, title, status, created_at, updated_at) "
        "VALUES ('r2', 'app1', '任务B', 'running', ?, ?)",
        ((today + timedelta(hours=10)).isoformat(),
         (today + timedelta(hours=10)).isoformat()))

    # local_logs：1 success + 1 error（今天）
    conn.execute(
        "INSERT INTO local_logs (project_id, event_type, event_summary, status, created_at) "
        "VALUES ('proj1', 'project.create', '创建项目', 'success', ?)",
        ((today + timedelta(hours=8)).isoformat(),))
    conn.execute(
        "INSERT INTO local_logs (project_id, event_type, event_summary, status, created_at) "
        "VALUES ('proj1', 'run.failed', '任务失败', 'error', ?)",
        ((today + timedelta(hours=8, minutes=30)).isoformat(),))

    # app_sessions：3 条
    #  s1: 昨天 23:30 → 今天 00:30（跨午夜，昨天 30 分钟 + 今天 30 分钟）
    conn.execute(
        "INSERT INTO app_sessions (id, start_at, end_at, status) VALUES "
        "('s1', ?, ?, 'closed')",
        ((today - timedelta(minutes=30)).isoformat(),
         (today + timedelta(minutes=30)).isoformat()))
    #  s2: 今天 08:00 → 今天 08:45（今天 45 分钟）
    conn.execute(
        "INSERT INTO app_sessions (id, start_at, end_at, status) VALUES "
        "('s2', ?, ?, 'closed')",
        ((today + timedelta(hours=8)).isoformat(),
         (today + timedelta(hours=8, minutes=45)).isoformat()))
    #  s3: 今天 open（end_at 为空，不应计入时长）
    conn.execute(
        "INSERT INTO app_sessions (id, start_at, status) VALUES ('s3', ?, 'open')",
        ((today + timedelta(hours=11)).isoformat(),))
    conn.commit()
    conn.close()

    flask_app = _mk_test_app(db_path)

    # ---------------------------------------------------------------
    # 1. 端点整体 + 字段断言
    # ---------------------------------------------------------------
    print("== 1. 端点整体与字段 ==")
    client = flask_app.test_client()
    resp = client.get("/api/dashboard/summary")
    data = resp.get_json()
    check("HTTP 200", resp.status_code == 200, str(resp.status_code))
    check("success=true", data.get("success") is True, str(data))
    d = data.get("data") or {}
    for field in ("ts", "status", "projects", "apps", "usage", "time_trend",
                  "active_hours", "run_status", "activity", "errors_today"):
        check(f"data.{field} 存在", field in d, str(d.keys()))

    # status
    st = d["status"]
    check("status.backend_ok", st.get("backend_ok") is True)
    check("status.default_model", st.get("default_model") == "test-model",
          str(st))
    check("status.available_model_count", st.get("available_model_count") == 1,
          str(st))
    check("status.model_provider_count", st.get("model_provider_count") == 1,
          str(st))

    # projects
    pr = d["projects"]
    check("projects.total=1（排除 __app_）", pr.get("total") == 1, str(pr))
    check("projects.app_count=1", pr.get("app_count") == 1, str(pr))
    check("projects.recent 长度", isinstance(pr.get("recent"), list) and len(pr["recent"]) <= 5)
    if pr.get("recent"):
        check("projects.recent[0].run_count", pr["recent"][0].get("run_count") == 1,
              str(pr["recent"]))

    # apps
    apps = d["apps"]
    check("apps 含 2 个应用", isinstance(apps, list) and len(apps) == 2, str(apps))
    recon = next((a for a in apps if a["id"] == "app-sales-check"), None)
    check("apps.app-sales-check.runs>=1", recon is not None and recon.get("runs") == 1,
          str(recon))

    # usage（会话口径）
    us = d["usage"]
    # 今天：s1 落今天 30 分钟 + s2 45 分钟 = 75 分钟 = 4500s，
    # 再加当前 open 会话（create_app 启动→now，几秒内）→ 容差断言
    base = 4500
    got_today = us.get("today_duration_sec")
    check("usage.today_duration_sec≈4500（s1 30m+s2 45m+当前open）",
          base <= got_today < base + 120,
          f"got={got_today} expect∈[{base},{base+120})")
    # 昨天：s1 落昨天 30 分钟 = 1800s（不含当前会话）
    check("usage.yesterday_duration_sec=1800（s1 昨天 30m）",
          us.get("yesterday_duration_sec") == 1800,
          f"got={us.get('yesterday_duration_sec')}")
    check("usage.today_runs=2", us.get("today_runs") == 2, str(us))
    check("usage.today_success=1", us.get("today_success") == 1, str(us))
    check("usage.today_failed=0（runs failed 计数）", us.get("today_failed") == 0, str(us))

    # 2. 时间趋势按天切分
    print("== 2. 时间趋势按天切分 ==")
    trend = d["time_trend"]
    check("time_trend 长度=7", isinstance(trend, list) and len(trend) == 7, str(len(trend)))
    day_map = {t["day"]: t for t in trend}
    today_str = today.strftime("%Y-%m-%d")
    yesterday_str = (today - timedelta(days=1)).strftime("%Y-%m-%d")
    got_today_dur = day_map.get(today_str, {}).get("duration_sec")
    check("今日 trend.duration_sec≈4500（含当前open）",
          base <= got_today_dur < base + 120, str(day_map.get(today_str)))
    check("昨日 trend.duration_sec=1800", day_map.get(yesterday_str, {}).get("duration_sec") == 1800,
          str(day_map.get(yesterday_str)))
    check("今日 trend.sessions=2（s2 今早开始 + 当前会话）",
          day_map.get(today_str, {}).get("sessions") == 2,
          str(day_map.get(today_str)))

    # 3. 活跃时段
    print("== 3. 活跃时段 ==")
    ah = d["active_hours"]
    check("active_hours 长度=24", isinstance(ah, list) and len(ah) == 24, str(len(ah)))
    h8 = next((x for x in ah if x["hour"] == 8), None)
    check("active_hours hour=8 sessions>=1", h8 is not None and h8["sessions"] >= 1, str(h8))

    # 4. run_status + activity + errors_today
    print("== 4. run_status / activity / errors_today ==")
    rs = d["run_status"]
    check("run_status 含 completed", any(x["status"] == "completed" for x in rs), str(rs))
    act = d["activity"]
    check("activity 长度<=10", isinstance(act, list) and 0 < len(act) <= 10, str(len(act)))
    run_item = next((x for x in act if x["type"] == "run" and x["status"] == "completed"), None)
    check("activity completed run 条目含 duration_sec=120", run_item is not None
          and run_item.get("duration_sec") == 120, str(run_item))
    check("activity log 条目含 status", any(x["type"] == "log" and x["status"] == "failed"
          for x in act), str(act))
    check("errors_today=1（local_logs error）", d.get("errors_today") == 1,
          str(d.get("errors_today")))

    # 5. _close_stale 排除当前会话
    print("== 5. _close_stale exclude_id ==")
    from storage.session_store import SessionStore
    store = SessionStore(sqlite3.connect(db_path))
    cur = sqlite3.connect(db_path)
    cur.row_factory = sqlite3.Row
    # 当前会话 open 行（模拟 APP_SESSION_ID）
    cur.execute("INSERT INTO app_sessions (id, start_at, status) VALUES ('cur1', ?, 'open')",
                (now.isoformat(),))
    cur.commit()
    n = store._close_stale(exclude_id="cur1")
    row = cur.execute("SELECT status, end_at FROM app_sessions WHERE id='cur1'").fetchone()
    check("exclude_id 不误杀当前会话", n >= 0 and row["status"] == "open" and row["end_at"] is None,
          f"n={n} row={dict(row)}")
    # 其他 open 行被收尾
    row3 = cur.execute("SELECT status, end_at FROM app_sessions WHERE id='s3'").fetchone()
    check("s3（非当前 open）被收尾为 stale", row3["status"] == "stale" and row3["end_at"] is not None,
          str(dict(row3)))
    cur.close()

    # 6. 空库容错
    print("== 6. 空库容错 ==")
    fd2, empty_path = tempfile.mkstemp(suffix=".db")
    os.close(fd2)
    conn2 = sqlite3.connect(empty_path)
    conn2.executescript(schema.read_text(encoding="utf-8"))
    conn2.commit()
    conn2.close()
    empty_app = _mk_test_app(empty_path)
    resp2 = empty_app.test_client().get("/api/dashboard/summary")
    d2 = (resp2.get_json() or {}).get("data") or {}
    check("空库 HTTP 200", resp2.status_code == 200, str(resp2.status_code))
    check("空库 projects.total=0", d2.get("projects", {}).get("total") == 0, str(d2.get("projects")))
    check("空库 usage.today_duration_sec=0", d2.get("usage", {}).get("today_duration_sec") == 0,
          str(d2.get("usage")))
    check("空库 activity=[]", d2.get("activity") == [], str(d2.get("activity")))

    # 清理
    for p in (db_path, empty_path):
        try:
            os.remove(p)
        except OSError:
            pass

    print("-" * 60)
    print(f"D2 验收结果：{PASS} PASS / {len(FAIL)} FAIL")
    for f in FAIL:
        print(f"  FAILED: {f}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
