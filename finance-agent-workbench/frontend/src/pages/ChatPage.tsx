/** ChatPage — 对话主区（阶段 2 核心）。
 *
 * 三元流渲染：思考（可折叠）/ 工具卡 / 正文 markdown
 * 对接：/api/workspace/run（发送）+ /api/workspace/events（轮询）
 * 数据：src/lib/api.ts + src/lib/sse.ts
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ReactElement } from "react";
import { Send, Square, Loader2, Wrench, FolderOpen, Database, ChevronDown, ChevronRight, PenLine, Play, FileText, Search, ArrowRight, BarChart3, Calculator, Scale, Sparkles, Table2, Lightbulb } from "lucide-react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import "katex/dist/katex.min.css";
import type { Project, ModelOption, AgentOption } from "../lib/api";
import { startRun, stopRun, fetchHistory, updateProject } from "../lib/api";
import ModelPicker from "../components/ModelPicker";
import { pollRunEvents, type ToolEvent } from "../lib/sse";
import PlanCard, { type PlanStep } from "../components/PlanCard";
import RunProgress from "../components/RunProgress";
import FileDrawer from "../components/FileDrawer";
import DataPanel from "../components/DataPanel";
import ApprovalDialog from "../components/ApprovalDialog";
import AskUserDialog, { type AskUserPayload } from "../components/AskUserDialog";
import ContextIndicator from "../components/ContextIndicator";
import WorkModeSelector, { type WorkMode } from "../components/WorkModeSelector";
import ChartRenderer, { type ChartSpec } from "../components/ChartRenderer";

// ---------- 工具事件驱动图表（2026-08-21：不再依赖 AI 正文写 chart-json） ----------

/** 会话级已渲染图表 key 集合（template+title 或 chart_id 去重，避免正文与工具事件重复渲染） */
const renderedChartKeys = new Set<string>();

/** 计算图表去重 key（与后端 chart_id 生成同源：template+title） */
function chartKey(spec: { template?: string; title?: string; chart_id?: string }): string {
  if (spec.chart_id) return spec.chart_id;
  return `chart-${Math.abs((String(spec.template || "") + String(spec.title || "")).split("").reduce((a, c) => (a * 31 + c.charCodeAt(0)) >>> 0, 0)) % 100000}`;
}

/** 从 generate_chart 工具 output 解析 ChartSpec；失败返回 null。
 * 工具输出形如 {"success":true,"result":{chart_id,template,title,option,data_table,...}} */
function parseChartFromToolOutput(output: string): ChartSpec | null {
  try {
    const parsed = JSON.parse(output || "{}");
    const r = parsed && typeof parsed === "object" ? (parsed.result || parsed) : null;
    if (!r || typeof r !== "object" || !r.template) return null;
    return {
      chart_id: r.chart_id as string | undefined,
      template: String(r.template),
      title: (r.title as string) || undefined,
      option: (r.option as Record<string, unknown>) || undefined,
      data_table: (r.data_table as Record<string, unknown>[]) || undefined,
    };
  } catch {
    return null;
  }
}

// ---------- 类型 ----------

interface ToolCardState {
  id: string;
  name: string;
  input: string;
  output: string;
  status: "running" | "completed" | "failed";
  title?: string;
  duration_ms?: number;  // Phase 17 P12：工具耗时
  step_id?: string;
}

interface Message {
  role: "user" | "assistant";
  content: string;
  reasoning?: string;
  tools?: ToolCardState[];
  /** 工具事件驱动图表（generate_chart 完成 → 自动渲染，不依赖 AI 正文写 chart-json） */
  charts?: ChartSpec[];
  running?: boolean;
}

// ---------- P12.5：react-markdown 渲染（方案 A：全量重解析 + React diff） ----------
// 替代手写 renderMarkdown：CommonMark 100% + remark-gfm（表格/删除线/任务列表），
// 默认转义 HTML 无 XSS；components 映射 Tailwind 财务风格。
// 流式时每次 text 增量全量重解析，React 虚拟 DOM diff 只更新变化节点 →
// **加粗 / ### 标题 / - 列表 打字过程中实时生效（天然打字机）。

const PROSE_CLASS =
  "prose-sm max-w-none text-sm leading-relaxed text-zinc-800 " +
  "[&_table]:my-2 [&_table]:w-full [&_table]:border-collapse [&_table]:border [&_table]:border-zinc-300 " +
  "[&_th]:border [&_th]:border-zinc-300 [&_th]:bg-zinc-100 [&_th]:px-2 [&_th]:py-1 " +
  "[&_td]:border [&_td]:border-zinc-300 [&_td]:px-2 [&_td]:py-1 " +
  "[&_pre]:my-2 [&_pre]:overflow-auto [&_pre]:rounded-md [&_pre]:bg-zinc-100 [&_pre]:p-3 " +
  "[&_code]:rounded [&_code]:bg-zinc-100 [&_code]:px-1 " +
  "[&_h1]:my-3 [&_h1]:text-lg [&_h2]:my-2 [&_h2]:text-base [&_h3]:my-2 [&_h3]:text-sm " +
  "[&_ul]:my-1 [&_ul]:list-disc [&_ul]:pl-5 [&_ol]:my-1 [&_ol]:list-decimal [&_ol]:pl-5";

/** P12.5：react-markdown 渲染（统一组件，流式/完成态共用）。
 * P3：remark-math + rehype-katex（$$ 块级公式渲染，关闭单 $ 防货币冲突）；
 * code 组件检测 language-chart-json → ChartRenderer（ECharts 渲染 + 数据表）。 */
