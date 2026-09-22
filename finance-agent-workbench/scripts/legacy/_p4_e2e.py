# -*- coding: utf-8 -*-
"""P4 端到端联调：financial-modeling Skill 三模式全自动验证。

在「测试」项目上，用 deepseek-v4-flash + auto 工作模式跑 3 个用例：
  模式 A：数据需求建议（无数据建模诉求）
  模式 B：已有数据建模（用库内销售提成汇总表）
  模式 C：知识讲解（杜邦公式）

全自动：发起 run → 轮询 events → 遇 ask_user 自动应答 → 收集最终答案 → 校验特征。

运行: python scripts/_p4_e2e.py
"""
from __future__ import annotations

import json
import sys
import time
import urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

BASE = "http://127.0.0.1:8080"
PROJECT_ID = "a10a3d71ae51420fa4d396565d9f11bd"          # 测试
MODEL_ID = "provider_deepseek_deepseek_v4_flash"          # deepseek-v4-flash
AGENT = "general-agent"
WORK_MODE = "auto"

FAIL = []


def _post(path: str, payload: dict):
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _get(path: str):
    with urllib.request.urlopen(BASE + path, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def check(label: str, ok: bool, detail: str = "") -> None:
    print(("PASS" if ok else "FAIL"), label, detail)
    if not ok:
        FAIL.append(label)


def run_case(name: str, prompt: str, expect: list, timeout_s: int = 600) -> str:
    """发起一次 run，全自动应答 ask_user，返回最终答案文本。"""
    print(f"\n{'='*60}\n用例: {name}\n输入: {prompt[:120]}\n{'='*60}")
    resp = _post("/api/workspace/run", {
        "prompt": prompt,
        "project_id": PROJECT_ID,
        "agent": AGENT,
        "model": MODEL_ID,
        "engine": "smol",
        "work_mode": WORK_MODE,
    })
    run_id = (resp.get("data") or {}).get("run_id") or resp.get("run_id", "")
    if not run_id:
        print("FAIL 发起 run 失败:", resp)
        FAIL.append(name + ":发起失败")
        return ""
    print("run_id:", run_id)

    answer = ""
    last_seq = 0
    t0 = time.time()
    answered = set()
    while time.time() - t0 < timeout_s:
        try:
            st = _get(f"/api/workspace/status?run_id={run_id}")["data"]
            status = st.get("status", "")
        except Exception as e:
            print("status err:", e)
            status = "running"
        ev = _get(f"/api/workspace/events?run_id={run_id}&after_seq={last_seq}")
        ev_data = ev.get("data") or {}
        last_seq = ev_data.get("last_seq", last_seq)
        for e in ev_data.get("events", []):
            etype = e.get("type", "")
            pl = e.get("payload") or {}
            if etype == "message_delta":
                answer += pl.get("text") or pl.get("delta") or ""
            elif etype == "user_input_required":
                iid = pl.get("interaction_id") or pl.get("tool_call_id") or ""
                if iid and iid not in answered:
                    answered.add(iid)
                    itype = pl.get("input_type", "text")
                    opts = pl.get("options") or []
                    q = (pl.get("question") or "")[:60]
                    # 自动应答：select 选第一个；confirm 选是；text 填默认
                    if itype == "select":
                        ans = opts[0] if opts else "第一个"
                        if pl.get("multi_select"):
                            ans = "、".join(opts[:2]) if opts else "全部"
                    elif itype == "confirm":
                        ans = "是"
                    else:
                        ans = "按你的专业建议执行"
                    print(f"  [auto-answer] {itype}: {q} -> {ans}")
                    _post(f"/api/interactions/{iid}/respond",
                          {"response": ans, "cancelled": False})
        if status in ("completed", "stopped", "failed"):
            break
        time.sleep(1.5)

    if not answer:
        print("FAIL 无最终答案，status=", status)
        FAIL.append(name + ":无答案")
        return ""
    # 特征校验
    for label, kw, mode in expect:
        hit = (kw in answer) if mode == "in" else (kw not in answer)
        check(f"{name}: {label}", hit, f"关键字={kw[:40]}")
    return answer


def main() -> None:
    # 模式 A：数据需求建议
    run_case(
        "模式A-数据需求",
        "我想做明年的收入预测，但还没有数据。请告诉我需要准备哪些数据。",
        [("输出数据需求建议", "数据", "in"),
         ("提示字段/格式准备", "按月", "in"),
         ("给出优先级/后续可做分析", "趋势", "in")],
    )

    # 模式 B：已有数据建模（销售提成汇总表 2021-2026）
    run_case(
        "模式B-销售预测",
        "用项目里【销售提成汇总表2021-2026】的数据做一次销售分析："
        "先看整体回款趋势，再做相关性分析看哪些因素和回款金额相关，"
        "最后输出带数据表的趋势图表。",
        [("调用分析（回款/趋势）", "回款", "in"),
         ("产出图表 JSON", "chart-json", "in"),
         ("带数据表", "data_table", "in")],
        timeout_s=900,
    )

    # 模式 C：知识讲解
    run_case(
        "模式C-杜邦讲解",
        "杜邦分析的公式是什么？怎么计算？请讲解一下。",
        [("输出公式", "$$", "in"),
         ("变量含义表", "含义", "in"),
         ("提到 ROE", "ROE", "in")],
    )

    # 汇总
    print("\n" + "=" * 60)
    if FAIL:
        print("FAIL 失败项:", FAIL)
        sys.exit(1)
    print("全部用例通过 ✅")


if __name__ == "__main__":
    main()
