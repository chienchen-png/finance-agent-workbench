"""Phase 17 P12 集成验证：smol_bridge 事件桥修复。

验证：
  1. ActionStep(is_final_answer=True) → 正文输出，不发射工具卡
  2. tool_calls 含 final_answer → 被过滤（不产生工具卡）
  3. 普通工具调用 → tool_started/tool_completed + 耗时 duration_ms > 0
  4. FinanceModel：工具调用轮次的文本增量被抑制（不透出包装文本）
"""
from __future__ import annotations

import os
import sys
import types
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

FAIL = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(("PASS" if ok else "FAIL"), label, detail)
    if not ok:
        FAIL.append(label)


def make_step(cls_name="ActionStep", tool_calls=None, observations=None,
              is_final_answer=False, model_output=""):
    """构造一个模拟 smolagents step（SimpleNamespace 级别）。"""
    return types.SimpleNamespace(
        __class__=type(cls_name, (), {"__name__": cls_name})(),
        tool_calls=tool_calls,
        observations=observations,
        is_final_answer=is_final_answer,
        model_output=model_output,
    )


def make_tool(name="read_excel", arguments=None):
    return types.SimpleNamespace(name=name, arguments=arguments or {})


def main() -> int:
    from agent.smol_bridge import SmolBridge

    events: list[dict] = []

    def emit(ev: dict) -> None:
        events.append(ev)

    bridge = SmolBridge(emit=emit)

    # ── 1. is_final_answer ActionStep → 正文输出，无工具卡 ──
    step = make_step(is_final_answer=True, model_output="你好！我是财务助手。")
    bridge.on_step(step)
    text_out = "".join(e["payload"].get("text", "")
                       for e in events if e["type"] == "message_delta")
    tool_cards = [e for e in events if e["type"] == "tool_started"]
    check("is_final_answer 转正文", "你好" in text_out, f"正文={text_out[:30]}")
    check("is_final_answer 无工具卡", len(tool_cards) == 0,
          f"工具卡 {len(tool_cards)} 张")
    check("is_final_answer 触发 run_completed",
          any(e["type"] == "run_completed" for e in events))

    # ── 2. tool_calls 含 final_answer → 过滤 ──
    events.clear()
    step2 = make_step(tool_calls=[make_tool("final_answer", {"answer": "x"})],
                      observations=["final answer"])
    bridge.on_step(step2)
    tool_cards2 = [e for e in events if e["type"] == "tool_started"]
    check("final_answer 工具被过滤", len(tool_cards2) == 0,
          f"工具卡 {len(tool_cards2)} 张")

    # ── 3. 普通工具调用 → 事件 + 耗时 ──
    # 真实 smolagents：ActionStep1 发 tool_calls，ActionStep2 带 observations（两步）
    events.clear()
    bridge3 = SmolBridge(emit=emit)
    step3a = make_step(tool_calls=[make_tool("query_table", {"file": "t.xlsx"})])
    bridge3.on_step(step3a)
    time.sleep(0.02)  # 模拟两步之间的执行耗时
    step3b = make_step(observations=["3 rows"])
    bridge3.on_step(step3b)
    starts = [e for e in events if e["type"] == "tool_started"]
    ends = [e for e in events if e["type"] == "tool_completed"]
    check("普通工具 tool_started", len(starts) == 1,
          f"started={len(starts)}")
    check("普通工具 tool_completed", len(ends) == 1,
          f"completed={len(ends)}")
    if starts and ends:
        check("工具名 query_table", starts[0]["payload"]["name"] == "query_table")
        check("耗时 duration_ms > 0",
              (ends[0]["payload"].get("duration_ms") or 0) > 0,
              f"duration={ends[0]['payload'].get('duration_ms')}")
        check("工具标题人类可读",
              starts[0]["payload"].get("title") == "query_table"
              or "查询" in starts[0]["payload"].get("title", ""),
              f"title={starts[0]['payload'].get('title')}")

    # ── 3.5 observations 为字符串（smolagents 真实类型 str|None）→ 只发 1 次 ──
    events.clear()
    bridge3b = SmolBridge(emit=emit)
    step3c = make_step(tool_calls=[make_tool("list_directory", {"path": "."})])
    bridge3b.on_step(step3c)
    # 真实 smolagents：observations 是 str（JSON 文本），不是 list！
    step3d = make_step(
        observations='{"files": ["a.md", "b.pdf"], "dirs": ["x"]}')
    bridge3b.on_step(step3d)
    ends3b = [e for e in events if e["type"] == "tool_completed"]
    check("observations 字符串只发 1 次 tool_completed", len(ends3b) == 1,
          f"completed={len(ends3b)}（按字符遍历会发 40+ 次）")
    if ends3b:
        check("observations 字符串完整输出",
              "a.md" in ends3b[0]["payload"].get("output", ""),
              f"output={ends3b[0]['payload'].get('output','')[:40]!r}")

    # ── 4. P12.2 轮次级缓冲路由：工具轮文本→思考块；final 轮文本→正文 ──
    from agent.smol_model import FinanceModel

    class FakeLLMToolTurn:
        """工具轮：规划文本（独立 chunk，早于 tcd）+ 工具调用增量。"""

        def chat_stream(self, *a, **kw):
            yield {"delta": "## 1. Facts survey\n- 任务要求：列出目录"}
            yield {"delta": "## 2. Plan"}
            yield {"tool_call_delta": [
                {"index": 0, "id": "t1",
                 "function": {"name": "list_directory", "arguments": '{"path":"."}'}}]}
            yield {"usage": {"input_tokens": 10, "output_tokens": 5}}

    ev4: list[dict] = []
    bridge4 = SmolBridge(emit=lambda e: ev4.append(e))
    model4 = FinanceModel(llm=FakeLLMToolTurn(), model_id="m",
                          on_text_delta=bridge4.on_text_delta,
                          on_reasoning=bridge4.on_reasoning_delta)
    list(model4.generate_stream([]))
    early4 = [e for e in ev4 if e["type"] in ("message_delta", "reasoning_delta")]
    check("工具轮文本先缓冲（流式中不 emit）", len(early4) == 0,
          f"early={[e['type'] for e in early4]}")

    step_tool = make_step(
        tool_calls=[make_tool("list_directory", {"path": "."})],
        observations=["3 files"])
    bridge4.on_step(step_tool)
    reas4 = "".join(e["payload"].get("text", "")
                    for e in ev4 if e["type"] == "reasoning_delta")
    msg4 = "".join(e["payload"].get("text", "")
                   for e in ev4 if e["type"] == "message_delta")
    check("工具轮规划文本→思考块", "Facts survey" in reas4,
          f"reasoning={reas4[:40]!r}")
    check("工具轮规划文本不进正文", "Facts survey" not in msg4,
          f"msg={msg4[:40]!r}")
    check("工具轮工具卡正常",
          any(e["type"] == "tool_started" for e in ev4),
          f"started={sum(1 for e in ev4 if e['type']=='tool_started')}")

    class FakeLLMFinal:
        """最终答案轮：纯文本（无工具调用）。"""

        def chat_stream(self, *a, **kw):
            yield {"delta": "工作目录中不存在 test-fixtures 目录"}
            yield {"usage": {"input_tokens": 5, "output_tokens": 5}}

    ev5: list[dict] = []
    bridge5 = SmolBridge(emit=lambda e: ev5.append(e))
    model5 = FinanceModel(llm=FakeLLMFinal(), model_id="m",
                          on_text_delta=bridge5.on_text_delta,
                          on_reasoning=bridge5.on_reasoning_delta)
    list(model5.generate_stream([]))
    bridge5.on_step(make_step(is_final_answer=True, model_output=""))
    fa_msg = "".join(e["payload"].get("text", "")
                     for e in ev5 if e["type"] == "message_delta")
    fa_reas = "".join(e["payload"].get("text", "")
                      for e in ev5 if e["type"] == "reasoning_delta")
    check("最终答案轮文本→正文", "test-fixtures" in fa_msg,
          f"final={fa_msg[:40]!r}")
    check("最终答案文本不进思考块", "test-fixtures" not in fa_reas,
          f"reas={fa_reas[:40]!r}")
    check("最终答案轮触发 run_completed",
          any(e["type"] == "run_completed" for e in ev5))

    # ── 5. FinalAnswerStep（旧式收尾）→ output 进正文 ──
    from smolagents.agents import FinalAnswerStep

    ev6: list[dict] = []
    bridge6 = SmolBridge(emit=lambda e: ev6.append(e))
    bridge6.on_step(FinalAnswerStep(output="最终输出"))
    fa6 = "".join(e["payload"].get("text", "")
                  for e in ev6 if e["type"] == "message_delta")
    check("FinalAnswerStep output→正文", "最终输出" in fa6,
          f"final={fa6[:30]!r}")
    check("FinalAnswerStep 触发 run_completed",
          any(e["type"] == "run_completed" for e in ev6))

    # ── 6. P12.4：纯写作任务（无工具调用）一次性输出 规划+答案 ──
    # 模型一次性输出 "Facts survey + Plan + <end_plan> + 最终答案"，
    # smolagents 解析为 is_final_answer → 规划须进思考块、答案才进正文。
    ev7: list[dict] = []
    bridge7 = SmolBridge(emit=lambda e: ev7.append(e))
    bridge7.on_text_delta("## 1. Facts survey\n- 任务要求：介绍财务核对流程")
    bridge7.on_text_delta("\n## 2. Plan\n1. 编写导入环节说明")
    bridge7.on_text_delta("\n<end_plan>财务核对流程分为导入、核对、写回三环节。")
    bridge7.on_step(make_step(is_final_answer=True, model_output=""))
    msg7 = "".join(e["payload"].get("text", "")
                   for e in ev7 if e["type"] == "message_delta")
    reas7 = "".join(e["payload"].get("text", "")
                    for e in ev7 if e["type"] == "reasoning_delta")
    check("P12.4 纯写作：最终答案进正文",
          "财务核对流程分为" in msg7 and "导入、核对、写回" in msg7,
          f"msg={msg7[:40]!r}")
    check("P12.4 纯写作：规划不进正文",
          "Facts survey" not in msg7 and "<end_plan>" not in msg7,
          f"msg={msg7[:40]!r}")
    check("P12.4 纯写作：规划进思考块",
          "Facts survey" in reas7 and "Plan" in reas7,
          f"reas={reas7[:40]!r}")

    # ── 7. P12.4：FinalAnswerStep.output 含规划 → 分离 ──
    ev8: list[dict] = []
    bridge8 = SmolBridge(emit=lambda e: ev8.append(e))
    bridge8.on_step(FinalAnswerStep(
        output="## 1. Facts survey\n- 事实\n## 2. Plan\n1. 计划\n"
               "<end_plan>最终答案正文内容"))
    msg8 = "".join(e["payload"].get("text", "")
                   for e in ev8 if e["type"] == "message_delta")
    reas8 = "".join(e["payload"].get("text", "")
                    for e in ev8 if e["type"] == "reasoning_delta")
    check("P12.4 FinalAnswerStep：答案进正文", "最终答案正文" in msg8,
          f"msg={msg8[:30]!r}")
    check("P12.4 FinalAnswerStep：规划进思考", "Facts survey" in reas8,
          f"reas={reas8[:30]!r}")

    # ── 8. P13：同一轮回答 is_final_answer + FinalAnswerStep → 正文只一遍 ──
    # 模型输出 content（被解析为 is_final_answer ActionStep），smolagents
    # 随后把同一回答封装为 FinalAnswerStep.output——两分支都路由会双份正文。
    ev9: list[dict] = []
    bridge9 = SmolBridge(emit=lambda e: ev9.append(e))
    bridge9.on_text_delta("目录清单：a.md、b.pdf 共 2 个文件")
    bridge9.on_step(make_step(is_final_answer=True, model_output=""))
    bridge9.on_step(FinalAnswerStep(output="目录清单：a.md、b.pdf 共 2 个文件"))
    msg9 = "".join(e["payload"].get("text", "")
                   for e in ev9 if e["type"] == "message_delta")
    check("P13 双分支正文只一遍", msg9.count("目录清单：") == 1,
          f"正文重复 {msg9.count('目录清单：')} 次 msg={msg9[:60]!r}")

    # ── 9. P13：run_completed 幂等（多收尾路径只发 1 次）──
    ev10: list[dict] = []
    bridge10 = SmolBridge(emit=lambda e: ev10.append(e))
    bridge10.on_step(make_step(is_final_answer=True, model_output="答案A"))
    bridge10.on_step(FinalAnswerStep(output="答案A"))
    bridge10.on_done()
    n_done10 = sum(1 for e in ev10 if e["type"] == "run_completed")
    check("P13 run_completed 只发 1 次", n_done10 == 1,
          f"run_completed x{n_done10}")

    print()
    if FAIL:
        print("FAILED:", FAIL)
        return 1
    print("ALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