function MarkdownText({ text }: { text: string }) {
  return (
    <Markdown
      remarkPlugins={[remarkGfm, [remarkMath, { singleDollarTextMath: false }]]}
      rehypePlugins={[[rehypeKatex, { strict: false, throwOnError: false }]]}
      components={{
        table: (props) => (
          <table className="my-2 w-full border-collapse border border-zinc-300" {...props} />
        ),
        th: (props) => (
          <th className="border border-zinc-300 bg-zinc-100 px-2 py-1 text-left" {...props} />
        ),
        td: (props) => (
          <td className="border border-zinc-300 px-2 py-1" {...props} />
        ),
        pre: (props) => {
          // P3：chart-json 代码块 → ChartRenderer 已渲染图表，直接透传不包 pre
          // （react-markdown 默认 pre > code 结构，会把它包进代码块样式的 pre）
          const child = props.children as { props?: { className?: string } } | undefined;
          const childCls = child?.props?.className;
          if (typeof childCls === "string" && childCls.includes("language-chart-json")) {
            return child as unknown as ReactElement;
          }
          return <pre className="my-2 overflow-auto rounded-md bg-zinc-100 p-3" {...props} />;
        },
        code: (props) => {
          const { className, children } = props;
          // P3：chart-json 代码块 → ECharts 渲染
          if (typeof className === "string" && className.includes("language-chart-json")) {
            const raw = String(children ?? "").replace(/\n$/, "");
            let spec: unknown = raw;
            try {
              spec = JSON.parse(raw);
            } catch {
              spec = raw;
            }
            // 2026-08-21：工具事件已驱动渲染（renderedChartKeys 含 key）→ 跳过，
            // 避免同一图表渲染两次（AI 正文与工具事件重复）。
            if (spec && typeof spec === "object" && !Array.isArray(spec)) {
              const s = spec as ChartSpec;
              if (renderedChartKeys.has(chartKey(s))) return null;
            }
            return <ChartRenderer spec={spec} />;
          }
          return <code className="rounded bg-zinc-100 px-1" {...props} />;
        },
        a: (props) => (
          <a className="text-blue-600 underline" target="_blank" rel="noreferrer" {...props} />
        ),
        h1: (props) => <h1 className="my-3 text-lg font-semibold" {...props} />,
        h2: (props) => <h2 className="my-2 text-base font-semibold" {...props} />,
        h3: (props) => <h3 className="my-2 text-sm font-semibold" {...props} />,
      }}
    >
      {text}
    </Markdown>
  );
}

/** P12.5：流式期间未闭合的块级构造（```代码块 / 表格 / $$ 公式）容错——
 * 截掉最后一个未闭合块构造之后的内容（等闭合后再合并），避免后续全部误入其中。
 * P3：新增 $$...$$ 公式块检测（remark-math 块级公式）。 */
