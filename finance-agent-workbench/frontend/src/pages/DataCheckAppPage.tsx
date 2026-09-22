/** DataCheckAppPage — 数据核对与校验集成应用（8 步流程版）。
 *
 * 8 步流程（步骤条常驻，一开始全显示，随时可回退）：
 *   1 数据文件 → 2 匹配键 → 3 核对变量 → 4 容差 → 5 处理策略
 *   → 6 校验（AI 执行 + 结果报告）→ 7 确认修改（写回确认）
 *   → 8 最终输出（输出文件 + 下载）
 *
 * 应用独立性（需求 ②）：本应用绑定独立隐藏项目（__app_recon__），
 * 数据区为固定目录 data/app-workspaces/recon，与用户项目数据库完全隔离——
 * 上传文件、导入、AI 运行全部走应用项目，不依赖任何项目历史结果。
 */

import { useCallback, useEffect, useRef, useState } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  Square, Wrench, CheckCircle2, Download, FileText, Play, ChevronRight, ChevronDown, History, RotateCw,
} from "lucide-react";
import type { Project, ModelOption, AgentOption, FileEntry, SkillDetail, Provider } from "../lib/api";
import {
  listProjects, createProject, listDataFiles, fetchSkillDetail, fetchFileTree,
  reconVerify, reconAudit, reconWriteback, updateProject,
  openExternalFile,
  type ReconVerifyParams, type ReconAuditItem, type ReconAuditDecision,
  type ReconDiffData,
} from "../lib/api";
import ModelPicker from "../components/ModelPicker";
import { useReconRun } from "../hooks/useReconRun";
import ReconWizard, { type ReconParams } from "../components/ReconWizard";
import AppDataPanel from "../components/AppDataPanel";
import AskUserDialog from "../components/AskUserDialog";
import LoadingState from "../components/LoadingState";

/** markdown 渲染样式（与 ChatPage 对齐） */
const PROSE_CLASS =
  "prose-sm max-w-none text-sm leading-relaxed text-zinc-800 " +
  "[&_table]:my-2 [&_table]:w-full [&_table]:border-collapse [&_table]:border [&_table]:border-zinc-300 " +
  "[&_th]:border [&_th]:border-zinc-300 [&_th]:bg-zinc-100 [&_th]:px-2 [&_th]:py-1 " +
  "[&_td]:border [&_td]:border-zinc-300 [&_td]:px-2 [&_td]:py-1 " +
  "[&_pre]:my-2 [&_pre]:overflow-auto [&_pre]:rounded-md [&_pre]:bg-zinc-100 [&_pre]:p-3 " +
  "[&_code]:rounded [&_code]:bg-zinc-100 [&_code]:px-1 " +
  "[&_h1]:my-3 [&_h1]:text-lg [&_h2]:my-2 [&_h2]:text-base [&_h3]:my-2 [&_h3]:text-sm " +
  "[&_ul]:my-1 [&_ul]:list-disc [&_ul]:pl-5 [&_ol]:my-1 [&_ol]:list-decimal [&_ol]:pl-5";

/** 6 步流程步骤定义（常驻步骤条）：
 *  1 数据文件 → 2 匹配键 → 3 核对变量 → 4 容差&处理策略 → 5 校验 → 6 修改
 *  步骤 4 合并「容差 + 处理策略」（容差本身是一种处理策略）；
 *  步骤 5 校验 = 执行中 + 结果 + 多轮审计循环；步骤 6 修改 = 方案确认→执行→报告。
 */
const FLOW_STEPS = [
  { n: 1, label: "数据文件" },
  { n: 2, label: "匹配键" },
  { n: 3, label: "核对变量" },
  { n: 4, label: "容差&策略" },
  { n: 5, label: "校验" },
  { n: 6, label: "修改" },
];

/** 差异表每页条数（大数据分页；后端 MAX_DIFFS=500 截断，前端按页浏览） */
const DIFF_PAGE_SIZE = 200;
/** 历史运行记录 localStorage key（最新在前，最多保留 HISTORY_MAX 条） */
const HISTORY_KEY = "app_recon_run_history";
const HISTORY_MAX = 10;

