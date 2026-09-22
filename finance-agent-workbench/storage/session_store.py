"""app_sessions 会话计时器 — 工作台总览 D1（v1.2 时间口径定稿）。

本质：软件打开即计时、关闭即结束。每次后端进程启动插一行 open 会话，
atexit 写 end_at；进程被强杀时由下次启动的 _close_stale 兜底收尾，
避免无限长会话。时间口径 = 软件打开会话时长（纯离线，从安装起累计）。

生命周期：
    启动  ──▶ SessionStore.start()   插 {id, start_at, last_seen_at, status=open}
    运行  ──▶ SessionStore.heartbeat() 每 ≥60s 更新 last_seen_at（防强杀丢失）
    退出  ──▶ SessionStore.close()   写 end_at=now, status=closed（幂等）
    强杀  ──▶ 下次启动 _close_stale() 把 end_at IS NULL 的行按 last_seen_at
              （或 start_at）补 end_at, status=stale
"""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone
from sqlite3 import Connection

from config.settings import DB_PATH
from storage._utils import iso_now, row_to_dict


class SessionStore:
    """软件打开会话计时器：start / close / heartbeat / _close_stale。"""

    def __init__(self, db: Connection | None = None) -> None:
        # 持有独立连接：atexit 钩子运行时 request-scoped g.db 已不可用，
        # 且钩子线程（atexit 在同一线程）不依赖 Flask 上下文。
        # check_same_thread=False：dev server 多线程下 before_request 心跳
        # 可能在不同线程执行；WAL 模式支持多线程访问（与 storage/db.py 一致）。
        self.db = db or sqlite3.connect(str(DB_PATH), check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self._last_seen: datetime | None = None  # 心跳节流基准（进程内）

    # ------------------------------------------------------------------
    # 启动计时
    # ------------------------------------------------------------------
    def start(self) -> dict:
        """启动计时：先收尾历史 stale 会话，再插入当前 open 会话。

        当前会话尚未插入，故此时所有 end_at IS NULL 的行都是旧会话，
        直接全部按 last_seen_at（或 start_at）补 end_at。
        """
        self._close_stale()
        now = iso_now()
        session_id = uuid.uuid4().hex
        self.db.execute(
            """INSERT INTO app_sessions (id, start_at, last_seen_at, status)
               VALUES (?, ?, ?, 'open')""",
            (session_id, now, now),
        )
        self.db.commit()
        self._last_seen = datetime.now(timezone.utc)
        row = self.db.execute(
            "SELECT * FROM app_sessions WHERE id = ?", (session_id,)
        ).fetchone()
        return row_to_dict(row)

    # ------------------------------------------------------------------
    # 退出计时
    # ------------------------------------------------------------------
    def close(self, session_id: str) -> dict | None:
        """退出计时：写 end_at = now，标记 closed。幂等（已 closed 不覆盖）。"""
        row = self.db.execute(
            "SELECT * FROM app_sessions WHERE id = ?", (session_id,)
        ).fetchone()
        if row is None or row["end_at"] is not None:
            return None
        self.db.execute(
            """UPDATE app_sessions
               SET end_at = ?, status = 'closed'
               WHERE id = ? AND end_at IS NULL""",
            (iso_now(), session_id),
        )
        self.db.commit()
        row = self.db.execute(
            "SELECT * FROM app_sessions WHERE id = ?", (session_id,)
        ).fetchone()
        return row_to_dict(row)

    # ------------------------------------------------------------------
    # 心跳（崩溃兜底的数据来源）
    # ------------------------------------------------------------------
    def heartbeat(self, session_id: str, *, min_interval_sec: float = 60.0) -> None:
        """心跳：距上次心跳 ≥ min_interval_sec 才更新 last_seen_at。

        只在 open 会话上更新（end_at IS NULL），已关闭/已 stale 不触碰。
        量小（进程内节流），每次请求调用无性能负担。
        """
        now = datetime.now(timezone.utc)
        if self._last_seen is not None:
            delta = (now - self._last_seen).total_seconds()
            if delta < min_interval_sec:
                return
        self._last_seen = now
        self.db.execute(
            """UPDATE app_sessions
               SET last_seen_at = ?
               WHERE id = ? AND end_at IS NULL""",
            (now.isoformat(), session_id),
        )
        self.db.commit()

    # ------------------------------------------------------------------
    # 崩溃兜底
    # ------------------------------------------------------------------
    def _close_stale(self, exclude_id: str | None = None) -> int:
        """把 end_at IS NULL 的旧会话按 last_seen_at（或 start_at）补 end_at，
        标记 stale，返回收尾的行数。防止强杀导致的无限长会话。

        exclude_id：跳过指定会话（当前正在运行的会话不得被收尾）。
        查询场景（D2 dashboard 聚合）调用时传入当前 APP_SESSION_ID。
        """
        rows = self.db.execute(
            "SELECT id, start_at, last_seen_at FROM app_sessions WHERE end_at IS NULL"
        ).fetchall()
        count = 0
        for row in rows:
            if exclude_id and row["id"] == exclude_id:
                continue
            end = row["last_seen_at"] or row["start_at"]
            self.db.execute(
                """UPDATE app_sessions
                   SET end_at = ?, status = 'stale'
                   WHERE id = ? AND end_at IS NULL""",
                (end, row["id"]),
            )
            count += 1
        if count:
            self.db.commit()
        return count
