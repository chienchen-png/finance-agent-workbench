/** useReconRun — 数据核对集成应用运行器 hook（P0 骨架）。
 *
 * 复用现有运行时链路（设计文档 §6.2/§6.4）：
 *   startRun（/api/workspace/run）→ pollRunEvents（SSE 事件流）→
 *   onQuestion → AskUserDialog 应答（/api/interactions/<id>/respond）。
 *
 * 与 ChatPage 的 handleSend 同构，但面向「向导预填指令」场景：
 *   - report 直接累积 final_answer 文本（不经对话气泡）
 *   - tools 独立维护工具卡列表（运行态展示）
 *   - question 暴露给页面挂 AskUserDialog
 */

import { useCallback, useRef, useState } from "react";
import { startRun, stopRun } from "../lib/api";
import { pollRunEvents, type ToolEvent } from "../lib/sse";
import type { AskUserPayload } from "../components/AskUserDialog";

export interface ReconToolState {
  id: string;
  name: string;
  title: string;
  input: string;
  output: string;
  status: "running" | "completed" | "failed";
  duration_ms?: number;
}

export interface UseReconRunOptions {
  projectId: string;
  agent: string;
  model: string;
  workMode?: "manual" | "auto";
  /** 运行到达终态（completed/failed/stopped）时回调，携带终态原因与最终报告文本 */
  onFinished?: (reason: string, report: string) => void;
  /** 工具完成回调（如 reconcile_variables 的完整输出，供解析结构化差异） */
  onToolCompleted?: (name: string, output: string) => void;
}

export function useReconRun({
  projectId,
  agent,
  model,
  workMode = "manual",
  onFinished,
  onToolCompleted,
}: UseReconRunOptions) {
  const [runId, setRunId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState({ current: 0, total: 0, label: "" });
  const [tools, setTools] = useState<ReconToolState[]>([]);
  const [report, setReport] = useState("");
  const [question, setQuestion] = useState<AskUserPayload | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  /** 启动一次核对运行（预填指令由调用方组装） */
  const start = useCallback(
    async (prompt: string) => {
      if (!projectId || busy) return;
      setBusy(true);
      setReport("");
      setTools([]);
      setProgress({ current: 0, total: 0, label: "" });
      setQuestion(null);

      const ac = new AbortController();
      abortRef.current = ac;
      let textBuf = "";

      try {
        const { run_id } = await startRun({
          prompt,
          project_id: projectId,
          agent,
          model,
          engine: "smol",
          work_mode: workMode,
        });
        setRunId(run_id);

        await pollRunEvents(
          run_id,
          {
            onText: (d) => {
              textBuf += d;
              setReport(textBuf);
            },
            onToolStart: (e: ToolEvent) => {
              // final_answer 兜底过滤（与 ChatPage 一致，后端已过滤）
              if (e.name === "final_answer") return;
              setTools((prev) => [
                ...prev,
                {
                  id: e.tool_id,
                  name: e.name,
                  title: e.title || e.name,
                  input: e.input || "",
                  output: "",
                  status: "running",
                },
              ]);
            },
            onToolEnd: (e: ToolEvent) => {
              setTools((prev) =>
                prev.map((t) =>
                  t.id === e.tool_id
                    ? {
                        ...t,
                        output: e.output || "",
                        status: (e.status as ReconToolState["status"]) || "completed",
                        duration_ms: e.duration_ms || 0,
                      }
                    : t,
                ),
              );
              // 结构化差异数据源：捕获 reconcile_variables 完整输出
              if (e.name === "reconcile_variables") {
                onToolCompleted?.(e.name, e.output || "");
              }
            },
            onStep: (current, total, label) => setProgress({ current, total, label }),
            onQuestion: (q) => {
              setQuestion({
                interaction_id: q.interaction_id,
                question: q.question,
                input_type: q.input_type,
                options: q.options,
                multi_select: q.multi_select,
                allow_skip: q.allow_skip,
              });
            },
            onDone: (reason) => {
              onFinished?.(reason || "completed", textBuf);
            },
            onError: (msg) => {
              setReport((prev) => prev + `\n\n⚠️ ${msg}`);
            },
          },
          ac.signal,
        );
      } catch (e) {
        if ((e as Error).name !== "AbortError") {
          setReport((prev) => prev + `\n\n⚠️ 发送失败: ${(e as Error).message}`);
        }
      } finally {
        setBusy(false);
        abortRef.current = null;
        setRunId(null);
      }
    },
    [projectId, agent, model, workMode, busy, onFinished, onToolCompleted],
  );

  /** 停止运行（后端 stopRun + 前端 abort 轮询） */
  const stop = useCallback(async () => {
    if (runId) {
      try {
        await stopRun(runId);
      } catch {
        /* 忽略 */
      }
    }
    abortRef.current?.abort();
    setBusy(false);
  }, [runId]);

  /** 应答 ask_user 提问（复用 /api/interactions/<id>/respond） */
  const answer = useCallback(
    async (resp: string, cancelled: boolean) => {
      if (!question) return;
      try {
        await fetch(`/api/interactions/${question.interaction_id}/respond`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ response: resp, cancelled }),
        });
      } catch {
        /* 忽略网络错误，引擎侧超时会自行降级 */
      }
      setQuestion(null);
    },
    [question],
  );

  return { runId, busy, progress, tools, report, question, start, stop, answer };
}