function trimIncompleteBlocks(text: string): { md: string; tail: string } {
  const lines = text.split("\n");
  let fenceOpen = false;
  let lastFenceIdx = -1;
  let lastTableIdx = -1;
  let mathOpen = false;
  let lastMathIdx = -1;
  for (let i = 0; i < lines.length; i++) {
    const l = lines[i];
    if (/^\s*```/.test(l)) {
      fenceOpen = !fenceOpen;
      if (fenceOpen) lastFenceIdx = i;
    }
    // 表格：上一个非空行是 | 分隔行（| --- | --- |）且后面还有 | 行 → 未闭合表格
    if (/^\s*\|/.test(l)) {
      lastTableIdx = i;
    }
    // $$ 公式：行内出现 $$ 切换状态
    const mathCount = (l.match(/\$\$/g) || []).length;
    if (mathCount % 2 === 1) {
      mathOpen = !mathOpen;
      if (mathOpen) lastMathIdx = i;
    }
  }
  // 1) 未闭合代码块 → 从开启行开始截掉
  if (fenceOpen && lastFenceIdx >= 0) {
    const md = lines.slice(0, lastFenceIdx).join("\n");
    const tail = lines.slice(lastFenceIdx).join("\n");
    return { md, tail };
  }
  // 2) 未闭合 $$ 公式块 → 从开启行开始截掉（等闭合再合并）
  if (mathOpen && lastMathIdx >= 0) {
    const md = lines.slice(0, lastMathIdx).join("\n");
    const tail = lines.slice(lastMathIdx).join("\n");
    return { md, tail };
  }
  // 3) 未闭合表格：末行是 | 分隔行（| --- | --- |）→ 表格结构未完成，先整体走纯文本
  if (lastTableIdx >= 0) {
    const l = lines[lastTableIdx];
    const isSep = /^\s*\|[\s:|-]+\|?\s*$/.test(l) && !/[^|\s:-]/.test(l.replace(/\|/g, ""));
    if (isSep) {
      return { md: "", tail: text };
    }
  }
  return { md: text, tail: "" };
}

// ---------- P12.5：Streaming Markdown（方案 A 全量重解析） ----------
// 对齐 Beautiful UI #Streaming Text：
//   每次 text 增量 → <MarkdownText text={text} /> 全量重解析 → React diff 只更新
//   变化节点 → 流式中 **加粗 / ### 标题 / - 列表 实时生效；光标叠加在末尾。

function StreamingMarkdown({ text, running }: { text: string; running: boolean }) {
  // 块级容错：未闭合代码块/表格尾部暂存为纯文本（闭合后自动并入 md）
  const { md, tail } = useMemo(() => trimIncompleteBlocks(text), [text]);

  return (
    <div className={PROSE_CLASS}>
      <MarkdownText text={md} />
      {tail && <span className="whitespace-pre-wrap">{tail}</span>}
      {running && <span className="stream-caret" />}
    </div>
  );
}

// ---------- 对话组件 ----------

export default function ChatPage({
  project,
  models,
  agents,
  providers,
  defaultModel,
  onModelChange,
}: {
  project: Project;
  models: ModelOption[];
  agents: AgentOption[];
  providers: { id: string; name: string }[];
  defaultModel: string;
  onModelChange?: (modelId: string) => void;
}) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  // 阶段 7.9：模型用唯一 id（provider_xxx_modelname）标识——一个模型名
  // 可能由多个供应商提供，必须用 id 区分源头与 token 计费
  const [model, setModel] = useState("");
  // 阶段 G4：工作模式（manual=人工审批 / auto=全自动），会话级临时切换，
  // 与模型切换同构：本地 state + updateProject 持久化 + startRun payload 传递。
  // 默认取项目级配置（projects.work_mode），后端未传时同样回退项目级。
  const [workMode, setWorkMode] = useState<WorkMode>(
    project.work_mode === "auto" ? "auto" : "manual",
  );
  const [agent] = useState(agents[0]?.name || "general-agent");
  const [runId, setRunId] = useState<string | null>(null);
  const [progress, setProgress] = useState({ current: 0, total: 0, label: "" });
  const [planSteps, setPlanSteps] = useState<PlanStep[]>([]);
  const [drawer, setDrawer] = useState<null | "files" | "data">(null);
  // 阶段 7.9.10.2：抽屉关闭动画统一由父级管理（两种关闭方式都走滑出动画：
  // ①子组件「关闭」按钮 ②工具行切换按钮）
  const [closingDrawer, setClosingDrawer] = useState<null | "files" | "data">(null);
  const closeTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  /** 请求关闭当前抽屉：先播放滑出动画，260ms 后再卸载 */
  const requestCloseDrawer = useCallback(() => {
    if (!drawer || closingDrawer) return;
    setClosingDrawer(drawer);
    closeTimerRef.current = setTimeout(() => {
      setDrawer(null);
      setClosingDrawer(null);
    }, 260); // 与 drawer-slide-out 时长一致
  }, [drawer, closingDrawer]);

  /** 切换抽屉：打开 → 直接展开；关闭（同类型已开）→ 走滑出动画 */
  const toggleDrawer = useCallback((kind: "files" | "data") => {
    setDrawer((d) => {
      if (d === kind) {
        // 正在播放关闭动画则不重复触发
        if (closingDrawer) return d;
        setClosingDrawer(kind);
        closeTimerRef.current = setTimeout(() => {
          setDrawer(null);
          setClosingDrawer(null);
        }, 260);
        return d; // 暂不卸载，等动画结束
      }
      return kind; // 打开
    });
  }, [closingDrawer]);

  useEffect(() => () => { if (closeTimerRef.current) clearTimeout(closeTimerRef.current); }, []);
  const [approval, setApproval] = useState<{ toolName: string; args: string; resolve: (v: boolean) => void } | null>(null);
  // 智能体优化 3.0（阶段 A2）：ask_user 提问弹窗
  const [question, setQuestion] = useState<AskUserPayload | null>(null);
  // 智能体优化 3.0（阶段 A2，铁律 000）：任务模式指示器（simple=无规划 / complex=含规划）
  const [taskMode, setTaskMode] = useState<"simple" | "complex" | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  // 开篇建议提示词 → 点击填充输入框并聚焦（不自动发送，用户可改，对齐 Claude/ChatGPT）
  const inputRef = useRef<HTMLTextAreaElement>(null);

  // ---------- 空状态开篇（借鉴主流智能体：建议提示词 + 能力清单 + 项目上下文） ----------
  const suggestions = useMemo(() => {
    const y = project.year ? `${project.year}年` : "本期";
    return [
      { icon: Scale, text: `核对「银行流水」与「总账」，列出每一笔差异并给出来源分析` },
      { icon: Database, text: `查询项目数据库，汇总各表记录数与关键字段概况` },
      { icon: BarChart3, text: `基于项目数据做杜邦分析，评估${y}盈利质量并生成图表` },
      { icon: PenLine, text: `把核对确认的差异写回 Excel 对应列，标注处理状态` },
    ];
  }, [project.year]);

  const capabilities = useMemo(
    () => [
      { icon: FileText, label: "项目文件", desc: "读写项目目录下的文件" },
      { icon: Table2, label: "Excel 分析", desc: "读取 / 分析 / 比较 Excel 工作表" },
      { icon: Scale, label: "差异核对", desc: "核对变量、比对两表差异" },
      { icon: BarChart3, label: "图表生成", desc: "生成 20+ 种可视化图表" },
      { icon: Calculator, label: "财务建模", desc: "杜邦、回归、敏感性等建模分析" },
      { icon: PenLine, label: "写回 Excel", desc: "将结果写回原 Excel 文件" },
    ],
    [],
  );

  /** 点击建议提示词：填充输入框并聚焦（不自动发送，用户确认后可回车） */
  const applySuggestion = useCallback((text: string) => {
    setInput(text);
    inputRef.current?.focus();
  }, []);

  // 阶段 7.9：解析 defaultModel（可能是 id 或旧 name）→ 唯一 model.id
  useEffect(() => {
    const byId = models.find((m) => m.id === defaultModel);
    const byName = models.find((m) => m.name === defaultModel);
    const globalDefault = models.find((m) => m.is_default === 1);
    const picked = byId || byName || globalDefault || models[0];
    setModel(picked?.id || "");
  }, [defaultModel, project.id, models]);

  // 阶段 7.9：切换模型（存唯一 id）并持久化到项目
  async function handleSelectModel(m: ModelOption) {
    setModel(m.id);
    try {
      await updateProject(project.id, { default_model: m.id });
      // 通知父级刷新 activeProject（下次刷新/重进仍是新模型）
      onModelChange?.(m.id);
    } catch (e) {
      alert(`切换模型失败: ${(e as Error).message}`);
    }
  }

  // 阶段 G4：切换工作模式（会话级临时切换，与模型切换同构——立即生效 + 持久化）
  async function handleSelectWorkMode(mode: WorkMode) {
    setWorkMode(mode);
    try {
      await updateProject(project.id, { work_mode: mode });
    } catch (e) {
      alert(`切换工作模式失败: ${(e as Error).message}`);
    }
  }

  // 加载历史（阶段 7.9：提取为可复用函数，清空上下文后重新加载）
  const loadHistory = useCallback(async () => {
    try {
      const h = await fetchHistory(project.id);
      const hist: Message[] = [];
      for (const r of h.runs) {
        hist.push({ role: "user", content: r.user_prompt, reasoning: undefined, tools: undefined });
        hist.push({
          role: "assistant",
          content: r.assistant_text,
          reasoning: r.reasoning || undefined,
          tools: (r.tool_cards as unknown as ToolCardState[]) || undefined,
        });
      }
      setMessages(hist);
    } catch { /* 无历史 */ }
  }, [project.id]);

  useEffect(() => {
    loadHistory();
  }, [loadHistory]);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight });
  }, [messages, progress]);

  // ---------- 发送 ----------
  async function handleSend() {
    const prompt = input.trim();
    if (!prompt || busy) return;
    setInput("");
    setMessages((m) => [...m, { role: "user", content: prompt }]);
    // 新 assistant 消息占位
    const assistantMsg: Message = { role: "assistant", content: "", reasoning: "", tools: [], running: true };
    setMessages((m) => [...m, assistantMsg]);
    setBusy(true);
    setProgress({ current: 0, total: 0, label: "" });
    setPlanSteps([]);
    // 智能体优化 3.0（阶段 A2，铁律 000）：新任务等待 run_created 事件更新模式
    setTaskMode(null);

    const ac = new AbortController();
    abortRef.current = ac;

    try {
      const { run_id } = await startRun({
        prompt,
        project_id: project.id,
        agent,
        model,
        engine: "smol",
        work_mode: workMode,  // 阶段 G4：会话级工作模式（manual/auto）
      });
      setRunId(run_id);

      let reasoningBuf = "";
      let textBuf = "";
      let lastTool: ToolCardState | null = null;

      await pollRunEvents(
        run_id,
        {
          onReasoning: (d) => {
            reasoningBuf += d;
            patchAssistant({ reasoning: reasoningBuf });
          },
          onText: (d) => {
            textBuf += d;
            patchAssistant({ content: textBuf });
          },
          onToolStart: (e: ToolEvent) => {
            // Phase 17 P12：final_answer 兜底过滤（后端已过滤，前端双保险）
            if (e.name === "final_answer") return;
            lastTool = {
              id: e.tool_id, name: e.name, input: e.input || "", output: "",
              status: "running", title: e.title || e.name, step_id: e.step_id,
            };
            patchAssistant({ tools: [...lastToolsRef.current, lastTool] });
          },
          onToolEnd: (e: ToolEvent) => {
            patchAssistant({
              tools: lastToolsRef.current.map((t) =>
                t.id === e.tool_id
                  ? {
                      ...t, output: e.output || "",
                      status: (e.status as "completed") || "completed",
                      duration_ms: e.duration_ms || 0,
                    }
                  : t,
              ),
            });
            // 2026-08-21：generate_chart 工具完成 → 自动渲染图表卡片。
            // 不依赖 AI 在正文写 chart-json（模型常跳过导致「画好了但没图」）。
            if (e.name === "generate_chart") {
              const spec = parseChartFromToolOutput(e.output || "");
              if (spec) {
                const key = chartKey(spec);
                if (!renderedChartKeys.has(key)) {
                  renderedChartKeys.add(key);
                  patchAssistant({
                    charts: [...(lastChartsRef.current || []), spec],
                  });
                }
              }
            }
          },
          onStep: (current, total, label) => setProgress({ current, total, label }),
          onPlan: (steps) => setPlanSteps(steps as PlanStep[]),
          // 智能体优化 3.0（阶段 A2，铁律 000）：run 创建 → 更新任务模式指示器
          onRunCreated: (m) => {
            setTaskMode(m.task_mode === "simple" ? "simple" : "complex");
          },
          // 智能体优化 3.0（阶段 A2）：ask_user 提问 → 弹窗
          onQuestion: (q) => {
            setQuestion({
              interaction_id: q.interaction_id,
              question: q.question,
              input_type: q.input_type,
              options: q.options,
            });
          },
          onDone: () => {
            patchAssistant({ running: false });
            setProgress({ current: 0, total: 0, label: "" });
          },
          onError: (msg) => {
            patchAssistant({ content: textBuf + `\n\n⚠️ ${msg}`, running: false });
          },
        },
        ac.signal,
      );
    } catch (e) {
      if ((e as Error).name !== "AbortError") {
        patchAssistant({ content: `\n\n⚠️ 发送失败: ${(e as Error).message}`, running: false });
      }
    } finally {
      setBusy(false);
      abortRef.current = null;
      setRunId(null);
    }
  }

  // 辅助：更新最后一条 assistant 消息（用 ref 避免 updater 内读 state 的反模式）
  const lastToolsRef = useRef<ToolCardState[]>([]);
  // 工具事件驱动图表（generate_chart 完成追加；与 lastToolsRef 同构）
  const lastChartsRef = useRef<ChartSpec[]>([]);

  // Phase 17 P12：从最后一条 assistant 消息派生已完成工具数（不依赖事件计数，
  // 避免 service 事件重复投递导致计数污染）
  const latestAssistantToolsDone = (() => {
    for (let i = messages.length - 1; i >= 0; i--) {
      const m = messages[i];
      if (m.role === "assistant" && m.tools?.length) {
        return m.tools.filter((t) => t.status === "completed").length;
      }
    }
    return 0;
  })();

  function patchAssistant(patch: Partial<Message>) {
    setMessages((m) => {
      const idx = m.length - 1;
      if (idx < 0 || m[idx].role !== "assistant") return m;
      const next = [...m];
      next[idx] = { ...next[idx], ...patch };
      if (patch.tools) lastToolsRef.current = patch.tools;
      if (patch.charts) lastChartsRef.current = patch.charts;
      return next;
    });
  }

  async function handleStop() {
    if (runId) {
      try { await stopRun(runId); } catch { /* 忽略 */ }
    }
    abortRef.current?.abort();
    patchAssistant({ running: false });
    setBusy(false);
    setProgress({ current: 0, total: 0, label: "" });
  }

  // ---------- 渲染 ----------
  return (
    <div className="relative flex min-w-0 flex-1 flex-col">
      {/* 消息流 */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto px-6 pt-6 pb-4">
        <div className="mx-auto max-w-3xl space-y-4">
          {messages.length === 0 && (
            <div className="fade-in-up mt-10 text-center">
              {/* 阶段 7.9.11：单色线性图标（Claude 式）——去渐变/阴影/背景块，克制大方；
                  7.9.11.1：颜色 zinc-300 太浅 → 改黑色 zinc-900 */}
              <FolderOpen size={30} strokeWidth={1.5} className="mx-auto mb-4 text-zinc-900" />
              <h1 className="text-2xl font-semibold text-zinc-800">{project.name}</h1>
              <p className="mt-2 text-sm text-zinc-500">我能帮您做哪些事？核对、查询、建模、出图——一句话完成</p>

              {/* 建议提示词（点击填充输入框，可修改后再发送——对齐 Claude/ChatGPT 交互） */}
              <div className="mt-8 text-left">
                <div className="mb-2 flex items-center gap-1.5 text-[12px] font-medium text-zinc-400">
                  <Sparkles size={12} className="text-amber-500" /> 尝试这样开始
                </div>
                <div className="space-y-2">
                  {suggestions.map((s) => (
                    <button
                      key={s.text}
                      onClick={() => applySuggestion(s.text)}
                      className="group flex w-full items-center gap-2.5 rounded-xl border border-zinc-200 bg-white px-3.5 py-2.5 text-left transition-colors hover:border-blue-300 hover:bg-blue-50/40"
                    >
                      <s.icon size={14} className="shrink-0 text-zinc-400 group-hover:text-blue-600" />
                      <span className="flex-1 truncate text-[13px] text-zinc-700 group-hover:text-blue-700">
                        {s.text}
                      </span>
                      <ArrowRight size={14} className="shrink-0 text-zinc-300 transition-transform group-hover:translate-x-0.5 group-hover:text-blue-500" />
                    </button>
                  ))}
                </div>
              </div>

              {/* 能力清单（告诉用户 agent 能做什么，降低试错成本） */}
              <div className="mt-8">
                <div className="mb-2 flex items-center gap-1.5 text-[12px] font-medium text-zinc-400">
                  <Lightbulb size={12} className="text-amber-500" /> 我能做什么
                </div>
                <div className="flex flex-wrap justify-center gap-1.5">
                  {capabilities.map((c) => (
                    <span
                      key={c.label}
                      title={c.desc}
                      className="inline-flex cursor-default items-center gap-1 rounded-full border border-zinc-200 bg-white px-2.5 py-1 text-[11px] text-zinc-500 transition-colors hover:border-zinc-300 hover:text-zinc-700"
                    >
                      <c.icon size={11} className="text-zinc-400" /> {c.label}
                    </span>
                  ))}
                </div>
              </div>
            </div>
          )}
          {messages.map((msg, i) => (
            <div key={i} className="fade-in-up">
              <MessageBubble msg={msg} />
            </div>
          ))}
          {planSteps.length > 0 && <PlanCard steps={planSteps} />}
          {/* 智能体优化 3.0（阶段 A2，铁律 000）：任务模式指示器
              简单问答（无规划）→ 绿色徽标；复杂任务（含规划）→ 蓝色徽标 */}
          {taskMode && (
            <div className="flex justify-center pt-1">
              <span
                className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-[11px] font-medium ${
                  taskMode === "simple"
                    ? "bg-emerald-50 text-emerald-600"
                    : "bg-blue-50 text-blue-600"
                }`}
              >
                <svg width="10" height="10" viewBox="0 0 24 24" fill="currentColor">
                  {taskMode === "simple" ? (
                    <path d="M9 16.2L4.8 12l-1.4 1.4L9 19 21 7l-1.4-1.4z" />
                  ) : (
                    <path d="M12 2l1.9 5.6L20 9.5l-4.5 4 1.4 6L12 16.5 7.1 19.5l1.4-6-4.5-4 6.1-1.9z" />
                  )}
                </svg>
                {taskMode === "simple" ? "简单问答（无规划）" : "复杂任务（含规划）"}
              </span>
            </div>
          )}
        </div>
      </div>

      {/* 文件/数据按需侧栏（阶段 7.9.10.2：closing 期间仍渲染，播放滑出动画） */}
      {(drawer === "files" || closingDrawer === "files") && (
        <FileDrawer
          projectId={project.id}
          workDir={project.work_dir}
          closing={closingDrawer === "files"}
          onClose={requestCloseDrawer}
          onPick={(path) => { setInput((v) => v + (v ? " " : "") + path); }}
          onRefer={(ref) => { setInput((v) => v + (v ? " " : "") + ref); }} // 阶段 7.9.2：右键引用
          onImported={() => { /* 导入后提示 */ }}
        />
      )}
      {(drawer === "data" || closingDrawer === "data") && (
        <DataPanel
          projectId={project.id}
          closing={closingDrawer === "data"}
          onClose={requestCloseDrawer}
          onRefer={(ref) => { setInput((v) => v + (v ? " " : "") + ref); }} // 阶段 7.9.2：数据库引用
        />
      )}

      {/* 审批弹窗 */}
      {approval && (
        <ApprovalDialog
          toolName={approval.toolName}
          args={approval.args}
          onConfirm={() => { approval.resolve(true); setApproval(null); }}
          onDeny={() => { approval.resolve(false); setApproval(null); }}
        />
      )}

      {/* Composer — 阶段 7.9.3：Codex 风格统一输入容器（无横线分隔、与对话区同一背景、单层高亮） */}
      <div className="px-6 pt-1 pb-4">
        <RunProgress current={progress.current} total={progress.total} label={progress.label} toolsDone={latestAssistantToolsDone} />
        <div className="mx-auto max-w-3xl">
          <div className="composer-shadow relative flex flex-col rounded-xl border border-zinc-300 bg-white transition-all focus-within:border-blue-500">
            {/* 智能体优化 3.0（阶段 A2）：ask_user 抽屉式提问卡——
                absolute bottom-full 浮在 composer（输入框）上方，对齐 VS Code。
                卡片不占文档流，浮层盖在对话区底部上方。 */}
            {question && (
              <AskUserDialog
                payload={question}
                onAnswer={(resp, cancelled) => {
                  fetch(`/api/interactions/${question.interaction_id}/respond`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ response: resp, cancelled }),
                  }).catch(() => { /* 失败由事件流兜底 */ });
                  setQuestion(null);
                }}
                onCancel={() => {
                  fetch(`/api/interactions/${question.interaction_id}/respond`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ response: "", cancelled: true }),
                  }).catch(() => { /* 失败由事件流兜底 */ });
                  setQuestion(null);
                }}
              />
            )}
            {/* 工具行：模型选择 + 工作模式 + 文件 + 数据（幽灵按钮，融入容器顶部） */}
            <div className="flex items-center gap-1 px-2.5 pt-2">
            {/* 模型选择（复用 ModelPicker：官方 logo + 模型名 + 按供应商分组下拉，全站统一） */}
            <ModelPicker
              models={models}
              providers={providers}
              value={model}
              onChange={handleSelectModel}
              disabled={busy}
              direction="up"
            />
            {/* 阶段 G4：工作模式切换（模型徽标右侧、项目目录左侧） */}
            <WorkModeSelector workMode={workMode} onChange={handleSelectWorkMode} />
            <button
              onClick={() => toggleDrawer("files")}
              className={`flex h-7 items-center gap-1.5 rounded-md px-2 text-[12px] transition-colors ${
                drawer === "files"
                  ? "bg-blue-50 text-blue-700"
                  : "text-zinc-500 hover:bg-zinc-100"
              }`}
              title="项目根目录（AI 可读写的全部文件）"
            >
              <FolderOpen size={13} /> 项目目录
            </button>            <button
              onClick={() => toggleDrawer("data")}
              className={`flex h-7 items-center gap-1.5 rounded-md px-2 text-[12px] transition-colors ${
                drawer === "data"
                  ? "bg-blue-50 text-blue-700"
                  : "text-zinc-500 hover:bg-zinc-100"
              }`}
              title="项目数据库"
            >
              <Database size={13} /> 数据
            </button>
            </div>
            {/* 输入行 */}
            <div className="flex items-end gap-2 px-2.5 pb-2.5 pt-1">
            <textarea
              ref={inputRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); handleSend(); } }}
              rows={1}
              placeholder="输入任务…（Enter 发送，Shift+Enter 换行）"
              onDragOver={(e) => e.preventDefault()} // 阶段 7.9.2：允许拖拽引用
              onDrop={(e) => {
                e.preventDefault();
                const ref = e.dataTransfer.getData("text/plain");
                if (ref) setInput((v) => v + (v ? " " : "") + ref); // 插入 @file/@folder/@db 引用
              }}
              className="max-h-40 flex-1 resize-none bg-transparent py-1.5 text-sm text-zinc-800 outline-none focus:outline-none placeholder:text-zinc-400"
            />
            {/* 上下文圆环（阶段 7.8：放输入框右端；阶段 7.9：清空后刷新对话历史） */}
            <ContextIndicator
              projectId={project.id}
              onCleared={() => {
                // 清空上下文后：立即清空本地消息并重新加载（数据库已清，前端同步）
                setMessages([]);
                loadHistory();
              }}
            />
            {busy ? (
              <button onClick={handleStop} className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-red-500 text-white hover:bg-red-400">
                <Square size={14} />
              </button>
            ) : (
              <button
                onClick={handleSend}
                disabled={!input.trim()}
                className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-blue-600 text-white transition-colors hover:bg-blue-500 disabled:opacity-40"
              >
                <Send size={15} />
              </button>
            )}
          </div>
          </div>
        </div>
      </div>
    </div>
  );
}

