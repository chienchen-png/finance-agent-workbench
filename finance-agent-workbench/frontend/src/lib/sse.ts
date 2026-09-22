/** sse.ts — SSE 事件客户端。
 *
 * 消费后端 /api/workspace/events 返回的 24 种 AgentEvent
 * （函数与变量总文档 1.4 agent/agent_events.py），驱动对话 UI。
 *
 * 事件类型（与后端契约一致）：
 *  - reasoning_delta       思考流式
 *  - reasoning_closed      思考结束
 *  - message_delta         正文流式
 *  - tool_started          工具开始
 *  - tool_completed        工具完成
 *  - step_started/completed 步骤
 *  - plan_proposed/updated 计划
 *  - run_completed/stopped/failed 终态
 *  - user_input_required   审批/提问
 */

export interface ToolEvent {
  tool_id: string;
  name: string;
  input?: string;
  title?: string;
  icon?: string;
  category?: string;
  output?: string;
  status?: string;
  output_summary?: string;
  duration_ms?: number;  // Phase 17 P12：工具耗时
  step_id?: string;
}

export interface RunEvents {
  status: string;
  last_seq: number;
  events: {
    type: string;
    seq?: number;
    ts?: string;
    payload: Record<string, unknown>;
  }[];
}

export interface StreamHandlers {
  onReasoning?: (delta: string) => void;
  onText?: (delta: string) => void;
  onToolStart?: (e: ToolEvent) => void;
  onToolEnd?: (e: ToolEvent) => void;
  onStep?: (index: number, total: number, label: string) => void;
  onPlan?: (steps: unknown[], status: string) => void;
  onDone?: (reason?: string) => void;
  onError?: (message: string) => void;
  // 智能体优化 3.0（阶段 A2）：ask_user 提问（原 user_input_required 曾误作 onError）
  onQuestion?: (q: {
    interaction_id: string;
    question: string;
    input_type: string;
    options: string[];
    multi_select?: boolean;
    allow_skip?: boolean;
  }) => void;
  // 智能体优化 3.0（阶段 A2，铁律 000）：run 创建元信息（任务模式：simple/complex）
  onRunCreated?: (m: { run_id: string; task_mode: string; title: string }) => void;
}

/** 轮询拉取事件（后端是轮询式 SSE，非长连接推送） */
export async function pollRunEvents(
  runId: string,
  handlers: StreamHandlers,
  signal?: AbortSignal,
): Promise<void> {
  let afterSeq = 0;
  let done = false;

  while (!done) {
    if (signal?.aborted) return;

    let data: RunEvents;
    try {
      const resp = await fetch(
        `/api/workspace/events?run_id=${encodeURIComponent(runId)}&after_seq=${afterSeq}`,
        { signal },
      );
      const json = await resp.json();
      data = json.data as RunEvents;
    } catch (e) {
      if (signal?.aborted) return;
      handlers.onError?.(`事件轮询失败: ${(e as Error).message}`);
      return;
    }

    afterSeq = data.last_seq;
    for (const ev of data.events) {
      dispatchEvent(ev, handlers);
    }

    if (data.status === "completed" || data.status === "failed" || data.status === "stopped") {
      done = true;
      handlers.onDone?.(data.status);
      return;
    }

    // 等待下一次轮询
    await new Promise((r) => setTimeout(r, 400));
  }
}

function dispatchEvent(ev: { type: string; payload: Record<string, unknown> }, h: StreamHandlers) {
  const p = ev.payload;
  switch (ev.type) {
    case "reasoning_delta":
      h.onReasoning?.((p.text as string) || "");
      break;
    case "reasoning_closed":
      break;
    case "message_delta":
      h.onText?.((p.text as string) || "");
      break;
    case "tool_started":
      h.onToolStart?.({
        tool_id: (p.tool_id as string) || "",
        name: (p.name as string) || "",
        input: (p.input as string) || "",
        title: (p.title as string) || "",
        icon: (p.icon as string) || "",
        category: (p.category as string) || "",
      });
      break;
    case "tool_completed":
      h.onToolEnd?.({
        tool_id: (p.tool_id as string) || "",
        name: (p.name as string) || "",
        output: (p.output as string) || "",
        status: (p.status as string) || "completed",
        output_summary: (p.output_summary as string) || "",
        duration_ms: (p.duration_ms as number) || 0,
        step_id: (p.step_id as string) || "",
      });
      break;
    case "step_started":
      h.onStep?.((p.index as number) || 0, (p.total as number) || 0, (p.title as string) || "执行");
      break;
    case "step_completed":
      break;
    case "plan_proposed":
      h.onPlan?.((p.steps as unknown[]) || [], "proposed");
      break;
    case "plan_updated":
      h.onPlan?.((p.steps as unknown[]) || [], (p.status as string) || "updated");
      break;
    case "user_input_required":
      // 智能体优化 3.0（阶段 A2）：从 onError 独立为 onQuestion，驱动 AskUserDialog
      h.onQuestion?.({
        interaction_id: (p.interaction_id as string) || "",
        question: (p.question as string) || "需要用户输入",
        input_type: (p.input_type as string) || "text",
        options: (p.options as string[]) || [],
        multi_select: (p.multi_select as boolean) || false,
        allow_skip: (p.allow_skip as boolean) || false,
      });
      break;
    case "run_created":
      // 智能体优化 3.0（阶段 A2，铁律 000）：任务模式指示器（简单问答 vs 复杂任务）
      h.onRunCreated?.({
        run_id: (p.run_id as string) || "",
        task_mode: (p.task_mode as string) || "complex",
        title: (p.title as string) || "",
      });
      break;
    default:
      break;
  }
}
