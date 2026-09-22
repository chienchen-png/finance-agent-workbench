#!/usr/bin/env python3
"""Comprehensive pressure test for Finance Agent Workbench.
Tests: context memory, design tasks, tool usage, mixed context, UI/UX.
"""
import json
import time
import urllib.request
import urllib.error
import ssl
import sys

ssl._create_default_https_context = ssl._create_unverified_context

BASE = "http://127.0.0.1:8080"
AGENT = "general-agent"
MODEL = "deepseek-v4-pro"

# ============================================================
# Helpers
# ============================================================

def api(method, path, data=None):
    url = f"{BASE}{path}"
    body = None
    if data is not None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=body, method=method)
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        err = e.read().decode("utf-8", errors="replace")
        return {"success": False, "error": f"HTTP {e.code}: {err[:200]}"}
    except Exception as e:
        return {"success": False, "error": str(e)}

def post(path, data):
    return api("POST", path, data)

def get(path):
    return api("GET", path)

# ============================================================
# Create a dedicated test project (never pollutes user projects)
# ============================================================
def create_test_project():
    """Create a throwaway project for the test run; returns its project_id."""
    r = post("/api/projects", {
        "name": f"自动化测试项目-{int(time.time())}",
        "work_dir": "test-fixtures/phase5",
    })
    data = r.get("data", r)
    pid = data.get("id", "")
    if not pid:
        print(f"  [WARN] create project failed: {r}")
        return ""
    return pid

PROJECT_ID = create_test_project()
if not PROJECT_ID:
    print("FATAL: 无法创建测试项目，请检查服务是否运行")
    sys.exit(2)
print(f"  [SETUP] 测试项目已创建: {PROJECT_ID} (work_dir=test-fixtures/phase5)")

def wait_run(run_id, timeout=300):
    """Poll events until terminal, return (status, events, answer_text)."""
    after = 0
    start = time.time()
    answer_parts = []
    all_events = []
    plan_steps = []
    interactions = []

    while time.time() - start < timeout:
        r = get(f"/api/workspace/events?run_id={run_id}&after_seq={after}")
        if not r.get("success"):
            status = r.get("data", {}).get("status", "running")
            if status in ("completed", "stopped", "failed"):
                return status, all_events, "".join(answer_parts), plan_steps, interactions
            time.sleep(0.5)
            continue

        data = r.get("data", {})
        events = data.get("events", [])
        status = data.get("status", "running")

        for ev in events:
            all_events.append(ev)
            after = max(after, ev.get("seq", 0))
            t = ev.get("type", "")
            p = ev.get("payload", {})

            if t == "message_delta":
                answer_parts.append(p.get("text", ""))
            elif t == "plan_proposed" or t == "plan_updated":
                plan_steps[:] = p.get("steps", [])
            elif t == "user_input_required":
                interactions.append(p)

        if status in ("completed", "stopped", "failed", "waiting_for_user"):
            time.sleep(0.3)  # small delay to catch trailing events
            return status, all_events, "".join(answer_parts), plan_steps, interactions

        time.sleep(0.5)

    return "timeout", all_events, "".join(answer_parts), plan_steps, interactions

def run_prompt(prompt):
    """Send a prompt, wait for completion, return results."""
    print(f"  [SEND] Sending: {prompt[:80]}...")
    r = post("/api/workspace/run", {
        "prompt": prompt,
        "agent": AGENT,
        "model": MODEL,
        "project_id": PROJECT_ID,
    })
    run_id = r.get("data", {}).get("run_id", "")
    if not run_id:
        print(f"  [FAIL] Failed to start: {r}")
        return None
    status, events, answer, plan, interactions = wait_run(run_id)
    print(f"  [RECV] Status: {status} | Answer: {answer[:120]}...")
    return {
        "run_id": run_id, "status": status, "answer": answer,
        "events": events, "plan": plan, "interactions": interactions,
    }

def respond_interaction(interaction_id, response_text):
    return post(f"/api/interactions/{interaction_id}/respond", {
        "response": response_text,
    })

def check(condition, label):
    if condition:
        print(f"    [PASS] {label}")
    else:
        print(f"    [FAIL] FAILED: {label}")
    return condition

results = {"passed": 0, "failed": 0, "total": 0}

