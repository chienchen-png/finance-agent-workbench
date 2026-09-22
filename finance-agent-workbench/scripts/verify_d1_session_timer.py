"""D1 会话计时器验收验证（临时 DB，不污染主库）。

验证三场景（设计方案 §九 验收标准）：
  1. 启动后表有 open 会话（start 插入 open 行）
  2. 退出后 end_at 写入（close 幂等写 end_at=closed）
  3. 强杀后下次启动 stale 收尾（_close_stale 补 end_at=stale）

用法：python scripts/verify_d1_session_timer.py
"""
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from storage.session_store import SessionStore

SCHEMA = ROOT / "storage" / "schema.sql"


def make_db() -> tuple[sqlite3.Connection, str]:
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA.read_text(encoding="utf-8"))
    conn.commit()
    return conn, path


def main() -> int:
    failures = 0

    # ---- 场景 1 + 2：启动 open / 正常退出 closed ----
    conn, path = make_db()
    store = SessionStore(conn)
    s1 = store.start()
    row = conn.execute(
        "SELECT status, start_at, end_at FROM app_sessions WHERE id = ?", (s1["id"],)
    ).fetchone()
    ok = row["status"] == "open" and row["start_at"] and row["end_at"] is None
    print(f"[场景1 启动open]  status={row['status']}  start={row['start_at']}  -> {'PASS' if ok else 'FAIL'}")
    failures += 0 if ok else 1

    # 同一连接再 start（模拟重启），上一会话应先被 stale 收尾
    s2 = store.start()
    row1 = conn.execute(
        "SELECT status, end_at FROM app_sessions WHERE id = ?", (s1["id"],)
    ).fetchone()
    ok = row1["status"] == "stale" and row1["end_at"] is not None
    print(f"[场景3 强杀stale]  上一会话 status={row1['status']}  end_at={row1['end_at']}  -> {'PASS' if ok else 'FAIL'}")
    failures += 0 if ok else 1

    closed = store.close(s2["id"])
    ok = closed is not None and closed["status"] == "closed" and closed["end_at"]
    print(f"[场景2 退出closed]  status={closed['status']}  end_at={closed['end_at']}  -> {'PASS' if ok else 'FAIL'}")
    failures += 0 if ok else 1

    # 幂等：重复 close 不覆盖
    closed_again = store.close(s2["id"])
    ok = closed_again is None
    print(f"[场景2 幂等close]  重复 close 返回 None  -> {'PASS' if ok else 'FAIL'}")
    failures += 0 if ok else 1

    # 心跳：不触碰已关闭会话
    store.heartbeat(s2["id"])
    row2 = conn.execute(
        "SELECT last_seen_at FROM app_sessions WHERE id = ?", (s2["id"],)
    ).fetchone()
    ok = row2["last_seen_at"] == closed["last_seen_at"]
    print(f"[心跳 已关不碰]  last_seen_at 未变化 -> {'PASS' if ok else 'FAIL'}")
    failures += 0 if ok else 1

    # 心跳：强制更新 open 会话 last_seen_at（min_interval_sec=0 绕过节流）
    store.heartbeat(s1["id"], min_interval_sec=0)
    row3 = conn.execute(
        "SELECT last_seen_at FROM app_sessions WHERE id = ?", (s1["id"],)
    ).fetchone()
    ok = row3["last_seen_at"] is not None and row3["last_seen_at"] >= row["start_at"]
    print(f"[心跳 open更新]  last_seen_at={row3['last_seen_at']} -> {'PASS' if ok else 'FAIL'}")
    failures += 0 if ok else 1

    conn.close()
    os.remove(path)

    print("-" * 60)
    print(f"D1 验收结果：{'全部通过' if failures == 0 else f'{failures} 项失败'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