/** 时间格式化（MM-DD HH:mm） */
function fmtTime(ts: number): string {
  const d = new Date(ts);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

/** 差异级别元信息（颜色/文案） */
const LEVEL_META: Record<string, { label: string; color: string; bg: string; selectable: boolean }> = {
  OK: { label: "OK", color: "text-emerald-600", bg: "bg-emerald-50", selectable: false },
  A1: { label: "A1 漏填", color: "text-amber-600", bg: "bg-amber-50", selectable: true },
  A2: { label: "A2 误差", color: "text-amber-600", bg: "bg-amber-50", selectable: true },
  B: { label: "B 待确认", color: "text-blue-600", bg: "bg-blue-50", selectable: true },
  C: { label: "C 无法匹配", color: "text-red-600", bg: "bg-red-50", selectable: false },
};

/** 待审计清单：side 元信息（分组 tab） */
const AUDIT_SIDE_META: Record<string, { label: string; color: string; bg: string }> = {
  base: { label: "总表独有", color: "text-amber-600", bg: "bg-amber-50" },
  detail: { label: "分表独有", color: "text-blue-600", bg: "bg-blue-50" },
  ambiguous: { label: "一对多模糊", color: "text-purple-600", bg: "bg-purple-50" },
};

/** 审计决策选项（按 side） */
const AUDIT_DECISION_OPTIONS: Record<string, string[]> = {
  base: ["补录到分表", "忽略(总表误记)", "挂起"],
  detail: ["补录到总表", "忽略(分表误记)", "挂起"],
  ambiguous: ["确认对应关系", "挂起"],
};

/** 结构化差异行（AI 校验报告 recon-data 块解析而来） */
interface ReconDiff {
  level: string;
  contract?: string;
  person?: string;
  client?: string;
  base_amount?: number | null;
  target_amount?: number | null;
  diff?: number | null;
  reason?: string;
  suggestion?: string;
  [k: string]: unknown;
}

interface ReconData {
  summary: { ok: number; a1: number; a2: number; b: number; c: number };
  diffs: ReconDiff[];
}

/** 历史运行记录（校验完成后自动存档，供回看 + 一键重跑） */
interface ReconRunRecord {
  id: string;
  time: number;
  params: ReconParams;
  summary: ReconData["summary"] | null;
  diffs: ReconDiff[];
  auditCount: number;
  report: string;
  runId: string;
}

/** 金额格式化（千分位 + 2 位小数；null → —） */
function fmtAmount(v: number | null | undefined): string {
  if (v == null || Number.isNaN(v)) return "—";
  return v.toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

/** 应用专属隐藏项目标识（列表过滤 + localStorage 缓存 key） */
const APP_PROJECT_NAME = "__app_recon__";
const APP_PROJECT_KEY = "app_recon_project_id";
/** 应用数据区（相对工作台根；后端 _project_root 会自动创建） */
const APP_WORK_DIR = "d:/Finance Recon Agent/finance-agent-workbench/data/app-workspaces/recon";

/** 获取（缓存/复用）或创建应用专属项目。
 * 复用策略：按名称查找现有应用项目，优先选择「已有文件」的（避免缓存指向空项目）。 */
async function ensureAppProject(defaultModel: string): Promise<Project> {
  // includeHidden=true：后端 /api/projects 默认隐藏 __app_ 前缀，应用内部显式查找复用
  const list = await listProjects(true);
  const apps = list.filter((p) => p.name === APP_PROJECT_NAME);
  if (apps.length > 0) {
    let best = apps[0];
    let bestCount = -1;
    for (const p of apps) {
      try {
        const r = await listDataFiles(p.id);
        const n = (r.files || []).length;
        if (n > bestCount) {
          bestCount = n;
          best = p;
        }
      } catch { /* 查文件失败跳过 */ }
    }
    localStorage.setItem(APP_PROJECT_KEY, best.id);
    return best;
  }
  const created = await createProject({
    name: APP_PROJECT_NAME,
    work_dir: APP_WORK_DIR,
    default_model: defaultModel || undefined,
    description: "数据核对与校验集成应用（隐藏）",
  });
  localStorage.setItem(APP_PROJECT_KEY, created.id);
  return created;
}

/** raw 文件下载/打开 URL（复用 /api/files/raw?binary=1） */
function rawUrl(projectId: string, path: string, binary: boolean): string {
  return `/api/files/raw?project_id=${encodeURIComponent(projectId)}&path=${encodeURIComponent(path)}${binary ? "&binary=1" : ""}`;
}

/** 参数 → 中文摘要（供校验/写回 prompt 共用） */
function paramSummary(p: ReconParams): string {
  const keys = [p.matchKeys.k1, p.matchKeys.k2On ? p.matchKeys.k2 : "", p.matchKeys.k3On ? p.matchKeys.k3 : ""]
    .filter(Boolean)
    .join(" > ");
  const actionLabel =
    p.unmatchedAction === "list"
      ? "A. 列清单供人工复核"
      : p.unmatchedAction === "fallback"
        ? "B. 按（人员+客户）降级匹配"
        : p.unmatchedAction === "mark"
          ? "C. 全部标记无法匹配"
          : `自定义：${p.unmatchedAction}`;
  return (
    `- 依据表：${p.baseFile}（应用数据库内，直接复用）\n` +
    `- 分表：${p.detailFile}（应用数据库内，直接复用）\n` +
    `- 匹配键层级：${keys}\n` +
    // 2026-08-20：核对变量是【分表】字段；依据表金额列由向导步骤 3 显式选择。
    // 确定性链路直接传 amount_col = "依据表列->分表列"，不再依赖 AI 猜测。
    `- 核对变量：${p.variables.join("、")}（分表字段）\n` +
    `- 依据表金额列：${p.baseAmountCol}（与分表第一项 ${p.variables[0]} 对应；` +
    `reconcile_variables 的 amount_col 传 "${p.baseAmountCol}->${p.variables[0]}"）\n` +
    `- 容差：${p.tolerance} 元\n` +
    `- 匹配不上处理：${actionLabel}\n` +
    `- 差异自动处理：${p.autoFix ? "开启（A 类自动写回）" : "关闭（仅报告不写回）"}`
  );
}

export default function DataCheckAppPage({
  project,
  models,
  agents,
  providers,
  defaultModel,
}: {
  project: Project;
  models: ModelOption[];
  agents: AgentOption[];
  providers: Provider[];
  defaultModel: string;
}) {
  // 6 步流程状态（步骤条常驻，可回退到已到达步骤）
  const [flowStep, setFlowStep] = useState(1);
  // 配置阶段（1-4）初始全部可达；5 校验 / 6 修改 逐步解锁
  const [maxReached, setMaxReached] = useState(4);
  const [params, setParams] = useState<ReconParams | null>(null);
  const [finalStatus, setFinalStatus] = useState("completed");
  // 结构化差异数据（步骤 6 校验结果，步骤 7 渲染差异表；工具直出，100% 可靠）
  const [reconData, setReconData] = useState<ReconData | null>(null);
  // 校验运行状态（2026-08-20 混合模式：确定性核对 + 一次 LLM 报告，本地 loading）
  const [verifyBusy, setVerifyBusy] = useState(false);
  const [verifyError, setVerifyError] = useState("");
  const [verifyReport, setVerifyReport] = useState("");
  // 执行阶段（混合模式明细）：0=确定性核对中 / 1=AI 报告生成中 / 2=完成
  const [verifyStage, setVerifyStage] = useState(0);
  // 各阶段实际耗时（ms；完成后展示）
  const [stageTimes, setStageTimes] = useState<{ reconcile: number; report: number }>({ reconcile: 0, report: 0 });
  // 执行明细抽屉（点击加载组件展开，默认收起）
  const [detailOpen, setDetailOpen] = useState(false);
  // 项目数据库抽屉（2026-08-21：步骤 1「项目数据库」按钮 → 右侧弹出；上传/删除/刷新）
  const [dbOpen, setDbOpen] = useState(false);
  const [dbClosing, setDbClosing] = useState(false);
  // 数据库变更触发号（onImported/删除后自增 → ReconWizard refreshTick 重新拉取下拉）
  const [dbTick, setDbTick] = useState(0);

  /** 请求关闭数据库抽屉：先播放滑出动画，260ms 后再卸载 */
  const requestCloseDb = useCallback(() => {
    if (!dbOpen || dbClosing) return;
    setDbClosing(true);
    window.setTimeout(() => {
      setDbOpen(false);
      setDbClosing(false);
    }, 260); // 与 drawer-slide-out 时长一致
  }, [dbOpen, dbClosing]);
  // 多轮审计循环（2026-08-20 第二步）：当前 run + 待审计清单 + 逐条决策
  const [runId, setRunId] = useState("");
  const [auditItems, setAuditItems] = useState<ReconAuditItem[]>([]);
  const [auditBusy, setAuditBusy] = useState(false);
  // 决策表：key = `${side}:${key}` → decision 中文
  const [auditDecisions, setAuditDecisions] = useState<Record<string, string>>({});
  // 待审计清单筛选（ALL | base | detail | ambiguous）
  const [auditFilter, setAuditFilter] = useState("ALL");
  // 待审计清单分页（每页 50 条）
  const [auditPage, setAuditPage] = useState(1);
  // 审计完成提示（下一轮无剩余时展示）
  const [auditDone, setAuditDone] = useState(false);
  // 差异勾选集合（key = 索引；A1/A2 默认勾选、B 需人工勾选、C 不可勾选）
  const [checkedIdx, setCheckedIdx] = useState<Set<number>>(new Set());
  // 差异表级别筛选（"ALL" | OK | A1 | A2 | B | C）
  const [diffFilter, setDiffFilter] = useState("ALL");
  // 差异表大数据分页（每页 DIFF_PAGE_SIZE 条；勾选集合仍按全局索引）
  const [diffPage, setDiffPage] = useState(1);
  // 历史运行记录（localStorage 持久化：回看报告/差异 + 一键重跑）
  const [history, setHistory] = useState<ReconRunRecord[]>([]);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [activeHistory, setActiveHistory] = useState<ReconRunRecord | null>(null);
  // 写回完成状态（步骤 6 展示写回报告）
  const [writebackDone, setWritebackDone] = useState(false);
  // 确定性写回（2026-08-21：写回走后端 API，不再依赖 LLM Agent 编排）
  const [writebackBusy, setWritebackBusy] = useState(false);
  const [writebackReport, setWritebackReport] = useState("");
  // 应用专属项目（独立数据区）
  const [appProject, setAppProject] = useState<Project | null>(null);
  const [appError, setAppError] = useState("");
  // 输出物（应用工作区文件列表）
  const [outputs, setOutputs] = useState<FileEntry[]>([]);
  // 应用 AI 提示词展示（skill 职责/约束）
  const [skill, setSkill] = useState<SkillDetail | null>(null);
  const loadedRef = useRef(false);

  // 模型/agent 取项目默认（与 ChatPage 默认逻辑一致）；模型可切换（2026-08-20）
  const defaultModelId =
    models.find((m) => m.id === defaultModel)?.id ||
    models.find((m) => m.is_default === 1)?.id ||
    models[0]?.id ||
    "";
  const [model, setModel] = useState(defaultModelId);
  const agent = agents[0]?.name || "general-agent";

  // 初始化：确保应用专属项目 + 拉取 skill 提示词
  useEffect(() => {
    if (loadedRef.current) return;
    loadedRef.current = true;
    ensureAppProject(model || defaultModel)
      .then((p) => setAppProject(p))
      .catch((e) => setAppError(`应用数据区初始化失败: ${(e as Error).message}`));
    fetchSkillDetail("data-reconcile")
      .then((s) => setSkill(s))
      .catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // 刷新输出物列表
  const refreshOutputs = useCallback(() => {
    if (!appProject) return;
    fetchFileTree(appProject.id, "")
      .then((r) => setOutputs(r.entries))
      .catch(() => {});
  }, [appProject]);

  // 写回（步骤 6 修改）仍走 Agent 链路（ask_user 逐条确认 B 类差异 + update_rows + 回写 Excel）
  const { busy, question, stop, answer } = useReconRun({
    projectId: appProject?.id || "",
    agent,
    model,
    workMode: project.work_mode === "auto" ? "auto" : "manual",
    onFinished: (_reason, _finalReport) => {
      // 写回完成 → 停在 6（修改完成，展示输出文件），刷新输出物
      setFinalStatus(_reason);
      setWritebackDone(true);
      setMaxReached((m) => Math.max(m, 6));
      setFlowStep(6);
      refreshOutputs();
    },
  });

  /** 切换模型：更新本地 state + 持久化到应用项目（__app_recon__ 的 default_model）。
   * 语义：用户选择的模型 = 每次调用 AI 服务时请求的 API；任务执行中不可切换，
   * 下次调用任务时使用最新选择。 */
  const handleSelectModel = useCallback(
    async (m: ModelOption) => {
      setModel(m.id);
      if (appProject) {
        try {
          await updateProject(appProject.id, { default_model: m.id });
          setAppProject((p) => (p ? { ...p, default_model: m.id } : p));
        } catch (e) {
          alert(`切换模型失败: ${(e as Error).message}`);
        }
      }
    },
    [appProject],
  );

  /** 保存一次运行记录（localStorage，最新在前，最多 HISTORY_MAX 条） */
  const saveHistory = useCallback((record: ReconRunRecord) => {
    setHistory((prev) => {
      const next = [record, ...prev].slice(0, HISTORY_MAX);
      try {
        localStorage.setItem(HISTORY_KEY, JSON.stringify(next));
      } catch {
        /* localStorage 超限/不可用时静默降级为内存态 */
      }
      return next;
    });
  }, []);

  /** 加载历史运行记录（进入应用时） */
  const loadHistory = useCallback(() => {
    try {
      const raw = localStorage.getItem(HISTORY_KEY);
      setHistory(raw ? (JSON.parse(raw) as ReconRunRecord[]) : []);
    } catch {
      setHistory([]);
    }
  }, []);

  useEffect(() => { loadHistory(); }, [loadHistory]);

  /** 一键重跑：历史参数回填向导 → 回到步骤 1（ReconWizard initial 全参数回填） */
  const handleRerun = useCallback((record: ReconRunRecord) => {
    setParams(record.params);
    setActiveHistory(null);
    setHistoryOpen(false);
    setMaxReached((m) => Math.max(m, 4)); // 步骤 1-4 向导可达
    setFlowStep(1);
  }, []);

  /** 向导提交（步骤 4「开始校验」）→ 步骤 5：确定性核对 + 一次 LLM 报告（混合模式） */
  const handleStart = useCallback(
    async (p: ReconParams) => {
      if (!appProject) return;
      setParams(p);
      setMaxReached((m) => Math.max(m, 5));
      setFlowStep(5);
      setVerifyBusy(true);
      setVerifyError("");
      setVerifyReport("");
      setAuditDone(false);
      setVerifyStage(0);
      setDetailOpen(false);
      const t0 = performance.now();
      // 阶段推进：确定性核对秒级 → 切到报告生成（真实耗时以 performance 为准）
      const stageTimer = window.setTimeout(() => setVerifyStage(1), 1200);
      try {
        // 后端：reconcile_variables 确定性核对（秒级）+ LLM 一次生成报告
        const res = await reconVerify(appProject.id, model, p as ReconVerifyParams);
        window.clearTimeout(stageTimer);
        setReconData(res.reconData);
        setVerifyReport(res.report);
        setRunId(res.runId);
        setAuditItems(res.auditItems || []);
        setAuditDecisions({});
        setAuditPage(1);
        setDiffPage(1);
        setFinalStatus("completed");
        setVerifyStage(2);
        setStageTimes({ reconcile: 1200, report: performance.now() - t0 - 1200 });
        // A1/A2 默认勾选（可自动处理）；B 不勾选（需人工确认）；C 不可勾选
        const init = new Set<number>();
        (res.reconData?.diffs || []).forEach((d, i) => {
          if (d.level === "A1" || d.level === "A2") init.add(i);
        });
        setCheckedIdx(init);
        setWritebackDone(false);
        setWritebackReport("");
        setFlowStep(5);
        // 校验完成 → 存档历史（回看 + 一键重跑）
        saveHistory({
          id: res.runId || `r_${Date.now()}`,
          time: Date.now(),
          params: p,
          summary: res.reconData?.summary || null,
          diffs: res.reconData?.diffs || [],
          auditCount: (res.auditItems || []).length,
          report: res.report || "",
          runId: res.runId || "",
        });
      } catch (e) {
        window.clearTimeout(stageTimer);
        setVerifyError((e as Error).message);
        setFinalStatus("failed");
        setVerifyStage(2);
      } finally {
        setVerifyBusy(false);
      }
    },
    [appProject, model, saveHistory],
  );

  /** 提交审计决策 → 下一轮核对（多轮审计循环闭环） */
  const handleAuditSubmit = useCallback(async () => {
    if (!params || !runId) return;
    const decisions: ReconAuditDecision[] = Object.entries(auditDecisions)
      .filter(([, d]) => d && d !== "挂起")
      .map(([k, decision]) => {
        const [side, ...rest] = k.split(":");
        return { side, key: rest.join(":"), decision };
      });
    if (decisions.length === 0) return;
    setAuditBusy(true);
    try {
      const res = await reconAudit(runId, appProject!.id, params as ReconVerifyParams, decisions);
      setReconData(res.reconData);
      setAuditItems(res.auditItems || []);
      setAuditDecisions({});
      setAuditPage(1);
      setAuditDone(res.remaining === 0);
    } catch (e) {
      setVerifyError((e as Error).message);
    } finally {
      setAuditBusy(false);
    }
  }, [params, runId, auditDecisions, appProject]);

  /** 设置单条审计决策 */
  const setAuditDecision = useCallback((side: string, key: string, decision: string) => {
    setAuditDecisions((prev) => {
      const next = { ...prev };
      if (decision === "挂起" || decision === "") {
        delete next[`${side}:${key}`];
      } else {
        next[`${side}:${key}`] = decision;
      }
      return next;
    });
  }, []);

  /** 批量设置决策（某 side 全部项统一决策） */
  const setAuditBatch = useCallback((side: string, decision: string) => {
    setAuditDecisions((prev) => {
      const next = { ...prev };
      auditItems
        .filter((a) => a.side === side)
        .forEach((a) => {
          if (decision === "挂起") delete next[`${side}:${a.key}`];
          else next[`${side}:${a.key}`] = decision;
        });
      return next;
    });
  }, [auditItems]);

  /** 步骤 5（校验完成）→ 步骤 6 修改 */
  const handleToConfirm = useCallback(() => {
    setFlowStep(6);
    setMaxReached((m) => Math.max(m, 6));
  }, []);

  /** 步骤 6「确认修改」→ 确定性写回（临时库 update_rows + 精确回写 Excel） */
  const handleWriteback = useCallback(async () => {
    if (!params || !runId) return;
    const confirmed = (reconData?.diffs || [])
      .filter((_, i) => checkedIdx.has(i))
      .map((d) => ({ ...d }));
    if (confirmed.length === 0) return;
    setWritebackBusy(true);
    setWritebackDone(false);
    try {
      const res = await reconWriteback(runId, appProject!.id, params as ReconVerifyParams, confirmed as ReconDiffData[]);
      setWritebackReport(res.report);
      setWritebackDone(true);
      setMaxReached((m) => Math.max(m, 6));
      setFlowStep(6);
      refreshOutputs();
    } catch (e) {
      setVerifyError(`写回失败: ${(e as Error).message}`);
    } finally {
      setWritebackBusy(false);
    }
  }, [params, runId, reconData, checkedIdx, appProject, refreshOutputs]);

  /** 勾选/取消一条差异 */
  const toggleDiff = useCallback((idx: number) => {
    setCheckedIdx((prev) => {
      const next = new Set(prev);
      if (next.has(idx)) next.delete(idx);
      else next.add(idx);
      return next;
    });
  }, []);

  /** 全选 / 取消全选（仅可选级别 A1/A2/B） */
  const toggleAll = useCallback(() => {
    const selectable = (reconData?.diffs || []).map((d, i) => ({ d, i })).filter(({ d }) => LEVEL_META[d.level]?.selectable);
    setCheckedIdx((prev) => {
      const allChecked = selectable.length > 0 && selectable.every(({ i }) => prev.has(i));
      const next = new Set(prev);
      if (allChecked) selectable.forEach(({ i }) => next.delete(i));
      else selectable.forEach(({ i }) => next.add(i));
      return next;
    });
  }, [reconData]);

  /** 步骤条跳转（只能回退到已到达步骤；运行中禁止） */
  const gotoStep = useCallback(
    (n: number) => {
      if (busy || n > maxReached) return;
      setFlowStep(n);
    },
    [busy, maxReached],
  );

  /** 打开输出物（D7：office → 本地打开；md/文本/pdf/图片 → 新标签页预览） */
  const handleOpenOutput = useCallback(
    (f: FileEntry) => {
      if (!appProject) return;
      const ext = f.name.toLowerCase();
      if (/\.(docx|xlsx|xls|ppt|pptx)$/.test(ext)) {
        void openExternalFile(appProject.id, f.path).catch((e) =>
          alert(`打开失败: ${(e as Error).message}`));
        return;
      }
      // md / txt / pdf / 图片 等 → 新标签页预览（独立 tab，可自由切换）
      const url = `/?preview=1&project_id=${encodeURIComponent(appProject.id)}&path=${encodeURIComponent(f.path)}`;
      window.open(url, "_blank");
    },
    [appProject],
  );

  /** 下载输出物 */
  const handleDownloadOutput = useCallback(
    (f: FileEntry) => {
      if (!appProject) return;
      const a = document.createElement("a");
      a.href = rawUrl(appProject.id, f.path, true);
      a.download = f.name;
      a.click();
    },
    [appProject],
  );

  // 初始化加载中
  if (!appProject) {
    return (
      <div className="flex flex-1 items-center justify-center gap-2 text-[13px] text-zinc-400">
        {appError ? (
          <span className="text-red-500">{appError}</span>
        ) : (
          <LoadingState label="正在初始化应用数据区…" />
        )}
      </div>
    );
  }

  // ---------- 共享头部（所有步骤统一：标题 + AI 模型选择 + 应用专用 AI 卡；步骤导航移至左侧） ----------
  const appHeader = (
    <div className="border-b border-zinc-200 bg-white px-6 pt-4 pb-3">
      <div className="mx-auto max-w-6xl space-y-3">
        {/* 标题 + 模型选择（标题行固定不变，切换的是下方表单；模型选择器与项目页共用 ModelPicker） */}
        <div className="flex items-center justify-between gap-3">
          <div>
            <h1 className="text-lg font-semibold text-zinc-900">数据核对与校验</h1>
            <p className="mt-0.5 text-[13px] text-zinc-500">按向导配置两表核对，AI 自动完成匹配、分级、归因与写回。</p>
          </div>
          {/* 模型选择（复用 ModelPicker：官方 logo + 模型名 + 按供应商分组下拉，与项目页完全一致） */}
          <div className="shrink-0 rounded-lg border border-zinc-200 bg-white">
            <ModelPicker
              models={models}
              providers={providers}
              value={model}
              onChange={handleSelectModel}
              disabled={busy || verifyBusy}
              direction="down"
            />
          </div>
        </div>

        {/* 应用专用 AI（折叠卡，与向导页一致） */}
        {skill && (
          <details className="overflow-hidden rounded-xl border border-zinc-200">
            <summary className="flex cursor-pointer select-none items-center gap-2 px-3.5 py-2 transition-colors hover:bg-zinc-50">
              <BotIcon />
              <span className="text-[12.5px] font-semibold text-zinc-800">应用专用 AI</span>
              <span className="rounded-full bg-zinc-100 px-1.5 py-px text-[10px] font-medium text-zinc-500">data-reconcile skill</span>
              <span className="ml-auto text-[11px] text-zinc-400">点击查看 AI 职责与约束</span>
            </summary>
            <div className="border-t border-zinc-100 px-3.5 py-2.5">
              <p className="text-[12px] leading-relaxed text-zinc-600">
                本应用内 AI 是「数据核对专用工具」，不是通用智能体：只按向导参数执行两表金额核对（匹配→分级→归因→报告），禁止自由发挥、禁止扩大核对范围，使结果流程确定性收敛。
              </p>
              {skill.purpose && (
                <p className="mt-1.5 text-[12px] leading-relaxed text-zinc-500">
                  <span className="font-medium text-zinc-700">职责：</span>
                  {skill.purpose}
                </p>
              )}
              {skill.constraints && (
                <p className="mt-1.5 whitespace-pre-line text-[12px] leading-relaxed text-zinc-500">
                  <span className="font-medium text-zinc-700">约束：</span>
                  {skill.constraints}
                </p>
              )}
            </div>
          </details>
        )}
      </div>
    </div>
  );

  // ---------- 运行中面板（步骤 5 校验 busy：确定性核对 + LLM 报告，本地 loading） ----------
  // 2026-08-20：左对齐靠上；点击加载组件弹出「执行明细」抽屉（默认收起），
  // 抽屉式滑出动画（drawer-up）展示混合模式两阶段：确定性核对 → AI 报告生成。
  const runningPanel = (
    <div className="min-h-0 flex-1 overflow-y-auto px-6 pt-5 pb-4">
      <div className="mx-auto max-w-3xl space-y-3">
        {/* 状态行（左上）：加载组件本身可点击 → 抽屉明细 */}
        <div className="flex flex-wrap items-center gap-3">
          <button
            onClick={() => setDetailOpen((o) => !o)}
            className="group flex items-center gap-2.5 rounded-xl border border-zinc-200 bg-white px-4 py-3 text-left transition-colors hover:border-zinc-300"
            title={detailOpen ? "收起执行明细" : "点击查看执行明细"}
          >
            <LoadingState label="AI 正在核对两表金额差异…（确定性引擎 + 一次归因）" />
            <span className="flex items-center gap-1 text-[11px] text-zinc-400 transition-colors group-hover:text-zinc-600">
              <ChevronDown size={12} className={`transition-transform ${detailOpen ? "rotate-180" : ""}`} />
              执行明细
            </span>
          </button>
          {verifyError && (
            <span className="rounded-full bg-amber-50 px-2.5 py-0.5 text-[11px] font-medium text-amber-600">
              {verifyError}
            </span>
          )}
        </div>

        {/* 执行明细抽屉（点击加载组件弹出，默认收起；drawer-up 滑出动画） */}
        {detailOpen && (
          <section className="drawer-up overflow-hidden rounded-xl border border-zinc-200 bg-white shadow-sm">
            <div className="flex items-center gap-2 border-b border-zinc-100 px-4 py-2.5">
              <Wrench size={13} className="text-zinc-400" />
              <h2 className="text-[13px] font-semibold text-zinc-800">执行明细</h2>
              <span className="text-[11px] text-zinc-400">混合模式：确定性核对（秒级）+ 一次 AI 归因报告</span>
            </div>
            <div className="divide-y divide-zinc-50 px-4 py-1">
              {/* 阶段 1：确定性核对 */}
              <div className="flex items-center gap-2.5 py-2.5">
                {verifyStage === 0 ? (
                  <LoadingState compact />
                ) : (
                  <CheckCircle2 size={13} className="shrink-0 text-emerald-500" />
                )}
                <div className="min-w-0">
                  <p className="text-[12.5px] font-medium text-zinc-700">确定性核对（reconcile_variables）</p>
                  <p className="text-[11px] text-zinc-400">
                    {verifyStage === 0
                      ? "两表按匹配键匹配 → 五级分级（OK/A1/A2/B/C）→ 未匹配升级为待审计项"
                      : verifyStage === 1
                        ? "完成 · 已生成差异表与待审计清单"
                        : `完成 · 耗时 ${stageTimes.reconcile}ms`}
                  </p>
                </div>
              </div>
              {/* 阶段 2：AI 报告生成 */}
              <div className="flex items-center gap-2.5 py-2.5">
                {verifyStage === 2 ? (
                  <CheckCircle2 size={13} className="shrink-0 text-emerald-500" />
                ) : (
                  <LoadingState compact />
                )}
                <div className="min-w-0">
                  <p className="text-[12.5px] font-medium text-zinc-700">AI 归因报告生成（一次 LLM 调用）</p>
                  <p className="text-[11px] text-zinc-400">
                    {verifyStage === 0
                      ? "等待核对完成后由 AI 撰写核对报告（总览/差异明细/原因分类/修改方案）"
                      : verifyStage === 1
                        ? "AI 正在分析差异并撰写核对报告…（约 20-50 秒）"
                        : `完成 · 耗时 ${stageTimes.report}ms`}
                  </p>
                </div>
              </div>
            </div>
          </section>
        )}
      </div>
    </div>
  );

  // ---------- 步骤 5 校验结果（报告 + 多轮审计清单） ----------
  const PAGE_SIZE = 50;
  const filteredAudit = auditFilter === "ALL"
    ? auditItems
    : auditItems.filter((a) => a.side === auditFilter);
  const auditPageCount = Math.max(1, Math.ceil(filteredAudit.length / PAGE_SIZE));
  const auditPageItems = filteredAudit.slice((auditPage - 1) * PAGE_SIZE, auditPage * PAGE_SIZE);
  const decidedCount = Object.keys(auditDecisions).length;

  const verifyResultPanel = (
    <div className="min-h-0 flex-1 overflow-y-auto px-6 pt-6 pb-4">
      <div className="mx-auto max-w-4xl space-y-4">
        {finalStatus !== "completed" && (
          <span className="rounded-full bg-amber-50 px-2.5 py-0.5 text-[11px] font-medium text-amber-600">
            {finalStatus === "failed" ? "运行失败" : finalStatus === "stopped" ? "已停止" : finalStatus}
          </span>
        )}
        {verifyError && (
          <span className="rounded-full bg-red-50 px-2.5 py-0.5 text-[11px] font-medium text-red-600">{verifyError}</span>
        )}

        {/* 历史运行（P3 补全：localStorage 记录 + 回看报告/差异 + 一键重跑） */}
        <section className="overflow-hidden rounded-xl border border-zinc-200 bg-white">
          <button
            onClick={() => { setHistoryOpen((o) => !o); if (activeHistory) setActiveHistory(null); }}
            className="flex w-full items-center gap-2 px-4 py-2.5 text-left transition-colors hover:bg-zinc-50"
          >
            <History size={13} className="shrink-0 text-zinc-400" />
            <span className="text-[13px] font-semibold text-zinc-800">历史运行</span>
            <span className="rounded-full bg-zinc-100 px-1.5 py-px text-[10.5px] font-medium text-zinc-500">
              {history.length} 次
            </span>
            <span className="ml-auto text-[11px] text-zinc-400">
              {historyOpen ? "收起" : "点击查看 / 一键重跑"}
            </span>
            <ChevronDown size={12} className={`shrink-0 text-zinc-400 transition-transform ${historyOpen ? "rotate-180" : ""}`} />
          </button>

          {historyOpen && (
            <div className="border-t border-zinc-100">
              {activeHistory ? (
                /* 历史详情：参数摘要 + 摘要卡 + 差异表（只读）+ 当时报告 + 一键重跑 */
                <div className="p-4">
                  <div className="mb-2 flex flex-wrap items-center gap-2">
                    <button
                      onClick={() => setActiveHistory(null)}
                      className="flex items-center gap-1 rounded-md border border-zinc-200 px-2 py-1 text-[11px] text-zinc-600 transition-colors hover:bg-zinc-100"
                    >
                      <ChevronRight size={11} className="rotate-180" /> 返回列表
                    </button>
                    <span className="text-[11px] text-zinc-400">{fmtTime(activeHistory.time)}</span>
                    {activeHistory.auditCount > 0 && (
                      <span className="rounded-full bg-amber-50 px-1.5 py-px text-[10px] font-medium text-amber-600">
                        待审计 {activeHistory.auditCount} 条
                      </span>
                    )}
                    <button
                      onClick={() => handleRerun(activeHistory)}
                      className="ml-auto flex items-center gap-1 rounded-md bg-zinc-900 px-2.5 py-1 text-[11.5px] font-medium text-white transition-colors hover:bg-zinc-700"
                    >
                      <RotateCw size={11} /> 以此次配置重新核对
                    </button>
                  </div>

                  {/* 参数摘要 */}
                  <div className="mb-2 rounded-lg bg-zinc-50 px-3 py-2 text-[11.5px] leading-relaxed text-zinc-600">
                    {paramSummary(activeHistory.params)}
                  </div>

                  {/* 摘要卡（只读） */}
                  {activeHistory.summary && (
                    <div className="mb-2 flex flex-wrap gap-1.5">
                      {[
                        { key: "OK", label: `OK ${activeHistory.summary.ok}`, cls: "bg-emerald-50 text-emerald-600" },
                        { key: "A1", label: `A1 漏填 ${activeHistory.summary.a1}`, cls: "bg-amber-50 text-amber-600" },
                        { key: "A2", label: `A2 误差 ${activeHistory.summary.a2}`, cls: "bg-amber-50 text-amber-600" },
                        { key: "B", label: `B 待确认 ${activeHistory.summary.b}`, cls: "bg-blue-50 text-blue-600" },
                        { key: "C", label: `C 无法匹配 ${activeHistory.summary.c}`, cls: "bg-red-50 text-red-600" },
                      ].map((s) => (
                        <span key={s.key} className={`rounded-full px-2.5 py-0.5 text-[11px] font-medium ${s.cls}`}>
                          {s.label}
                        </span>
                      ))}
                    </div>
                  )}

                  {/* 差异明细（只读，最多显示前 100 条） */}
                  {activeHistory.diffs.length > 0 && (
                    <div className="mb-2 overflow-hidden rounded-lg border border-zinc-200">
                      <div className="border-b border-zinc-100 bg-zinc-50 px-3 py-1.5 text-[11px] font-medium text-zinc-600">
                        差异明细（共 {activeHistory.diffs.length} 条，仅显示前 100 条）
                      </div>
                      <div className="max-h-64 overflow-auto">
                        <table className="w-full border-collapse text-[11px]">
                          <thead>
                            <tr className="sticky top-0 border-b border-zinc-100 bg-white text-left text-[10.5px] text-zinc-400">
                              <th className="px-2 py-1 font-medium">级别</th>
                              <th className="px-2 py-1 font-medium">合同编号</th>
                              <th className="px-2 py-1 font-medium">人员</th>
                              <th className="px-2 py-1 text-right font-medium">依据金额</th>
                              <th className="px-2 py-1 text-right font-medium">目标金额</th>
                              <th className="px-2 py-1 text-right font-medium">差异</th>
                            </tr>
                          </thead>
                          <tbody>
                            {activeHistory.diffs.slice(0, 100).map((d, i) => {
                              const meta = LEVEL_META[d.level] || LEVEL_META.C;
                              return (
                                <tr key={i} className="border-b border-zinc-50">
                                  <td className="px-2 py-1">
                                    <span className={`rounded-full px-1.5 py-px text-[9.5px] font-medium ${meta.bg} ${meta.color}`}>
                                      {meta.label}
                                    </span>
                                  </td>
                                  <td className="max-w-[100px] truncate px-2 py-1 text-zinc-700" title={d.contract}>{d.contract || "—"}</td>
                                  <td className="max-w-[70px] truncate px-2 py-1 text-zinc-700" title={d.person}>{d.person || "—"}</td>
                                  <td className="px-2 py-1 text-right font-mono text-zinc-700">{fmtAmount(d.base_amount)}</td>
                                  <td className="px-2 py-1 text-right font-mono text-zinc-700">{fmtAmount(d.target_amount)}</td>
                                  <td className={`px-2 py-1 text-right font-mono ${Number(d.diff) > 0 ? "text-red-600" : "text-zinc-700"}`}>
                                    {fmtAmount(d.diff)}
                                  </td>
                                </tr>
                              );
                            })}
                          </tbody>
                        </table>
                      </div>
                    </div>
                  )}

                  {/* 当时核对报告 */}
                  {activeHistory.report && (
                    <details className="rounded-lg border border-zinc-200">
                      <summary className="cursor-pointer select-none px-3 py-1.5 text-[11.5px] font-medium text-zinc-600 transition-colors hover:bg-zinc-50">
                        查看当时核对报告全文
                      </summary>
                      <div className="border-t border-zinc-100 px-3 py-2">
                        <div className={PROSE_CLASS}>
                          <Markdown remarkPlugins={[remarkGfm]}>{activeHistory.report}</Markdown>
                        </div>
                      </div>
                    </details>
                  )}
                </div>
              ) : history.length === 0 ? (
                <p className="px-4 py-6 text-center text-[12px] text-zinc-400">
                  暂无历史运行记录。完成一次校验后自动保存（最多保留 {HISTORY_MAX} 次）。
                </p>
              ) : (
                /* 历史列表：时间 + 文件对 + 摘要徽章 + 查看/重跑 */
                <ul className="max-h-80 divide-y divide-zinc-100 overflow-y-auto">
                  {history.map((r) => (
                    <li key={r.id} className="flex items-center gap-2 px-4 py-2 transition-colors hover:bg-zinc-50">
                      <span className="shrink-0 text-[11px] text-zinc-400">{fmtTime(r.time)}</span>
                      <span className="max-w-[120px] truncate text-[12px] text-zinc-700" title={r.params.baseFile}>{r.params.baseFile}</span>
                      <span className="shrink-0 text-[10px] text-zinc-300">vs</span>
                      <span className="min-w-0 flex-1 truncate text-[12px] text-zinc-700" title={r.params.detailFile}>{r.params.detailFile}</span>
                      {r.summary && (
                        <span className="hidden shrink-0 text-[10.5px] text-zinc-400 sm:inline">
                          A1 {r.summary.a1} · A2 {r.summary.a2} · B {r.summary.b} · C {r.summary.c}
                        </span>
                      )}
                      <button
                        onClick={() => setActiveHistory(r)}
                        className="shrink-0 rounded-md border border-zinc-200 px-2 py-0.5 text-[11px] text-zinc-600 transition-colors hover:bg-zinc-100"
                      >
                        查看
                      </button>
                      <button
                        onClick={() => handleRerun(r)}
                        title="以此次配置重新核对"
                        className="shrink-0 rounded-md border border-zinc-200 px-2 py-0.5 text-[11px] text-zinc-600 transition-colors hover:bg-zinc-100"
                      >
                        <RotateCw size={11} />
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}
        </section>

        {verifyReport ? (
          <section className="rounded-xl border border-zinc-200 bg-white p-5">
            <h2 className="text-[14px] font-semibold text-zinc-800">核对报告</h2>
            <div className={PROSE_CLASS}>
              <Markdown remarkPlugins={[remarkGfm]}>{verifyReport}</Markdown>
            </div>
          </section>
        ) : (
          <section className="rounded-xl border border-zinc-200 bg-white p-5 text-[13px] text-zinc-400">
            （无报告内容）
          </section>
        )}

        {/* 待审计清单（多轮审计循环：未匹配记录逐条决策 → 下一轮核对） */}
        {!auditDone && auditItems.length > 0 && (
          <section className="overflow-hidden rounded-xl border border-zinc-200 bg-white">
            <div className="border-b border-zinc-100 px-4 py-2.5">
              <div className="flex flex-wrap items-center gap-2">
                <h2 className="text-[13px] font-semibold text-zinc-800">
                  待审计清单
                  <span className="ml-1.5 rounded-full bg-amber-50 px-1.5 py-px text-[10.5px] font-medium text-amber-600">
                    {auditItems.length} 条
                  </span>
                </h2>
                <span className="text-[11px] text-zinc-400">
                  未匹配记录逐条决策（补录/忽略/确认对应关系），提交后进入下一轮核对
                </span>
                {auditBusy && (
                  <span className="ml-auto flex items-center gap-1 text-[11px] text-zinc-500">
                    <LoadingState compact /> 下一轮核对中…
                  </span>
                )}
              </div>
              {/* 分组 tab */}
              <div className="mt-2 flex flex-wrap items-center gap-1.5">
                {[
                  { key: "ALL", label: `全部 ${auditItems.length}` },
                  { key: "base", label: `总表独有 ${auditItems.filter((a) => a.side === "base").length}` },
                  { key: "detail", label: `分表独有 ${auditItems.filter((a) => a.side === "detail").length}` },
                  { key: "ambiguous", label: `一对多模糊 ${auditItems.filter((a) => a.side === "ambiguous").length}` },
                ].map((t) => (
                  <button
                    key={t.key}
                    onClick={() => { setAuditFilter(t.key); setAuditPage(1); }}
                    className={`rounded-full px-2.5 py-0.5 text-[11px] font-medium transition-colors ${
                      auditFilter === t.key
                        ? "bg-zinc-900 text-white"
                        : "bg-zinc-100 text-zinc-600 hover:bg-zinc-200"
                    }`}
                  >
                    {t.label}
                  </button>
                ))}
                {/* 批量决策（当前分组） */}
                {auditFilter !== "ALL" && (
                  <span className="ml-auto flex items-center gap-1.5">
                    <span className="text-[11px] text-zinc-400">批量：</span>
                    {AUDIT_DECISION_OPTIONS[auditFilter]?.filter((o) => o !== "挂起").map((o) => (
                      <button
                        key={o}
                        onClick={() => setAuditBatch(auditFilter, o)}
                        className="rounded-md border border-zinc-200 px-2 py-0.5 text-[11px] text-zinc-600 transition-colors hover:bg-zinc-100"
                      >
                        {o}
                      </button>
                    ))}
                    <button
                      onClick={() => setAuditBatch(auditFilter, "挂起")}
                      className="rounded-md border border-zinc-200 px-2 py-0.5 text-[11px] text-zinc-400 transition-colors hover:bg-zinc-100"
                    >
                      清空本组
                    </button>
                  </span>
                )}
              </div>
            </div>

            {/* 审计项表格 */}
            {auditPageItems.length === 0 ? (
              <p className="px-4 py-6 text-center text-[13px] text-zinc-400">该分组无待审计项</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full border-collapse text-[12.5px]">
                  <thead>
                    <tr className="border-b border-zinc-100 bg-zinc-50 text-left text-[11.5px] text-zinc-500">
                      <th className="w-16 px-3 py-2">类型</th>
                      <th className="px-2 py-2">关键值（匹配键）</th>
                      <th className="px-2 py-2">原因</th>
                      <th className="w-44 px-2 py-2">我的决策</th>
                    </tr>
                  </thead>
                  <tbody>
                    {auditPageItems.map((a) => {
                      const meta = AUDIT_SIDE_META[a.side] || AUDIT_SIDE_META.base;
                      const selKey = `${a.side}:${a.key}`;
                      const value = auditDecisions[selKey] || "";
                      return (
                        <tr key={selKey} className="border-b border-zinc-50 hover:bg-zinc-50">
                          <td className="px-3 py-2">
                            <span className={`rounded-full px-1.5 py-px text-[10.5px] font-medium ${meta.bg} ${meta.color}`}>
                              {meta.label}
                            </span>
                          </td>
                          <td className="max-w-[160px] truncate px-2 py-2 font-mono text-zinc-700" title={a.key}>
                            {a.key || "—"}
                          </td>
                          <td className="max-w-[260px] px-2 py-2 text-zinc-600" title={a.reason}>
                            {a.reason}
                            {a.candidates > 0 && (
                              <span className="ml-1 text-[10.5px] text-zinc-400">（{a.candidates} 条候选）</span>
                            )}
                          </td>
                          <td className="px-2 py-2">
                            <select
                              value={value}
                              onChange={(e) => setAuditDecision(a.side, a.key, e.target.value)}
                              className={`w-full rounded-md border px-1.5 py-1 text-[12px] ${
                                value ? "border-zinc-300 bg-white text-zinc-800" : "border-zinc-200 bg-zinc-50 text-zinc-400"
                              }`}
                            >
                              <option value="">请选择…</option>
                              {AUDIT_DECISION_OPTIONS[a.side]?.map((o) => (
                                <option key={o} value={o}>{o}</option>
                              ))}
                            </select>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}

            {/* 分页 */}
            {auditPageCount > 1 && (
              <div className="flex items-center justify-between border-t border-zinc-100 px-4 py-2 text-[11px] text-zinc-400">
                <span>第 {auditPage}/{auditPageCount} 页 · 每页 {PAGE_SIZE} 条</span>
                <div className="flex items-center gap-1">
                  <button
                    disabled={auditPage <= 1}
                    onClick={() => setAuditPage((p) => Math.max(1, p - 1))}
                    className="rounded-md border border-zinc-200 px-2 py-0.5 transition-colors hover:bg-zinc-100 disabled:opacity-40"
                  >
                    上一页
                  </button>
                  <button
                    disabled={auditPage >= auditPageCount}
                    onClick={() => setAuditPage((p) => Math.min(auditPageCount, p + 1))}
                    className="rounded-md border border-zinc-200 px-2 py-0.5 transition-colors hover:bg-zinc-100 disabled:opacity-40"
                  >
                    下一页
                  </button>
                </div>
              </div>
            )}

            {/* 提交决策 */}
            <div className="flex items-center justify-between border-t border-zinc-100 bg-zinc-50/60 px-4 py-2.5">
              <span className="text-[12px] text-zinc-500">
                已决策 <b className="text-zinc-800">{decidedCount}</b> 条（挂起不计入）
              </span>
              <button
                onClick={() => void handleAuditSubmit()}
                disabled={decidedCount === 0 || auditBusy}
                className="flex items-center gap-1.5 rounded-lg bg-zinc-900 px-3.5 py-1.5 text-[12.5px] font-medium text-white transition-colors hover:bg-zinc-700 disabled:cursor-not-allowed disabled:bg-zinc-300"
              >
                {auditBusy ? <LoadingState compact /> : <Play size={12} />}
                提交决策（{decidedCount} 条）→ 下一轮核对
              </button>
            </div>
          </section>
        )}

        {/* 审计完成（无剩余待审计项） */}
        {auditDone && (
          <section className="flex items-center gap-2 rounded-xl border border-emerald-200 bg-emerald-50/60 px-4 py-3">
            <CheckCircle2 size={15} className="shrink-0 text-emerald-600" />
            <span className="text-[13px] text-emerald-700">
              未匹配记录已全部处理完毕，可以进入确认修改。
            </span>
          </section>
        )}

        <div className="flex justify-end">
          <button
            onClick={handleToConfirm}
            className="flex items-center gap-1.5 rounded-lg bg-zinc-900 px-4 py-2 text-[13px] font-medium text-white transition-colors hover:bg-zinc-700"
          >
            进入确认修改 <ChevronRight size={14} />
          </button>
        </div>
      </div>
    </div>
  );

  // ---------- 步骤 7 确认修改（结构化差异表） ----------
  const diffs = reconData?.diffs || [];
  const filteredDiffs = diffFilter === "ALL" ? diffs : diffs.filter((d) => d.level === diffFilter);
  const selectableCount = diffs.filter((d) => LEVEL_META[d.level]?.selectable).length;
  const checkedCount = checkedIdx.size;
  const summary = reconData?.summary;
  // 差异表分页（勾选集合按全局索引，不受分页影响）
  const diffPageCount = Math.max(1, Math.ceil(filteredDiffs.length / DIFF_PAGE_SIZE));
  const safeDiffPage = Math.min(diffPage, diffPageCount);
  const pageDiffs = filteredDiffs.slice((safeDiffPage - 1) * DIFF_PAGE_SIZE, safeDiffPage * DIFF_PAGE_SIZE);

  const confirmPanel = (
    <div className="min-h-0 flex-1 overflow-y-auto px-6 pt-6 pb-4">
      <div className="mx-auto max-w-5xl space-y-4">
        {writebackBusy ? (
          <div className="mt-10 flex flex-col items-center gap-3">
            <LoadingState label="正在执行确定性写回：勾选差异写入临时库 → 精确回写 Excel…" />
            <details className="w-fit">
              <summary className="cursor-pointer select-none text-[12px] text-zinc-400 transition-colors hover:text-zinc-600">
                写回说明：A1/A2 自动填充（B/C 跳过需人工）· 不依赖 LLM · 秒级完成
              </summary>
            </details>
          </div>
        ) : (
          <>
            {/* 总览摘要卡（点击过滤） */}
            {summary && (
              <section className="rounded-xl border border-zinc-200 bg-white p-4">
                <h2 className="mb-2 text-[13px] font-semibold text-zinc-800">总览（点击筛选差异）</h2>
                <div className="flex flex-wrap gap-2">
                  {[
                    { key: "ALL", label: `全部 ${diffs.length}`, color: "text-zinc-800", bg: "bg-zinc-100" },
                    { key: "OK", label: `OK ${summary.ok}`, color: "text-emerald-600", bg: "bg-emerald-50" },
                    { key: "A1", label: `A1 漏填 ${summary.a1}`, color: "text-amber-600", bg: "bg-amber-50" },
                    { key: "A2", label: `A2 误差 ${summary.a2}`, color: "text-amber-600", bg: "bg-amber-50" },
                    { key: "B", label: `B 待确认 ${summary.b}`, color: "text-blue-600", bg: "bg-blue-50" },
                    { key: "C", label: `C 无法匹配 ${summary.c}`, color: "text-red-600", bg: "bg-red-50" },
                  ].map((f) => (
                    <button
                      key={f.key}
                      onClick={() => { setDiffFilter(f.key); setDiffPage(1); }}
                      className={`rounded-full px-3 py-1 text-[12px] font-medium transition-colors ${f.bg} ${f.color} ${
                        diffFilter === f.key ? "ring-2 ring-zinc-400" : "hover:opacity-80"
                      }`}
                    >
                      {f.label}
                    </button>
                  ))}
                </div>
              </section>
            )}

            {/* 差异明细表（可勾选） */}
            <section className="overflow-hidden rounded-xl border border-zinc-200 bg-white">
              <div className="flex items-center gap-2 border-b border-zinc-100 px-4 py-2.5">
                <h2 className="text-[13px] font-semibold text-zinc-800">差异明细（已选 {checkedCount}/{selectableCount}）</h2>
                {filteredDiffs.length > DIFF_PAGE_SIZE && (
                  <span className="rounded-full bg-amber-50 px-2 py-px text-[10.5px] text-amber-600">
                    共 {filteredDiffs.length} 条 · 第 {safeDiffPage}/{diffPageCount} 页
                  </span>
                )}
                <button
                  onClick={toggleAll}
                  className="ml-auto rounded-md border border-zinc-200 px-2 py-0.5 text-[11px] text-zinc-600 transition-colors hover:bg-zinc-100"
                >
                  全选/取消
                </button>
              </div>
              {filteredDiffs.length === 0 ? (
                <p className="px-4 py-6 text-center text-[13px] text-zinc-400">
                  {diffs.length === 0 ? "（未解析到结构化差异数据，可查看校验报告）" : "该级别无差异"}
                </p>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full border-collapse text-[12.5px]">
                    <thead>
                      <tr className="border-b border-zinc-100 bg-zinc-50 text-left text-[11.5px] text-zinc-500">
                        <th className="w-8 px-3 py-2">
                          <input
                            type="checkbox"
                            checked={filteredDiffs.length > 0 && filteredDiffs.every((d) => {
                              const gi = diffs.indexOf(d);
                              return !LEVEL_META[d.level]?.selectable || checkedIdx.has(gi);
                            })}
                            onChange={toggleAll}
                            className="accent-zinc-900"
                          />
                        </th>
                        <th className="px-2 py-2">级别</th>
                        <th className="px-2 py-2">合同编号</th>
                        <th className="px-2 py-2">人员</th>
                        <th className="px-2 py-2">客户</th>
                        <th className="px-2 py-2 text-right">依据金额</th>
                        <th className="px-2 py-2 text-right">目标金额</th>
                        <th className="px-2 py-2 text-right">差异</th>
                        <th className="px-2 py-2">AI 归因</th>
                        <th className="px-2 py-2">AI 建议</th>
                      </tr>
                    </thead>
                    <tbody>
                      {pageDiffs.map((d) => {
                        const gi = diffs.indexOf(d);
                        const meta = LEVEL_META[d.level] || LEVEL_META.C;
                        const selectable = meta.selectable;
                        const checked = checkedIdx.has(gi);
                        return (
                          <tr
                            key={gi}
                            className={`border-b border-zinc-50 ${selectable ? "cursor-pointer hover:bg-zinc-50" : "opacity-60"}`}
                            onClick={() => selectable && toggleDiff(gi)}
                          >
                            <td className="px-3 py-2">
                              {selectable ? (
                                <input
                                  type="checkbox"
                                  checked={checked}
                                  onChange={() => toggleDiff(gi)}
                                  onClick={(e) => e.stopPropagation()}
                                  className="accent-zinc-900"
                                />
                              ) : (
                                <span className="text-zinc-300">—</span>
                              )}
                            </td>
                            <td className="px-2 py-2">
                              <span className={`rounded-full px-1.5 py-px text-[10.5px] font-medium ${meta.bg} ${meta.color}`}>
                                {meta.label}
                              </span>
                            </td>
                            <td className="max-w-[110px] truncate px-2 py-2 text-zinc-700" title={d.contract}>{d.contract || "—"}</td>
                            <td className="max-w-[80px] truncate px-2 py-2 text-zinc-700" title={d.person}>{d.person || "—"}</td>
                            <td className="max-w-[90px] truncate px-2 py-2 text-zinc-700" title={d.client}>{d.client || "—"}</td>
                            <td className="px-2 py-2 text-right font-mono text-zinc-700">{fmtAmount(d.base_amount)}</td>
                            <td className="px-2 py-2 text-right font-mono text-zinc-700">{fmtAmount(d.target_amount)}</td>
                            <td className={`px-2 py-2 text-right font-mono ${Number(d.diff) > 0 ? "text-red-600" : "text-zinc-700"}`}>
                              {fmtAmount(d.diff)}
                            </td>
                            <td className="max-w-[100px] px-2 py-2 text-zinc-600" title={d.reason}>{d.reason || "—"}</td>
                            <td className="max-w-[140px] px-2 py-2 text-zinc-500" title={d.suggestion}>{d.suggestion || "—"}</td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}

              {/* 差异表分页导航（大数据分页；勾选按全局索引，跨页保持） */}
              {diffPageCount > 1 && (
                <div className="flex items-center justify-between border-t border-zinc-100 px-4 py-2 text-[11px] text-zinc-400">
                  <span>共 {filteredDiffs.length} 条 · 每页 {DIFF_PAGE_SIZE} 条</span>
                  <div className="flex items-center gap-1">
                    <button
                      disabled={safeDiffPage <= 1}
                      onClick={() => setDiffPage((p) => Math.max(1, p - 1))}
                      className="rounded-md border border-zinc-200 px-2 py-0.5 transition-colors hover:bg-zinc-100 disabled:opacity-40"
                    >
                      上一页
                    </button>
                    <span className="px-1">第 {safeDiffPage}/{diffPageCount} 页</span>
                    <button
                      disabled={safeDiffPage >= diffPageCount}
                      onClick={() => setDiffPage((p) => Math.min(diffPageCount, p + 1))}
                      className="rounded-md border border-zinc-200 px-2 py-0.5 transition-colors hover:bg-zinc-100 disabled:opacity-40"
                    >
                      下一页
                    </button>
                  </div>
                </div>
              )}
            </section>

            {/* 校验报告（折叠） */}
            {verifyReport && (
              <details className="rounded-xl border border-zinc-200 bg-white">
                <summary className="cursor-pointer select-none px-4 py-2.5 text-[13px] font-semibold text-zinc-800 hover:bg-zinc-50">
                  查看校验报告全文
                </summary>
                <div className="border-t border-zinc-100 px-4 py-3">
                  <div className={PROSE_CLASS}>
                    <Markdown remarkPlugins={[remarkGfm]}>{verifyReport}</Markdown>
                  </div>
                </div>
              </details>
            )}

            {/* 写回报告 */}
            {writebackDone && (
              <section className="rounded-xl border border-emerald-200 bg-white p-5">
                <h2 className="text-[14px] font-semibold text-zinc-800">修改报告</h2>
                <div className={PROSE_CLASS}>
                  <Markdown remarkPlugins={[remarkGfm]}>{writebackReport || "（写回完成）"}</Markdown>
                </div>
              </section>
            )}

            {/* 输出文件（写回完成后展示：应用数据区下载/打开） */}
            {writebackDone && (
              <section className="rounded-xl border border-zinc-200 bg-white p-5">
                <div className="flex items-center gap-2">
                  <FolderOpenIcon />
                  <h2 className="text-[14px] font-semibold text-zinc-800">输出文件</h2>
                  <span className="text-[11px] text-zinc-400">修改已写入 Excel（可打开 / 下载导出）</span>
                </div>
                {outputs.length > 0 ? (
                  <ul className="mt-3 divide-y divide-zinc-100">
                    {outputs.map((f) => (
                      <li key={f.path} className="flex items-center gap-2 py-2">
                        <FileText size={14} className="shrink-0 text-zinc-400" />
                        <button
                          onClick={() => handleOpenOutput(f)}
                          className="min-w-0 flex-1 truncate text-left text-[13px] text-zinc-700 transition-colors hover:text-zinc-900"
                        >
                          {f.name}
                        </button>
                        <span className="shrink-0 text-[11px] text-zinc-400">
                          {f.size != null && f.size > 0 ? `${(f.size / 1024).toFixed(1)} KB` : ""}
                        </span>
                        <button
                          onClick={() => handleOpenOutput(f)}
                          className="shrink-0 rounded-md border border-zinc-200 px-2 py-0.5 text-[11px] text-zinc-600 transition-colors hover:bg-zinc-100"
                        >
                          打开
                        </button>
                        <button
                          onClick={() => handleDownloadOutput(f)}
                          className="flex shrink-0 items-center gap-1 rounded-md border border-zinc-200 px-2 py-0.5 text-[11px] text-zinc-600 transition-colors hover:bg-zinc-100"
                        >
                          <Download size={10} /> 导出
                        </button>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="mt-2 text-[12px] text-zinc-400">（暂无输出文件）</p>
                )}
              </section>
            )}

            {/* 操作区 */}
            <div className="flex items-center justify-end gap-2">
              {writebackDone && (
                <span className="mr-auto flex items-center gap-1 text-[12px] text-emerald-600">
                  <CheckCircle2 size={13} /> 修改完成
                </span>
              )}
              {!writebackDone && (
                <button
                  onClick={handleWriteback}
                  disabled={checkedCount === 0}
                  className="flex items-center gap-1.5 rounded-lg bg-zinc-900 px-4 py-2 text-[13px] font-medium text-white transition-colors hover:bg-zinc-700 disabled:cursor-not-allowed disabled:bg-zinc-300"
                >
                  <Play size={13} /> 确认修改（{checkedCount} 条）
                </button>
              )}
              {writebackDone && (
                <button
                  onClick={() => gotoStep(1)}
                  className="rounded-lg border border-zinc-200 bg-white px-3.5 py-2 text-[13px] font-medium text-zinc-600 transition-colors hover:bg-zinc-100"
                >
                  重新核对（回到步骤 1）
                </button>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );

  // ---------- 左侧竖排步骤导航（6 步流程；顶部固定区下方，右侧内容区随步骤切换） ----------
  const stepNav = (
    // 2026-08-21：回到最初简单列表版——无竖线连接，选项间留空隙（space-y-1），
    // 顶部对齐自然排列，保持简洁。
    <nav className="flex w-44 shrink-0 flex-col border-r border-zinc-200 bg-white py-3">
      {FLOW_STEPS.map((s, i) => {
        const done = maxReached > s.n || (maxReached === s.n && s.n < 5);
        const active = flowStep === s.n;
        const clickable = !busy && s.n <= maxReached;
        return (
          <div key={s.n} className={i > 0 ? "mt-1" : ""}>
            <button
              onClick={() => clickable && gotoStep(s.n)}
              disabled={!clickable}
              title={clickable ? `回到步骤 ${s.n}：${s.label}` : s.n > maxReached ? "尚未到达" : "运行中不可切换"}
              className={`flex w-full items-center gap-2.5 px-5 py-2.5 text-[12.5px] transition-colors ${
                active
                  ? "bg-zinc-50 font-semibold text-zinc-900"
                  : done
                    ? "text-zinc-600 hover:bg-zinc-50"
                    : s.n <= maxReached
                      ? "text-zinc-600 hover:bg-zinc-50"
                      : "cursor-not-allowed text-zinc-300"
              }`}
            >
              <span
                className={`flex size-5 shrink-0 items-center justify-center rounded-full text-[11px] font-semibold ${
                  active
                    ? "bg-zinc-900 text-white"
                    : done
                      ? "bg-emerald-100 text-emerald-600"
                      : "bg-zinc-200 text-zinc-500"
                }`}
              >
                {done ? "✓" : s.n}
              </span>
              {s.label}
              {active && <span className="ml-auto h-1.5 w-1.5 rounded-full bg-zinc-900" />}
            </button>
          </div>
        );
      })}
    </nav>
  );

  return (
    <div className="relative flex min-w-0 flex-1 flex-col bg-zinc-50">
      {/* 共享头部（标题 + AI 模型选择 + 应用专用 AI 卡，所有步骤统一） */}
      {appHeader}

      {/* 主区：左竖排导航 + 右内容区（2026-08-20 左右布局；导航额外占位，内容宽度保持原样） */}
      {/* min-h-0：允许主区收缩到剩余高度（否则被内容撑开导致右侧无法滚动） */}
      <div className="flex min-h-0 min-w-0 flex-1">
        {stepNav}

        {/* 右侧内容区（overflow-hidden：确保子面板各自滚动，不被撑破遮挡） */}
        <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden">
          {/* 步骤 1-4：配置向导（含合并的容差&处理策略） */}
          {flowStep <= 4 && (
            <ReconWizard
              projectId={appProject.id}
              initial={params}
              step={flowStep}
              onStepChange={gotoStep}
              onStart={handleStart}
              running={busy}
              onOpenDb={() => setDbOpen(true)}
              refreshTick={dbTick}
            />
          )}

          {/* 步骤 5：校验（执行中 + 结果 + 多轮审计循环） */}
          {flowStep === 5 && (verifyBusy ? runningPanel : verifyResultPanel)}

          {/* 步骤 6：修改（方案确认 → 执行 → 报告 + 输出文件）
              外层仅约束高度，滚动由 confirmPanel 自身承担（避免双层滚动条） */}
          {flowStep === 6 && (
            <div className="flex min-h-0 flex-1 flex-col">
              {confirmPanel}
            </div>
          )}
        </div>
      </div>

      {/* 项目数据库抽屉（2026-08-21：上传 Excel/删除/刷新；无写回，流程已固化） */}
      {(dbOpen || dbClosing) && appProject && (
        <AppDataPanel
          projectId={appProject.id}
          closing={dbClosing}
          onClose={requestCloseDb}
          onImported={() => setDbTick((t) => t + 1)}
        />
      )}

      {/* ask_user 弹窗（复用 AskUserDialog） */}
      {question && (
        <div className="pointer-events-none absolute inset-x-0 bottom-0 z-40 px-6 pb-4">
          <div className="pointer-events-auto relative mx-auto max-w-3xl">
            <AskUserDialog payload={question} onAnswer={answer} onCancel={() => answer("", true)} />
          </div>
        </div>
      )}

      {/* 运行中：右下角停止按钮 */}
      {busy && (
        <div className="absolute right-6 bottom-5 z-30">
          <button
            onClick={() => void stop()}
            className="flex items-center gap-1.5 rounded-lg border border-zinc-200 bg-white px-3 py-1.5 text-[12px] font-medium text-zinc-600 shadow-sm transition-colors hover:bg-zinc-100 hover:text-zinc-800"
          >
            <Square size={11} fill="currentColor" />
            停止
          </button>
        </div>
      )}
    </div>
  );
}

/** 文件夹图标（lucide 无 FolderOpen 导出冲突，内联） */
function FolderOpenIcon() {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" className="text-zinc-500">
      <path d="M6 14l1.5-2.9A2 2 0 019.24 10H20a2 2 0 011.94 2.5l-1.54 6a2 2 0 01-1.95 1.5H4a2 2 0 01-2-2V5a2 2 0 012-2h3.9a2 2 0 011.69.9l.81 1.2a2 2 0 001.67.9H18a2 2 0 012 2v2" />
    </svg>
  );
}

/** 机器人图标（应用专用 AI 徽标，lucide 无直接导出冲突时内联） */
function BotIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" className="shrink-0 text-zinc-500">
      <path d="M12 8V4H8" />
      <rect width="16" height="12" x="4" y="8" rx="2" />
      <path d="M2 14h2" />
      <path d="M20 14h2" />
      <path d="M15 13v2" />
      <path d="M9 13v2" />
    </svg>
  );
}

/** 工具事件行（运行态展示：名称 + 状态 + 耗时）—— 2026-08-21 写回改确定性后不再使用，保留备用 */
/*
function ToolRow({ tool }: { tool: ReconToolState }) {
  const done = tool.status === "completed";
  return (
    <div className="flex items-center gap-2 rounded-md border border-zinc-200 bg-white px-3 py-2">
      <Wrench size={13} className={done ? "text-zinc-400" : "animate-spin text-blue-600"} />
      <span className="min-w-0 flex-1 truncate text-[12.5px] text-zinc-700">{tool.title}</span>
      {done && tool.duration_ms != null && tool.duration_ms > 0 && (
        <span className="shrink-0 text-[11px] text-zinc-400">{(tool.duration_ms / 1000).toFixed(1)}s</span>
      )}
      <span
        className={`shrink-0 rounded-full px-1.5 py-px text-[10px] font-medium ${
          done ? "bg-emerald-50 text-emerald-600" : "bg-blue-50 text-blue-600"
        }`}
      >
        {done ? "完成" : "执行中"}
      </span>
    </div>
  );
}
*/