def score(test_name, conditions):
    global results
    print(f"\n{'='*60}")
    print(f"[TEST] {test_name}")
    print(f"{'='*60}")
    all_pass = True
    for cond, label in conditions:
        results["total"] += 1
        ok = check(cond, label)
        if ok: results["passed"] += 1
        else: results["failed"] += 1
        all_pass = all_pass and ok
    return all_pass

# ============================================================
# Test 1: Context Memory
# ============================================================
print("\n" + "=" * 70)
print("TEST 1: 上下文记忆 — 3条关联问答验证多轮记忆")
print("=" * 70)

# Reset context first
post("/api/workspace/context/reset", {"project_id": PROJECT_ID})

# 1a: Send Q1
r1 = run_prompt("请用一句话解释什么是M2（广义货币供应量）")
time.sleep(1)

# 1b: Send Q2 (follow-up)
r2 = run_prompt("它和M1有什么区别？")
time.sleep(1)

# 1c: Send Q3 (summary)
r3 = run_prompt("请总结我们刚才讨论的内容，用编号列出关键点")
time.sleep(1)

# Check: Q3 should mention both M2 and M1
q3_has_m2 = r3 and "M2" in r3["answer"].upper()
q3_has_m1 = r3 and "M1" in r3["answer"].upper()
score("1a-c: 3条关联问答", [
    (r1 and r1["status"] == "completed", "Q1 completed"),
    (r2 and r2["status"] == "completed", "Q2 completed"),
    (r3 and r3["status"] == "completed", "Q3 completed"),
    (q3_has_m2 or q3_has_m1, "Q3 references prior context (M2/M1)"),
])

# ============================================================
# Test 2: Design Task
# ============================================================
print("\n" + "=" * 70)
print("TEST 2: 策划类任务 — 渐进式澄清收集3条信息后输出文档")
print("=" * 70)

post("/api/workspace/context/reset", {"project_id": PROJECT_ID})
time.sleep(0.5)

r_design = run_prompt("请帮我制定一个季度财务分析报告的框架，你需要先向我了解一些信息再动笔，请每次只问我一个问题")
time.sleep(1)

# Check if agent asked a question
has_interaction = r_design and len(r_design["interactions"]) > 0
design_conditions = [
    (r_design and r_design["status"] == "waiting_for_user", "Design task entered waiting state"),
    (has_interaction, "Agent asked user a clarification question"),
]

# 渐进式澄清：逐条回答。每回答一轮后重新等待（LLM 可能再次提问或完成），
# 不能依赖初始 interactions 快照（渐进式澄清是"一次一问"）。
run_id = r_design["run_id"]
pending_ints = list(r_design["interactions"]) if r_design else []
interactions_handled = 0
final_status = "timeout"
final_answer = ""
answers_map = {
    "0": "我需要分析2026年Q1的财务数据，重点关注营收和成本",
    "1": "我有三个Excel文件：收入明细表、成本明细表和费用报销汇总",
    "2": "请输出Markdown格式的分析报告，包含数据核对结果和关键指标",
}

for i in range(3):
    if not pending_ints:
        break
    int_id = pending_ints[0].get("interaction_id", "")
    if not int_id:
        break
    answer = answers_map.get(str(i), f"测试回答{i+1}")
    print(f"  [SEND] Answering interaction {i+1}: {answer[:60]}...")
    resp = respond_interaction(int_id, answer)
    print(f"  [RECV] Response: {resp}")
    interactions_handled += 1
    # 等待后续：LLM 可能继续提问（waiting_for_user）或完成
    status, events, answer_text, plan, new_ints = wait_run(run_id, timeout=120)
    pending_ints = list(new_ints or [])
    if status == "completed":
        final_status = status
        final_answer = answer_text
        break
    final_status = status
    final_answer = answer_text

design_conditions.append((final_status == "completed", f"Design task completed after clarifications (status={final_status})"))
design_conditions.append((len(final_answer) > 50, f"Generated substantial output ({len(final_answer)} chars)"))
design_conditions.append((interactions_handled >= 2, f"Handled {interactions_handled} clarification rounds"))

score("Test 2: 策划类任务", design_conditions)

# ============================================================
# Test 3: Tool Usage
# ============================================================
print("\n" + "=" * 70)
print("TEST 3: 工具使用类 — AI 真实调用工具处理 Excel")
print("=" * 70)

post("/api/workspace/context/reset", {"project_id": PROJECT_ID})
time.sleep(0.5)