// ---------- 消息气泡 ----------

function MessageBubble({ msg }: { msg: Message }) {
  if (msg.role === "user") {
    return (
      <div className="flex justify-end">
        <div className="max-w-[85%] whitespace-pre-wrap rounded-2xl rounded-br-md bg-zinc-200 px-4 py-2 text-sm text-zinc-800">
          {msg.content}
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {/* 思考块（P12.3：Beautiful UI Thinking 风格——无边框、shimmer 标题、竖线引导） */}
      {msg.reasoning && <ThinkingBlock text={msg.reasoning} running={!!msg.running} />}
      {/* 工具调用（P12.3：Beautiful UI Tool Chips 风格——无边框、图标行+chip、hover chevron；
          P12.7：运行中自动展开、完成后自动收起） */}
      {msg.tools && msg.tools.length > 0 && <ToolChipList tools={msg.tools} isRunning={!!msg.running} />}
      {/* 工具事件驱动图表（generate_chart 完成即渲染，不依赖 AI 正文写 chart-json） */}
      {msg.charts && msg.charts.length > 0 && (
        <div className="space-y-3">
          {msg.charts.map((c, ci) => <ChartRenderer key={ci} spec={c} />)}
        </div>
      )}
      {/* 正文（P12.4：StreamingMarkdown 丝滑逐词流式 + markdown 兼容） */}
      {msg.content && <StreamingMarkdown text={msg.content} running={!!msg.running} />}
      {/* 运行中动画 */}
      {msg.running && !msg.content && (
        <div className="flex items-center gap-2 text-zinc-400">
          <Loader2 size={14} className="animate-spin" />
          <span className="text-[13px]">思考中…</span>
        </div>
      )}
    </div>
  );
}

// ── P12.3：Beautiful UI Thinking（思考过程，无边框可展开 trace）──
// 对齐 beautifului.dev 的 #Thinking 组件（4 变体，自动检测）：
//  header：星星图标 + shimmer 渐变标题（进行中）/ 灰文本完成态 + chevron 旋转
//  Steps    规划步骤（编号行）→ 序号 + 完成对勾（淡显，不强加每行对勾）
//  Reasoning 深度思考（段落/分节）→ 纯 prose，无图标（不强制）
//  Search   搜索意图（含 搜索/查找/查询 关键词）→ 放大镜图标行
//  Coding   工具意图（含 read/write/edit/run 等工具名）→ 工具行图标

type ThinkingVariant = "steps" | "reasoning" | "search" | "coding";

function detectThinkingVariant(text: string): ThinkingVariant {
  const lines = text.split("\n").map((l) => l.trim()).filter(Boolean);
  if (!lines.length) return "reasoning";

  // 1) 工具意图 → coding（读/写/编辑/执行 等动作词 + 文件名/命令）
  const toolish = lines.filter((l) =>
    /^(read|write|edit|run|exec|create|delete|move|copy|import|export|查询|读取|写入|执行|调用|搜索|查找)/i.test(l));
  if (toolish.length >= Math.min(2, lines.length)) return "coding";

  // 2) 搜索意图 → search（整行是搜索动作，而非"含搜索词"——
  //    P12.6：DeepSeek 思考文本里"查找/查询/搜索"几乎每行都出现，
  //    按含词判定会把整块思考误判成 search（放大镜）；改为要求行首
  //    就是搜索动作动词，或含 search_files/搜索文件 等明确意图）
  const searchish = lines.filter((l) =>
    /^(搜索|查找|查询|搜一下|找一下)\s/.test(l) ||
    /search_files|搜索文件|查找文件|web ?search/i.test(l));
  if (searchish.length >= Math.min(2, lines.length)) return "search";

  // 3) 规划步骤 → steps（短命令式编号/列表行，如 "1. 使用 xxx 工具"）
  //    排除分节标题（"1.1. Facts given in the task" 这类长标题不算步骤）
  const steps = lines.filter((l) => {
    const m = l.match(/^(\d+[\.、)]|[-*])\s*(.+)/);
    if (!m) return false;
    const body = m[2];
    // 短行（≤40 字）+ 命令式（含动词/工具名）才像步骤；长句/标题归 reasoning
    return body.length <= 40 && /使用|调用|执行|读取|查询|检查|列出|写入|分析|比较|导入|导出|运行|确认|打开/.test(body);
  });
  if (steps.length >= Math.min(2, lines.length)) return "steps";

  // 4) 其余 → reasoning（深度思考 prose，无图标）
  return "reasoning";
}