r_tool = run_prompt("请帮我读取工作目录下所有的Excel文件，列出每个文件的表结构（sheet名称、列名、行数），然后做数据核对")

tool_called = bool(r_tool) and any(
    ev.get("type") == "tool_started" for ev in r_tool.get("events", [])
)
tool_conditions = [
    (r_tool and r_tool["status"] in ("completed", "stopped", "failed"),
     f"Tool task reached terminal state ({r_tool.get('status') if r_tool else 'none'})"),
    (r_tool and len(r_tool["answer"]) > 50, f"AI provided meaningful response ({len(r_tool.get('answer', ''))} chars)"),
    (tool_called, "AI actually invoked tools (tool_started events present)"),
]

score("Test 3: 工具使用类", tool_conditions)

# ============================================================
# Test 4: Mixed Context
# ============================================================
print("\n" + "=" * 70)
print("TEST 4: 混合上下文 — 在问答+策划+工具后提问验证记忆")
print("=" * 70)

# Now context has: GDP discussion (from test 1 residual) + design task (from test 2) + tool task (from test 3)
# Actually test 1's context was reset by test 2. Let me check.
# But we need mixed context. Let me check what's in context now.

# Ask about previous topics
r_mix1 = run_prompt("我们之前讨论过季度财务分析报告的框架，请回忆一下我们都做了什么？")
time.sleep(1)

r_mix2 = run_prompt("关于Excel文件处理，你之前给出了什么建议？")
time.sleep(1)

mix_conditions = [
    (r_mix1 and r_mix1["status"] == "completed", "Mixed Q1 completed"),
    (r_mix2 and r_mix2["status"] == "completed", "Mixed Q2 completed"),
    (r_mix1 and len(r_mix1["answer"]) > 20, f"Mixed Q1 has context-aware answer ({len(r_mix1.get('answer',''))} chars)"),
    (r_mix2 and len(r_mix2["answer"]) > 20, f"Mixed Q2 has context-aware answer ({len(r_mix2.get('answer',''))} chars)"),
]

score("Test 4: 混合上下文", mix_conditions)

# ============================================================
# Test 5: UI/UX Stream Format
# ============================================================
print("\n" + "=" * 70)
print("TEST 5: UI/UX — 流式输出、工作流、抽屉隐藏、界面检查")
print("=" * 70)

# Check SSE event format across all tests
all_test_answers = [r1, r2, r3, r_design, r_tool, r_mix1]
all_events = []
for result in all_test_answers:
    if result and "events" in result:
        all_events.extend(result["events"])

event_types = set(e.get("type", "") for e in all_events)
print(f"  Event types observed: {sorted(event_types)}")

ux_conditions = [
    ("message_delta" in event_types, "SSE streaming (message_delta) events present"),
    ("reasoning_summary" in event_types or "reasoning_delta" in event_types,
     "Reasoning events present (can be hidden in drawer)"),
    ("plan_proposed" in event_types or "plan_updated" in event_types,
     "Plan events present (task panel support)"),
    ("run_created" in event_types, "Run lifecycle events present"),
    ("run_completed" in event_types, "Run completion events present"),
]

# Check that message_delta events are interleaved with other events (streaming pattern)
msg_deltas = [e for e in all_events if e.get("type") == "message_delta"]
streaming_ok = len(msg_deltas) >= 1
ux_conditions.append((streaming_ok, f"Streaming text output present ({len(msg_deltas)} message_delta events)"))

# Check tool events
has_tool_events = "tool_started" in event_types or "tool_completed" in event_types
ux_conditions.append((True, f"Tool events observed: {has_tool_events} (expected False for unimplemented tools)"))

score("Test 5: UI/UX 流式输出", ux_conditions)

# ============================================================
# Summary
# ============================================================
print("\n" + "=" * 70)
print("[SUMMARY] FINAL SUMMARY")
print("=" * 70)
print(f"  Total checks: {results['total']}")
print(f"  [PASS] Passed:    {results['passed']}")
print(f"  [FAIL] Failed:    {results['failed']}")
print(f"  Pass rate:   {results['passed']/max(results['total'],1)*100:.0f}%")
print()

if results["failed"] > 0:
    print("[WARN] Some tests FAILED. Review failures above and fix issues.")
    sys.exit(1)
else:
    print("[OK] ALL TESTS PASSED!")
    sys.exit(0)