// 智能体优化 3.0（阶段 A2，铁律 000）：超长思考折叠阈值（字符数）。
// 思考完成后文本超过该值 → 默认折叠显示（预览高度 + 渐变遮罩 + 展开按钮），
// 避免展开思考块时被几十段冗长内容刷屏。
const THINK_COLLAPSE_LEN = 600;

function ThinkingBlock({ text, running }: { text: string; running: boolean }) {
  const [open, setOpen] = useState(false);
  // P12.7：运行中自动展开（流式思考可见），完成后自动收起（最智能）
  useEffect(() => {
    setOpen(running);
  }, [running]);
  const [variant, setVariant] = useState<ThinkingVariant>("reasoning");
  // 变体仅用于 header 类型标签（思考/规划/检索/工具），不影响内容渲染——
  // 内容一律 react-markdown 自适应（###→标题 / -→列表 / 1.→有序列表 / 段落→prose）
  useEffect(() => {
    setVariant(detectThinkingVariant(text));
  }, [text]);

  // 思考耗时（组件挂载即计时）
  const startRef = useRef(Date.now());
  useEffect(() => {
    if (!running) return;
    const t = setInterval(() => {
      // 触发重渲染刷新完成态耗时（运行中显示 shimmer 标题不带秒）
      setElapsedTick((v) => v + 1);
    }, 500);
    return () => clearInterval(t);
  }, [running]);
  const [, setElapsedTick] = useState(0);
  const totalSec = Math.round((Date.now() - startRef.current) / 1000);

  // 变体徽标文案（P12.6：多种思考方式标签，不强制图标化内容）
  const variantLabel =
    variant === "steps" ? "规划步骤" :
    variant === "search" ? "检索分析" :
    variant === "coding" ? "工具操作" : "深度思考";

  // 智能体优化 3.0（阶段 A2，铁律 000）：超长思考折叠——思考完成后
  // 若文本超长（> THINK_COLLAPSE_LEN），默认只显示预览高度（+ 渐变遮罩 +
  // 「展开全部」按钮），避免展开思考块时看到几十段冗长内容。
  // 运行中不折叠（实时可见）；完成后折叠。
  const isLong = text.length > THINK_COLLAPSE_LEN;
  const [expanded, setExpanded] = useState(false);
  // 思考内容更新时若变长，保持展开态由用户控制（不自动重置）
  const collapsed = !running && isLong && !expanded;

  return (
    <div className="flex w-full max-w-[95%] flex-col">
      {/* header — 无边框，hover 淡背景 */}
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        className="-mx-1.5 flex w-fit items-center gap-2 rounded-lg px-1.5 py-1 transition-colors duration-100 hover:bg-zinc-100"
      >
        {/* 星星图标（对齐 beautifului Thinking header） */}
        <svg width="15" height="15" viewBox="0 0 24 24" fill="var(--zinc-400, #a1a1aa)">
          <path d="M12 2l2.4 7.2L22 12l-7.6 2.8L12 22l-2.4-7.2L2 12l7.6-2.8z" />
        </svg>
        {running ? (
          <span role="status" className="shimmer-text text-[13px] font-medium whitespace-nowrap">
            思考过程
          </span>
        ) : (
          <span className="fade-in text-[13px] font-medium whitespace-nowrap text-zinc-500">
            思考了 {Math.max(totalSec, 1)}s
          </span>
        )}
        {/* 变体标签（P12.6：展示当前思考方式，内容仍 markdown 自适应） */}
        <span className="rounded-full bg-zinc-100 px-1.5 py-px text-[10px] font-medium text-zinc-400">
          {variantLabel}
        </span>
        <ChevronDown
          size={13}
          className={`text-zinc-400 transition-transform duration-300 ${open ? "rotate-180" : ""}`}
        />
      </button>

      {/* 可展开 trace（grid-rows 动画，对齐 beautifului） */}
      <div
        className="grid transition-[grid-template-rows,opacity] duration-400"
        style={{
          gridTemplateRows: open ? "1fr" : "0fr",
          opacity: open ? 1 : 0,
          transitionTimingFunction: "cubic-bezier(0.23, 1, 0.32, 1)",
        }}
      >
        <div className="overflow-hidden">
          <div className="relative mt-1 ml-[5px] pl-4">
            <span aria-hidden className="absolute left-[3px] top-[-8px] w-px bg-zinc-200" />
            <div className="flex flex-col gap-1 py-1">
              {/* P12.6：内容用 react-markdown 自适应渲染——
                  ### 标题→标题 / - 列表→列表 / 1. 步骤→有序列表 / 段落→prose，
                  每种结构各用其原生方式，不再整块强加对勾/放大镜 */}
              {/* A2：超长思考折叠（预览高度 + 渐变遮罩，展开全部前不渲染全文） */}
              <div
                className={`relative fade-in text-[12.5px] leading-relaxed text-zinc-600 prose-sm [&_h1]:my-2 [&_h1]:text-sm [&_h1]:font-semibold [&_h2]:my-2 [&_h2]:text-[13px] [&_h2]:font-semibold [&_h3]:my-1.5 [&_h3]:text-[13px] [&_h3]:font-semibold [&_ul]:my-1 [&_ul]:list-disc [&_ul]:pl-5 [&_ol]:my-1 [&_ol]:list-decimal [&_ol]:pl-5 [&_li]:my-0.5 [&_p]:my-1 [&_code]:rounded [&_code]:bg-zinc-100 [&_code]:px-1 [&_strong]:font-semibold ${
                  collapsed ? "max-h-[168px] overflow-hidden" : ""
                }`}
              >
                <MarkdownText text={text} />
                {/* 渐变遮罩（折叠时提示下方还有内容） */}
                {collapsed && (
                  <div
                    aria-hidden
                    className="pointer-events-none absolute inset-x-0 bottom-0 h-14 bg-gradient-to-t from-white via-white/80 to-transparent"
                  />
                )}
              </div>
              {/* 展开/收起按钮（超长思考完成后显示） */}
              {!running && isLong && (
                <button
                  type="button"
                  onClick={() => setExpanded((e) => !e)}
                  className="fade-in -mx-1.5 flex w-fit items-center gap-1 rounded-md px-1.5 py-0.5 text-[11px] text-zinc-400 transition-colors hover:bg-zinc-100 hover:text-zinc-600"
                >
                  {expanded ? (
                    <>
                      <ChevronDown size={12} className="rotate-180" />
                      收起思考
                    </>
                  ) : (
                    <>
                      <ChevronDown size={12} />
                      展开全部思考（共 {text.length} 字）
                    </>
                  )}
                </button>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

// ── P12.3：Beautiful UI Tool Chips（工具调用，无边框）──
// 对齐 beautifului.dev 的 #Tool Chips 组件：
//  header：chevron + "N tool calls"（小号灰文本，点击折叠）
//  行：图标 + label + chip（浅灰圆角 pill 工具名）+ 耗时，hover 行显 chevron
//  展开：border-l 竖线 + 输入/输出详情
//  状态：running→spinner，completed→check，failed→red

function fmtDuration(ms: number): string {
  if (!ms || ms <= 0) return "";
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${Math.round(ms)}ms`;
}

// 工具图标映射（对齐 beautifului Icons：write/run/read/search/think）
function toolIcon(name: string) {
  const n = (name || "").toLowerCase();
  if (/(write|update|insert|delete|export|import|move|copy)/.test(n)) return <PenLine size={13} />;
  if (/(run|command|execute|shell)/.test(n)) return <Play size={13} />;
  if (/(read|query|analyze|compare|stats|info|sheet|table)/.test(n)) return <FileText size={13} />;
  if (/(search|find|list)/.test(n)) return <Search size={13} />;
  return <Wrench size={13} />;
}

function ToolChipList({ tools, isRunning }: { tools: ToolCardState[]; isRunning?: boolean }) {
  // P12.7：运行中自动展开（实时看到工具调用），完成后自动收起（点击可随时手动切换）
  const [open, setOpen] = useState(false);
  useEffect(() => {
    setOpen(!!isRunning);
  }, [isRunning]);
  const failed = tools.filter((t) => t.status === "failed").length;
  const running = tools.filter((t) => t.status === "running").length;
  const totalMs = tools.reduce((s, t) => s + (t.duration_ms || 0), 0);

  return (
    <div className="pb-1">
      {/* 聚合头 — 无边框，chevron + 计数（对齐 beautifului Tool Chips header） */}
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        className="-mx-1.5 flex w-fit items-center gap-1.5 rounded-lg px-1.5 py-1 text-[12.5px] text-zinc-500 transition-colors duration-100 hover:bg-zinc-100"
      >
        <ChevronDown
          size={12}
          className={`text-zinc-400 transition-transform duration-200 ${open ? "rotate-0" : "-rotate-90"}`}
        />
        <span className="tabular-nums">
          {tools.length} 次工具调用
          {failed > 0 && <span className="text-red-500"> · {failed} 失败</span>}
          {running > 0 && <span className="text-blue-500"> · 运行中</span>}
          {totalMs > 0 && <span className="text-zinc-400"> · {fmtDuration(totalMs)}</span>}
        </span>
      </button>

      {/* 工具调用行（grid-rows 动画） */}
      <div
        className="grid transition-[grid-template-rows,opacity] duration-300"
        style={{ gridTemplateRows: open ? "1fr" : "0fr", opacity: open ? 1 : 0 }}
      >
        {/* -mx-1 + px-1.5 让 hover pill 有呼吸空间 */}
        <div className="-mx-1 overflow-hidden px-1.5 pb-1">
          <div className="mt-1.5 flex flex-col gap-1">
            {tools.map((t) => (
              <ToolChipRow key={t.id} tool={t} />
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

function ToolChipRow({ tool }: { tool: ToolCardState }) {
  const [open, setOpen] = useState(false);
  const dur = fmtDuration(tool.duration_ms || 0);
  const icon = toolIcon(tool.name);

  return (
    <div>
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        className="group/row -mx-[3px] flex h-7 w-[calc(100%+6px)] min-w-0 items-center gap-2 rounded-lg px-[3px] text-left transition-colors duration-100 hover:bg-zinc-100"
      >
        {/* 图标 + hover chevron（对齐 beautifului：hover 时图标淡出 chevron 淡入） */}
        <span className="relative flex size-4 shrink-0 items-center justify-center text-zinc-400">
          <span className={`transition-opacity duration-100 ${open ? "opacity-0" : "group-hover/row:opacity-0"}`}>
            {icon}
          </span>
          <ChevronRight
            size={12}
            className={`absolute transition-[opacity,transform] duration-150 group-hover/row:opacity-100 ${open ? "rotate-0 opacity-100" : "-rotate-90 opacity-0"}`}
          />
        </span>
        <span className="shrink-0 text-[12.5px] font-medium text-zinc-700">
          {tool.title || tool.name}
        </span>
        {/* chip：浅灰圆角 pill 显示工具名/参数（对齐 beautifului chip） */}
        <span className="inline-flex h-5.5 min-w-0 flex-1 cursor-pointer items-center truncate rounded-full bg-zinc-100 px-1.5 font-mono text-[11.5px] text-zinc-500 shadow-sm transition-colors duration-100 hover:bg-zinc-200">
          {tool.input || tool.name}
        </span>
        {dur && <span className="shrink-0 font-mono text-[10.5px] tabular-nums text-zinc-400">{dur}</span>}
        {tool.status === "running" && (
          <Loader2 size={11} className="spin-slow shrink-0 text-blue-500" />
        )}
      </button>

      {/* 展开详情（border-l 竖线引导，对齐 beautifului） */}
      <div
        className="grid transition-[grid-template-rows,opacity] duration-300"
        style={{
          gridTemplateRows: open ? "1fr" : "0fr",
          opacity: open ? 1 : 0,
          transitionTimingFunction: "cubic-bezier(0.23, 1, 0.32, 1)",
        }}
      >
        <div className="min-h-0 overflow-hidden">
          <div className="mt-0.5 mb-1 ml-2 flex flex-col gap-1 border-l border-zinc-200 py-0.5 pl-3.5">
            {tool.input && (
              <span className="font-mono text-[11.5px] leading-[1.6] text-zinc-500 whitespace-pre-wrap break-all">{tool.input}</span>
            )}
            {tool.output && (
              <span className="max-h-48 overflow-auto font-mono text-[11.5px] leading-[1.6] text-zinc-600 whitespace-pre-wrap break-all">{tool.output}</span>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

