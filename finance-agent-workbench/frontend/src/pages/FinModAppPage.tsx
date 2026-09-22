/** FinModAppPage — 财务建模与分析集成应用（P2 引导引擎，2026-08-21）。

 * 7 步向导（步骤条常驻，与应用一一致，可自由回退）：
 *   1 诉求入口 → 2 AI 引导 → 3 建模方向 → 4 变量映射
 *   → 5 图表配置 → 6 执行 → 7 报告
 *
 * P2 交付（引导引擎，对应需求文档 §四 步骤 1-3 + §八 P2）：
 *   - 步骤 1「诉求入口」：一句话目标输入 + 项目数据库抽屉（AppDataPanel 上传/
 *     表头锚定/索引查看/删除）+ 已导入文件列表；诉求与上传可同时/可只其一
 *   - 步骤 2「AI 引导」：POST /finmod/guide（诉求 + 列名索引 → LLM 建议 JSON），
 *     模式 A 渲染数据需求清单卡 / 模式 B 渲染 GuideCard 方向建议卡（勾选）/
 *     模式 C 渲染讲解卡 + 诉求输入；LLM 不可用 → 降级提示 + 手动模型库路径
 *   - 步骤 3「建模方向」：AI 推荐卡（默认勾选）+ 模型库补充入口（A-G 分类勾选）
 *     → 已选模型 chips；至少选 1 个才能下一步
 *   步骤 4+ 为 P3+ 占位（P1 图表库浏览保留在步骤 5）。
 *
 * 数据流：guide 端点（LLM 建议，仅建议不执行）→ GuideCard/ModelCard 勾选
 * → selectedModels 配置清单（P3 变量映射消费）。
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { BookOpen, ChartColumn, AlertTriangle, Sparkles, Database, ArrowRight, X, FileSpreadsheet, CheckCircle2, FolderOpen, RotateCcw, History, Wrench, Check, Layers, RefreshCw, FileText, Trash2 } from "lucide-react";
import type {
  AgentOption, DataFileRecord, FinmodGuideResult, FinmodMetaData, ModelOption, Project, Provider, SkillDetail,
} from "../lib/api";
import {
  finmodMeta, finmodGuide, finmodVarmap, finmodVarmapSuggest, finmodDerivedEval, finmodChartSuggest, finmodRun,
  finmodSaveChart, finmodExportMd, finmodAssetUrl, finmodPrepData, rawFileUrl,
  listProjects, createProject, listDataFiles, fetchSkillDetail,
  type FinmodVarmapResult, type FinmodVarmapModel,
  type FinmodChartSuggestResult, type FinmodChartManifestItem, type FinmodRunResult,
  type FinmodExportMdResult, type FinmodPrepStep, type FinmodPrepResult, type FinmodStylePrefs,
} from "../lib/api";
import ModelCard from "../components/ModelCard";
import ChartLibrary from "../components/ChartLibrary";
import GuideCard from "../components/GuideCard";
import VariableMapTable, { type DerivedFormulaLine } from "../components/VariableMapTable";
import DataPrepPanel from "../components/DataPrepPanel";
import ChartManifest from "../components/ChartManifest";
import ChartPreview from "../components/ChartPreview";
import ChartRenderer from "../components/ChartRenderer";
import DataAnalyzer from "../components/DataAnalyzer";
import AppDataPanel from "../components/AppDataPanel";
import ModelPicker from "../components/ModelPicker";
import MarkdownBlock from "../components/MarkdownBlock";
import FileEditor from "../components/FileEditor";
import LoadingState from "../components/LoadingState";
import { buildChartOption } from "../components/chart-templates";
import { renderOptionToSvg, renderOptionToPng, sanitizeFileName } from "../lib/chartSvg";
import { sampleDataToRows } from "../components/ChartPreview";
import { finmodPyChart } from "../lib/api";

/** 4 步流程步骤定义（常驻步骤条；R3 4步化，2026-08-23）：
 *  1 诉求与数据（含多文件选择）→ 2 宏观建模与映射（建模方向+变量映射）
 *  → 3 图表风格 → 4 AI 撰写报告（执行+报告合并） */
const FLOW_STEPS = [
  { n: 1, label: "诉求与数据" },
  { n: 2, label: "宏观建模与映射" },
  { n: 3, label: "图表风格" },
  { n: 4, label: "AI 撰写报告" },
];

/** 历史分析报告记录：每条对应一份落盘的报告 md。 */
interface ReportHistoryItem {
  id: string;            // 唯一标识（run_id）
  runId: string;
  rel_path: string;      // 报告 md 相对项目根（含 财务分析报告/财务分析报告N/xxx.md）
  filename: string;      // 如 财务分析报告1.md
  goal: string;          // 本次分析诉求（标题展示）
  createdAt: string;     // 生成时间（ISO）
}

/** v6.9：走 Python(mplot3d) 生成 PNG 的 3D 模板。报告落盘时用 finmodPyChart
 * 直接生成 PNG（echarts-gl 无法 SVG 矢量，且 surface/line3D 渲染为曲面不符预期）。 */
const PY3D_TEMPLATES = new Set(["waterfall3d", "bar3d", "scatter3d"]);

/** 把 AI 输出的讲解文案转成 markdown 分点排版（v6.14-2）。
 *  LLM 常把「1）xxx 2）yyy 3）zzz」挤成一行 / 用 ··、①②③ 等作分点，react-markdown 会渲染成
 *  一个长 <p>。此处识别常见分点符号，统一转成 `- ` 列表项（每条换行），保证分段分行可读。 */
export function autoListify(text: string): string {
  if (!text) return text;
  // ① 若已含 markdown 列表/换行 → 原样返回（尊重 LLM 结构）
  if (/^\s*[-*]\s+/m.test(text) || /\n\s*[-*]\s+/.test(text) || /^\s*\d+[.、]/m.test(text)) {
    return text;
  }
  // ② 识别中文序号 1）2）3） 或 （1）（2）（3） 或 ①②③ 或 1.2.3.
  const hasZhSeq = /[（(]?\d+[）)]|①|②|③|④|⑤|⑥|⑦|⑧|⑨|⑩/.test(text);
  if (hasZhSeq) {
    // 把「x）内容」拆开，前面补 `- `；句号后若不是序号也按句拆分
    // 先按 [数字）]  或 ①②③ 或 （数字） 切分
    const parts = text
      .split(/(?=[（(]?\d+[）)]|[①②③④⑤⑥⑦⑧⑨⑩]|\d+[.、])/)
      .map((s) => s.trim())
      .filter(Boolean);
    if (parts.length > 1) {
      return parts.map((p) => `- ${p}`).join("\n");
    }
  }
  // ③ 兜底：按句号/分号断行（每句一行），避免纯文本大段
  const sentences = text
    .split(/(?<=[。；！？!?])\s*/)
    .map((s) => s.trim())
    .filter(Boolean);
  if (sentences.length > 1) {
    return sentences.map((s) => `- ${s}`).join("\n");
  }
  return text;
}

/** 应用专属隐藏项目标识 + 独立工作区（主库零污染） */
const APP_PROJECT_NAME = "__app_finmod__";
const APP_WORK_DIR = "d:/Finance Recon Agent/finance-agent-workbench/data/app-workspaces/finmod";

/** 机器人图标（应用专用 AI 徽标，与应用一 data-reconcile 的内联 SVG 一致） */
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

interface Props {
  project: Project;
  models: ModelOption[];
  agents: AgentOption[];
  providers: Provider[];
  defaultModel: string;
}

/** 获取（缓存/复用）或创建应用专属隐藏项目。 */
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
    return best;
  }
  return createProject({
    name: APP_PROJECT_NAME,
    work_dir: APP_WORK_DIR,
    default_model: defaultModel || undefined,
    description: "财务建模与分析集成应用（隐藏）",
  });
}

export default function FinModAppPage({
  project: _project,
  models,
  agents: _agents,
  providers,
  defaultModel,
}: Props) {
  // 元数据（P1：模型/图表目录）
  const [meta, setMeta] = useState<FinmodMetaData | null>(null);
  const [metaError, setMetaError] = useState("");
  // 应用专用 AI（skill 职责/约束，v6.14-2）
  const [skill, setSkill] = useState<SkillDetail | null>(null);
  // 流程状态（步骤条常驻；P2 步骤 1-3 可交互）
  const [flowStep, setFlowStep] = useState(1);
  const [maxReached, setMaxReached] = useState(1);
  // 应用专属项目 + 已导入数据文件
  const [appProject, setAppProject] = useState<Project | null>(null);
  const [appError, setAppError] = useState("");
  const [files, setFiles] = useState<DataFileRecord[]>([]);
  const [dbOpen, setDbOpen] = useState(false);
  const [dbClosing, setDbClosing] = useState(false);
  const [dbTick, setDbTick] = useState(0);
  // R1：参与分析的文件列表（默认全选已上传文件，步骤 1 可在 UI 增删）
  const [selectedFiles, setSelectedFiles] = useState<DataFileRecord[]>([]);
  // R3：步骤 2 内部子阶段（direction 建模方向 / varmap 变量映射）
  const [macroPhase, setMacroPhase] = useState<"direction" | "varmap">("direction");
  // R3：步骤 4 内部子阶段（execute 执行 / report 报告生成）
  const [reportPhase, setReportPhase] = useState<"execute" | "report">("execute");
  /** R1：参与分析的文件（selectedFiles 有值用 selectedFiles，否则回退全部 files） */
  const analysisFiles: DataFileRecord[] = useMemo(() => {
    if (selectedFiles.length > 0) return selectedFiles;
    return files;
  }, [selectedFiles, files]);
  /** R1：参与分析的文件名列表（传给后端 file_names） */
  const analysisFileNames: string[] = useMemo(
    () => analysisFiles.map((f) => f.file_name),
    [analysisFiles],
  );
  /** R1：切换某文件是否参与分析（多文件建模） */
  const toggleAnalysisFile = useCallback((f: DataFileRecord) => {
    setSelectedFiles((prev) => {
      const exists = prev.some((sf) => sf.file_name === f.file_name);
      if (exists) return prev.filter((sf) => sf.file_name !== f.file_name);
      return [...prev, f];
    });
  }, []);
  // 步骤 1 诉求
  const [goal, setGoal] = useState("");
  // 步骤 2 引导结果
  const [guideResult, setGuideResult] = useState<FinmodGuideResult | null>(null);
  const [guideBusy, setGuideBusy] = useState(false);
  const [guideError, setGuideError] = useState("");
  // 步骤 3 已选模型（model_id Set）
  const [selectedModels, setSelectedModels] = useState<Set<string>>(new Set());
  const [expandedModel, setExpandedModel] = useState<string | null>(null);
  // 步骤 4 变量映射（P3）
  const [varmap, setVarmap] = useState<FinmodVarmapResult | null>(null);
  const [varmapBusy, setVarmapBusy] = useState(false);
  const [varmapError, setVarmapError] = useState("");
  /** 当前映射覆盖：{model_id: {var_name: col}}（用户手动选择/预填） */
  const [mappingOverrides, setMappingOverrides] = useState<Record<string, Record<string, string>>>({});
  /** 期间列 */
  const [periodCol, setPeriodCol] = useState("");
  /** 派生变量公式行 */
  const [derivedFormulas, setDerivedFormulas] = useState<DerivedFormulaLine[]>([]);
  /** v3.5：允许缺失分析（truly_missing 存在时勾选后可放行，报告给出说明） */
  const [allowMissingAnalysis, setAllowMissingAnalysis] = useState(false);
  const [derivedResults, setDerivedResults] = useState<Record<string, { type: string; sample: unknown[]; rows: number }>>({});
  const [derivedErrors, setDerivedErrors] = useState<{ line: number; name: string; kind: string; message: string }[]>([]);
  const [derivedBusy, setDerivedBusy] = useState(false);
  // v2.0 V2：AI 变量匹配（LLM 推荐 + 置信度 + 统计量绑定）
  const [aiUsed, setAiUsed] = useState(false);           // varmap-suggest 是否用过 LLM
  /** AI 推荐映射（key=model_id:var_name） */
  const [aiMappings, setAiMappings] = useState<Record<string, { confidence: number; reason: string; candidates: string[] }>>({});
  /** AI 统计量绑定（key=model_id:var_name） */
  const [aiStatBindings, setAiStatBindings] = useState<Record<string, { stat: string; based_on: string }>>({});
  /** 统计量用户绑定（改函数/来源列） */
  const [statBindings, setStatBindings] = useState<{ var_name: string; stat: string; based_on: string }[]>([]);
  // V3：数据预处理（数据准备区）
  const [prepSteps, setPrepSteps] = useState<FinmodPrepStep[]>([]);
  const [prepResult, setPrepResult] = useState<FinmodPrepResult | null>(null);
  const [prepBusy, setPrepBusy] = useState(false);
  // 步骤 5 图表配置（P4）
  const [chartSuggest, setChartSuggest] = useState<FinmodChartSuggestResult | null>(null);
  const [chartBusy, setChartBusy] = useState(false);
  const [chartLevel, setChartLevel] = useState("L2");
  const [chartError, setChartError] = useState("");
  // R4：图表风格偏好（用户表达，非硬性勾选；传给 charts-suggest style_prefs）
  const [stylePrefs, setStylePrefs] = useState<FinmodStylePrefs>({ level: "L2", colors: "auto", categories: [] });
  /** 图表偏好类别选项（与后端 CHART_CATEGORY_LABELS 对齐） */
  const CHART_CATEGORY_OPTIONS = [
    { id: "trend", label: "趋势" },
    { id: "compare", label: "对比" },
    { id: "share", label: "占比" },
    { id: "sensitivity", label: "敏感性" },
    { id: "distribution", label: "分布" },
    { id: "relation", label: "关系" },
  ];
  /** R4：切换偏好类别（多选） → 重新推荐 */
  const togglePrefCategory = useCallback((cat: string) => {
    setStylePrefs((prev) => {
      const cats = prev.categories || [];
      const next = cats.includes(cat) ? cats.filter((c) => c !== cat) : [...cats, cat];
      return { ...prev, categories: next };
    });
  }, []);
  /** AI 推荐卡展开（v6.8：折叠=名称+理由+加入；展开=模板预览+示例数据） */
  const [suggestOpen, setSuggestOpen] = useState<string | null>(null);
  /** 图表确认清单（chart_manifest 收敛，P5 run 消费） */
  const [chartManifest, setChartManifest] = useState<FinmodChartManifestItem[]>([]);
  // 步骤 6 执行（P5）
  const [runBusy, setRunBusy] = useState(false);
  const [runError, setRunError] = useState("");
  const [runResult, setRunResult] = useState<FinmodRunResult | null>(null);
  const [analyzerOpen, setAnalyzerOpen] = useState(false);
  // 步骤 7 报告交付（P6）
  const [reportBusy, setReportBusy] = useState(false);
  const [reportError, setReportError] = useState("");
  const [reportResult, setReportResult] = useState<FinmodExportMdResult | null>(null);
  /** 已落盘图表清单 {filename, rel_path, format} */
  const [savedCharts, setSavedCharts] = useState<{ filename: string; rel_path: string; format: string }[]>([]);
  /** 历史分析报告（localStorage app_finmod_report_history）：每条=一份落盘的报告 md。
   *  点击在新标签页预览（复用 PreviewPage），支持删除/刷新。 */
  const [reportHistory, setReportHistory] = useState<ReportHistoryItem[]>([]);
  // 模型选择器（复用 ModelPicker；P2 引导用同一模型）
  const defaultModelId =
    models.find((m) => m.id === defaultModel)?.id ||
    models.find((m) => m.is_default === 1)?.id ||
    models[0]?.id ||
    "";
  const [model, setModel] = useState(defaultModelId);
  // ModelPicker onChange 回调（接收 ModelOption → 存 id）
  const handleSelectModel = useCallback((m: ModelOption) => {
    setModel(m.id);
  }, []);
  const loadedRef = useRef(false);

  // 初始化：确保应用专属项目 + 拉取元数据
  useEffect(() => {
    if (loadedRef.current) return;
    loadedRef.current = true;
    ensureAppProject(model || defaultModel)
      .then((p) => setAppProject(p))
      .catch((e) => setAppError(`应用数据区初始化失败: ${(e as Error).message}`));
    finmodMeta()
      .then((d) => setMeta(d))
      .catch((e) => setMetaError((e as Error).message || "元数据加载失败"));
    // 应用专用 AI：拉取 financial-modeling skill 职责/约束（v6.14-2，与应用一致）
    fetchSkillDetail("financial-modeling")
      .then((s) => setSkill(s))
      .catch(() => { /* 拉取失败不阻塞应用 */ });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // 数据文件列表（dbTick 变化时刷新：导入完成/删除后）
  const loadFiles = useCallback(() => {
    if (!appProject) return;
    listDataFiles(appProject.id)
      .then((r) => {
        const fs = r.files || [];
        setFiles(fs);
        // R1：默认同步全选已上传文件到 selectedFiles（保持引用稳定，避免重复选中）
        setSelectedFiles((prev) => {
          const prevNames = new Set(prev.map((f) => f.file_name));
          const kept = prev.filter((f) => fs.some((nf) => nf.file_name === f.file_name));
          const added = fs.filter((f) => !prevNames.has(f.file_name));
          return [...kept, ...added];
        });
      })
      .catch(() => {});
  }, [appProject]);
  useEffect(() => { loadFiles(); }, [loadFiles, dbTick]);

  /** 请求关闭数据库抽屉（滑出动画后卸载） */
  const requestCloseDb = useCallback(() => {
    if (!dbOpen || dbClosing) return;
    setDbClosing(true);
    window.setTimeout(() => { setDbOpen(false); setDbClosing(false); }, 260);
  }, [dbOpen, dbClosing]);

  // 进入步骤 2（建模方向）且尚无引导结果 → 自动触发引导（导航直达场景，v1.9 合并后）
  useEffect(() => {
    if (flowStep === 2 && !guideBusy && !guideResult && !guideError) {
      void runGuide(goal);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [flowStep]);

  /** 运行 AI 引导（P2：诉求 + 列名索引 → 建议 JSON） */
  const runGuide = useCallback(async (g: string) => {
    if (!appProject) return;
    setGuideBusy(true);
    setGuideError("");
    try {
      const r = await finmodGuide(appProject.id, model, g, analysisFileNames);
      setGuideResult(r);
      // 模式 B：AI 推荐卡默认全选（用户可取消，R2 双向收敛）
      // v2.7 数据完备性：变量不足的模型不默认勾选（步骤 2 已校验，
      // 数据齐的才进变量映射——变量映射是辅助确认而非决定性环节）
      if (r.success && r.mode === "B" && r.directions.length) {
        // v3.2 统一口径：ready（无真正缺失）即可默认勾选；可派生也算就绪
        const ready = r.directions
          .filter((d) => !d.var_coverage || d.var_coverage.ready !== false)
          .map((d) => d.model_id);
        // 至少选 1 个（全缺数据时让用户看到推荐但手动决策）
        setSelectedModels(new Set(ready.length ? ready : r.directions.map((d) => d.model_id)));
      }
    } catch (e) {
      setGuideError((e as Error).message || "AI 引导失败");
      setGuideResult(null);
    } finally {
      setGuideBusy(false);
    }
  }, [appProject, model, analysisFileNames]);

  /** 步骤 1 下一步：有诉求或有数据才能进入引导 */
  const handleNextToGuide = () => {
    if (!goal.trim() && files.length === 0) return;
    setMaxReached((m) => Math.max(m, 2));
    setFlowStep(2);
    void runGuide(goal);
  };

  /** 模式 A/C 重新引导（补传数据/表达诉求后） */
  const handleRerunGuide = (g?: string) => {
    const next = g ?? goal;
    setGoal(next);
    setMaxReached((m) => Math.max(m, 2));
    setFlowStep(2);
    void runGuide(next);
  };

  /** R2：汇总「已选模型」真正缺失的数据需求（供模式 B 数据需求卡 + 重新引导）。
   *  从 guideResult.directions 中筛选 selectedModels 的 var_coverage.truly_missing_details。
   *  returns {models: [{code,name,missing:[{var_name,meaning,unit}],derivable:[...]}], total} */
  const selectedMissingNeeds = useMemo(() => {
    if (!guideResult || guideResult.mode !== "B" || selectedModels.size === 0) {
      return { models: [] as { code: string; name: string; missing: { var_name: string; meaning: string; unit: string }[]; derivable: string[] }[], total: 0 };
    }
    const models = (guideResult.directions || [])
      .filter((d) => selectedModels.has(d.model_id) && d.var_coverage)
      .map((d) => {
        const vc = d.var_coverage!;
        const missing = (vc.truly_missing_details || vc.missing_names?.map((n) => ({ var_name: n, meaning: "", unit: "" })) || [])
          .map((x) => ({ var_name: x.var_name, meaning: x.meaning || "", unit: x.unit || "" }));
        return {
          code: d.code, name: d.name,
          missing,
          derivable: vc.derivable || [],
        };
      })
      .filter((m) => m.missing.length > 0);
    const total = models.reduce((a, m) => a + m.missing.length, 0);
    return { models, total };
  }, [guideResult, selectedModels]);

  const toggleModel = useCallback((id: string) => {
    setSelectedModels((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  // ---------- P3：变量映射 ----------
  /** 进入步骤 4 时加载 varmap（按所选模型 + 所选文件自动预填） */
  const loadVarmap = useCallback(async () => {
    if (!appProject || analysisFiles.length === 0 || selectedModels.size === 0) return;
    setVarmapBusy(true);
    setVarmapError("");
    try {
      // v2.0 V2：优先 AI 匹配（LLM 推荐 + 置信度 + 统计量绑定）；LLM 不可用降级确定性
      const r = await finmodVarmapSuggest(
        appProject.id, analysisFiles[0].file_name, Array.from(selectedModels), model, "",
        analysisFileNames,
      );
      setVarmap(r.varmap);
      setAiUsed(r.used_llm);
      // AI 推荐映射（key=model_id:var_name）
      const aiMap: Record<string, { confidence: number; reason: string; candidates: string[] }> = {};
      const aiStat: Record<string, { stat: string; based_on: string }> = {};
      for (const m of r.ai_suggestions.mappings) {
        aiMap[`${m.model_id}:${m.var_name}`] = {
          confidence: m.confidence, reason: m.reason, candidates: m.candidates || [],
        };
      }
      for (const s of r.ai_suggestions.stat_bindings) {
        aiStat[`${s.model_id}:${s.var_name}`] = { stat: s.stat, based_on: s.based_on };
      }
      setAiMappings(aiMap);
      setAiStatBindings(aiStat);
      // AI 高置信映射自动应用（无基础用户零操作；低置信留给用户确认）
      const overrides: Record<string, Record<string, string>> = {};
      for (const m of r.ai_suggestions.mappings) {
        if (m.mapped_col && m.confidence >= 0.85) {
          overrides[m.model_id] = { ...(overrides[m.model_id] || {}), [m.var_name]: m.mapped_col };
        }
      }
      setMappingOverrides((prev) => {
        const merged = { ...prev };
        for (const [mid, mp] of Object.entries(overrides)) {
          merged[mid] = { ...(merged[mid] || {}), ...mp };
        }
        return merged;
      });
      // 统计量绑定：AI 建议 → statBindings（用户可改）
      const sb: { var_name: string; stat: string; based_on: string }[] = [];
      for (const s of r.ai_suggestions.stat_bindings) {
        sb.push({ var_name: s.var_name, stat: s.stat, based_on: s.based_on });
      }
      setStatBindings(sb);
      // v3.4：可派生变量候选公式 → 自动注入派生公式（用户可改/删除）
      if (r.derived_formulas && r.derived_formulas.length) {
        setDerivedFormulas((prev) => {
          const existing = new Set(prev.map((f) => f.text));
          const news = r.derived_formulas!
            .map((df) => ({ id: `df-${df.model_id}-${df.var_name}`, text: df.formula }))
            .filter((f) => !existing.has(f.text));
          return [...prev, ...news];
        });
      }
      // 预填期间列（自动识别第一个）
      if (r.varmap.period_cols.length > 0) setPeriodCol((p) => p || r.varmap.period_cols[0]);
    } catch (e) {
      // 降级：varmap-suggest 失败 → 用确定性 varmap
      try {
        const r = await finmodVarmap(appProject.id, analysisFiles[0].file_name, Array.from(selectedModels), "", analysisFileNames);
        setVarmap(r);
        if (r.period_cols.length > 0) setPeriodCol((p) => p || r.period_cols[0]);
      } catch (e2) {
        setVarmapError((e2 as Error).message || "变量映射加载失败");
      }
    } finally {
      setVarmapBusy(false);
    }
  }, [appProject, analysisFiles, analysisFileNames, selectedModels, model]);

  /** 用户修改某模型某变量的映射列 */
  const handleMappingChange = useCallback((modelId: string, varName: string, col: string) => {
    setMappingOverrides((prev) => {
      const next = { ...prev };
      next[modelId] = { ...(next[modelId] || {}), [varName]: col };
      return next;
    });
  }, []);

  /** v2.0：统计量变量绑定（用户改函数/来源列） */
  const handleStatBindingChange = useCallback((
    _modelId: string, varName: string, stat: string, basedOn: string,
  ) => {
    setStatBindings((prev) => {
      const others = prev.filter((s) => s.var_name !== varName);
      return [...others, { var_name: varName, stat, based_on: basedOn }];
    });
  }, []);

  /** 合并用户覆盖后的映射（展示用；预填 + 用户手动选择） */
  const mergedVarmapModels: FinmodVarmapModel[] = useMemo(() => {
    if (!varmap) return [];
    return varmap.models.map((m: FinmodVarmapModel) => {
      const over = mappingOverrides[m.model_id] || {};
      return {
        ...m,
        variables: m.variables.map((v) => ({
          ...v,
          mapped_col: over[v.var_name] !== undefined ? over[v.var_name] : v.mapped_col,
          status: (over[v.var_name] !== undefined ? over[v.var_name] : v.mapped_col) ? "matched" : "missing",
        })),
      };
    });
  }, [varmap, mappingOverrides]);

  /** 派生变量防抖实时重算（300ms） */
  const derivedTimer = useRef<number | null>(null);
  const runDerivedEval = useCallback(async () => {
    if (!appProject || analysisFiles.length === 0) return;
    const formulas = derivedFormulas.map((f) => f.text).filter((t) => t.trim());
    if (formulas.length === 0) {
      setDerivedResults({});
      setDerivedErrors([]);
      return;
    }
    setDerivedBusy(true);
    try {
      const r = await finmodDerivedEval(appProject.id, analysisFiles[0].file_name, formulas, {}, "", analysisFileNames);
      setDerivedResults(r.results);
      setDerivedErrors(r.errors);
    } catch (e) {
      setDerivedErrors([{ line: 0, name: "", kind: "value", message: (e as Error).message || "求值失败" }]);
    } finally {
      setDerivedBusy(false);
    }
  }, [appProject, analysisFiles, analysisFileNames, derivedFormulas]);
  useEffect(() => {
    if (derivedTimer.current) window.clearTimeout(derivedTimer.current);
    derivedTimer.current = window.setTimeout(() => { void runDerivedEval(); }, 300);
    return () => { if (derivedTimer.current) window.clearTimeout(derivedTimer.current); };
  }, [derivedFormulas, runDerivedEval]);

  // V3：数据预处理防抖预览（步骤链变化 → 调 prep-data）
  const prepTimer = useRef<number | null>(null);
  const runPrepPreview = useCallback(async () => {
    if (!appProject || analysisFiles.length === 0 || prepSteps.length === 0) {
      setPrepResult(null);
      return;
    }
    setPrepBusy(true);
    try {
      const r = await finmodPrepData(appProject.id, analysisFiles[0].file_name, prepSteps, "", analysisFileNames);
      setPrepResult(r);
    } catch (e) {
      setPrepResult({ success: false, columns: [], rows: 0, preview: [],
        logs: [`预览失败：${(e as Error).message}`], errors: [] });
    } finally {
      setPrepBusy(false);
    }
  }, [appProject, analysisFiles, analysisFileNames, prepSteps]);
  useEffect(() => {
    if (prepTimer.current) window.clearTimeout(prepTimer.current);
    prepTimer.current = window.setTimeout(() => { void runPrepPreview(); }, 400);
    return () => { if (prepTimer.current) window.clearTimeout(prepTimer.current); };
  }, [prepSteps, runPrepPreview]);

  /** 派生公式行操作 */
  const addDerived = useCallback(() => {
    setDerivedFormulas((prev) => [...prev, { id: `f${Date.now()}`, text: "" }]);
  }, []);
  const removeDerived = useCallback((id: string) => {
    setDerivedFormulas((prev) => prev.filter((f) => f.id !== id));
  }, []);
  const changeDerived = useCallback((id: string, text: string) => {
    setDerivedFormulas((prev) => prev.map((f) => (f.id === id ? { ...f, text } : f)));
  }, []);

  // ---------- P4：图表配置 ----------
  /** guide 推荐图表并集（LLM 按诉求定制，charts-suggest 优先使用） */
  const guideCharts = useMemo(() => {
    if (!guideResult?.directions) return [];
    const set = new Set<string>();
    for (const d of guideResult.directions) {
      for (const c of d.recommended_charts || []) set.add(c);
    }
    return Array.from(set);
  }, [guideResult]);

  /** 从建议生成 manifest（默认全选；已存在项保留；variant 空回退 template）
   *  R4：保留 importance（primary/secondary/optional）作为「优先建议」标注。 */
  const applySuggestions = useCallback((sug: FinmodChartSuggestResult) => {
    const metaCharts = new Map((meta?.charts || []).map((c) => [c.id, c]));
    setChartManifest((prev) => {
      const existing = new Set(prev.map((m) => m.variant || m.template));
      const added = sug.suggestions
        .filter((s) => !existing.has(s.template))
        .map((s) => {
          const cmeta = metaCharts.get(s.template.split("-")[0]);
          return {
            id: `c${Date.now()}-${s.template}`,
            template: s.template.split("-")[0],
            variant: s.template || s.template.split("-")[0],
            name: s.name,
            level: s.level,
            variants: cmeta?.variants && cmeta.variants.length > 0 ? cmeta.variants : [s.template],
            color_scheme: "auto",
            data_source: [],
            reason: s.reason,
            importance: s.importance || "secondary",  // R4：优先建议标注
          } as FinmodChartManifestItem;
        });
      return [...prev, ...added];
    });
  }, [meta]);

  /** 进入步骤 5 / 切换档位时拉取图表推荐（确定性） */
  const loadChartSuggest = useCallback(async (level: string) => {
    if (selectedModels.size === 0) return;
    setChartBusy(true);
    setChartError("");
    try {
      const r = await finmodChartSuggest(Array.from(selectedModels), guideCharts, level, stylePrefs);
      setChartSuggest(r);
      applySuggestions(r);
    } catch (e) {
      setChartError((e as Error).message || "图表推荐失败");
    } finally {
      setChartBusy(false);
    }
  }, [selectedModels, guideCharts, applySuggestions, stylePrefs]);

  /** R4：偏好变化 → 重新拉取图表推荐（同步档位 state） */
  // （偏好类别/配色变化由下方 useEffect 防抖触发；档位变化走 handleLevelChange）

  // R4：偏好（类别/配色）变化 → 重新推荐（防抖 300ms；仅在图表风格步骤激活且有模型时）
  const stylePrefTimer = useRef<number | null>(null);
  useEffect(() => {
    if (stylePrefTimer.current) window.clearTimeout(stylePrefTimer.current);
    stylePrefTimer.current = window.setTimeout(() => {
      if (flowStep === 3 && selectedModels.size > 0) {
        void loadChartSuggest(stylePrefs.level || chartLevel);
      }
    }, 300);
    return () => { if (stylePrefTimer.current) window.clearTimeout(stylePrefTimer.current); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stylePrefs.categories, stylePrefs.colors]);

  /** 进入步骤 3「图表风格」：拉推荐 + 收敛清单 */
  const enterStep5 = useCallback(() => {
    setMaxReached((m) => Math.max(m, 3));
    setFlowStep(3);
    void loadChartSuggest(chartLevel);
  }, [loadChartSuggest, chartLevel]);

  /** 档位切换：重新推荐 + 白名单过滤现有清单 */
  const handleLevelChange = useCallback((level: string) => {
    setChartLevel(level);
    void loadChartSuggest(level);
    // 档位白名单：移除超出档位的图（L1 不保留 L2/L3）
    const allowed = level === "L1" ? ["L1"] : level === "L2" ? ["L1", "L2"] : ["L1", "L2", "L3"];
    setChartManifest((prev) => prev.filter((m) => allowed.includes(m.level)));
  }, [loadChartSuggest]);

  /** 微观勾选模板（加入清单） */
  const toggleMicroChart = useCallback((template: string, name: string, level: string, variants: string[]) => {
    setChartManifest((prev) => {
      if (prev.some((m) => m.variant === template)) {
        return prev.filter((m) => m.variant !== template);
      }
      return [...prev, {
        id: `c${Date.now()}-${template}`,
        template: template.split("-")[0],
        variant: template,
        name,
        level,
        variants: variants.length > 0 ? variants : [template],
        color_scheme: "auto",
        data_source: [],
        reason: "手动勾选",
      } as FinmodChartManifestItem];
    });
  }, []);

  /** manifest 操作 */
  const removeChart = useCallback((id: string) => {
    setChartManifest((prev) => prev.filter((m) => m.id !== id));
  }, []);
  const moveChart = useCallback((id: string, dir: -1 | 1) => {
    setChartManifest((prev) => {
      const idx = prev.findIndex((m) => m.id === id);
      const next = [...prev];
      const j = idx + dir;
      if (idx < 0 || j < 0 || j >= next.length) return prev;
      [next[idx], next[j]] = [next[j], next[idx]];
      return next;
    });
  }, []);
  const changeVariant = useCallback((id: string, variant: string) => {
    setChartManifest((prev) => prev.map((m) => (m.id === id ? { ...m, variant } : m)));
  }, []);
  const changeColor = useCallback((id: string, color: string) => {
    setChartManifest((prev) => prev.map((m) => (m.id === id ? { ...m, color_scheme: color } : m)));
  }, []);

  /** v3.5：truly_missing（真正缺失的 input 变量）计数——放行需勾选「允许缺失分析」。
   * 判定：direction=input 且 status=missing 且无派生公式覆盖 → truly_missing。 */
  const trulyMissingCount = useMemo(() => {
    if (!mergedVarmapModels.length) return 0;
    return mergedVarmapModels.reduce((acc, m) => {
      return acc + m.variables.filter((v) => {
        if (v.direction === "output" || v.direction === "statistic") return false;
        if (v.status === "matched" || v.status === "statistic" || v.status === "output") return false;
        // input 且 missing：有派生公式覆盖 → 可派生（不算缺失）；否则真正缺失
        return !derivedFormulas.some((f) => f.text.includes(v.var_name));
      }).length;
    }, 0);
  }, [mergedVarmapModels, derivedFormulas]);

  /** v3.5 步骤 4 完成检查（软放宽）：无 truly_missing 即就绪；
   *  有 truly_missing 时，需勾选「允许缺失分析」才放行（报告给出说明）。 */
  const varmapReady = useCallback((): boolean => {
    if (!varmap || varmap.models.length === 0) return false;
    // 所有能映射/派生的都就绪，且无真正缺失 → 直接放行
    return trulyMissingCount === 0 || allowMissingAnalysis;
  }, [varmap, trulyMissingCount, allowMissingAnalysis]);

  // ---------- P5：确定性执行 ----------
  /** 进入步骤 4「AI 撰写报告」：触发 run（配置清单 → 后端并行计算，0 LLM） */
  const enterStep6 = useCallback(() => {
    if (!appProject || analysisFiles.length === 0 || selectedModels.size === 0 || chartManifest.length === 0) return;
    setMaxReached((m) => Math.max(m, 4));
    setFlowStep(4);
    setReportPhase("execute");
    setRunBusy(true);
    setRunError("");
    // 组装变量映射（mergedVarmapModels：模型变量 → 列）
    const mappings: Record<string, Record<string, string>> = {};
    for (const m of mergedVarmapModels) {
      mappings[m.model_id] = {};
      for (const v of m.variables) {
        if (v.mapped_col) mappings[m.model_id][v.var_name] = v.mapped_col;
      }
    }
    // v2.0 V1：派生/统计量公式 → run 物化（统计量广播整列喂给模型）
    const derived = [...derivedFormulas.map((f) => f.text).filter((t) => t.trim())];
    for (const sb of statBindings) {
      if (sb.based_on) {
        derived.push(`${sb.var_name}=${sb.stat}(${sb.based_on})`);
      }
    }
    finmodRun(
      appProject.id,
      analysisFiles[0].file_name,
      Array.from(selectedModels),
      mappings,
      {},
      chartManifest,
      derived,
      prepSteps,  // V3：数据预处理步骤
      analysisFileNames,  // R1：参与分析的多文件
    )
      .then((r) => {
        setRunResult(r);
        setRunBusy(false);
        setMaxReached((m) => Math.max(m, 4));
        // R3：执行完成自动衔接「报告」子阶段（用户点击「AI 撰写报告」生成正文）
        setReportPhase("report");
        // P6：写入历史（localStorage，最多 10 条）
      })
      .catch((e) => {
        setRunError((e as Error).message || "执行失败");
        setRunBusy(false);
      });
  }, [appProject, analysisFiles, analysisFileNames, selectedModels, chartManifest, mergedVarmapModels, derivedFormulas, statBindings, prepSteps]);

  // ---------- P6：报告交付（批量 SVG 落盘 → export-md） ----------
  /** 步骤 7「生成报告」：逐图离屏 SVG → save-chart → export-md（LLM 报告 + 路径）。 */
  const runReport = useCallback(async () => {
    if (!appProject || !runResult) return;
    setReportBusy(true);
    setReportError("");
    setSavedCharts([]);
    setReportResult(null);
    try {
      const runId = runResult.runId || runResult.run_id;
      const saved: { filename: string; rel_path: string; format: string }[] = [];
      const chartsWithPath: (FinmodRunResult["charts"][number] & { rel_path?: string })[] = [];
      // 逐图落盘（2D → SVG；3D(Python) → finmodPyChart PNG；均失败跳过）
      for (const ch of runResult.charts) {
        const tpl = ch.variant || ch.template;
        const base = sanitizeFileName(`${ch.name || ch.variant || "chart"}_${ch.chart_id || chartsWithPath.length + 1}`);

        // v6.9：3D 模板改用 Python 生成 PNG（echarts-gl 无矢量、且渲染为曲面不符预期）
        if (PY3D_TEMPLATES.has(tpl) || PY3D_TEMPLATES.has(ch.template)) {
          try {
            const py = await finmodPyChart(tpl, ch.data as unknown as Record<string, unknown>);
            if (py.success && py.b64) {
              const fileName = `${base}.png`;
              const r = await finmodSaveChart(appProject.id, runId, fileName, py.b64, "png");
              saved.push({ filename: r.filename, rel_path: r.rel_path, format: "png" });
              chartsWithPath.push({ ...ch, rel_path: r.rel_path });
              continue;
            }
          } catch { /* Python 3D 失败 → 走下方兜底 */ }
          chartsWithPath.push({ ...ch });
          continue;
        }

        let option = buildChartOption(tpl, ch.data as never, ch.name, undefined);
        if (!option) {
          // 未知模板 → 尝试原始 option（run 已带 data）
          option = buildChartOption("line", ch.data as never, ch.name, undefined);
        }
        if (!option) {
          chartsWithPath.push({ ...ch });
          continue;
        }
        const opt = option as unknown as Record<string, unknown>;
        let content = await renderOptionToSvg(opt);
        let format: "svg" | "png" = "svg";
        if (!content) {
          content = await renderOptionToPng(opt);
          format = "png";
        }
        if (!content) {
          chartsWithPath.push({ ...ch });
          continue;
        }
        const fileName = `${base}.${format}`;
        const r = await finmodSaveChart(appProject.id, runId, fileName, content, format);
        saved.push({ filename: r.filename, rel_path: r.rel_path, format });
        chartsWithPath.push({ ...ch, rel_path: r.rel_path });
      }
      setSavedCharts(saved);
      // export-md（LLM 报告；LLM 不可用 → 后端降级确定性报告）
      // R5：传 data_stats（数据概览）+ style_prefs（图表风格偏好）
      const md = await finmodExportMd({
        projectId: appProject.id,
        runId,
        goal,
        modelId: model,
        models: runResult.models,
        charts: chartsWithPath,
        dataStats: runResult.data_stats as Record<string, unknown> | undefined,
        stylePrefs,
      });
      setReportResult(md);
      // 报告生成成功 → 写入历史分析报告（localStorage，供历史记录区/新标签页预览）
      try {
        const item: ReportHistoryItem = {
          id: runId,
          runId,
          rel_path: md.rel_path,
          filename: md.filename,
          goal: goal || "财务建模分析",
          createdAt: new Date().toISOString(),
        };
        setReportHistory((prev) => {
          const next = [item, ...prev.filter((p) => p.id !== item.id)].slice(0, 50);
          localStorage.setItem("app_finmod_report_history", JSON.stringify(next));
          return next;
        });
      } catch { /* 历史写入失败不影响主流程 */ }
    } catch (e) {
      setReportError((e as Error).message || "报告生成失败");
    } finally {
      setReportBusy(false);
    }
  }, [appProject, runResult, goal, model, stylePrefs]);

  /** 阶段 2：进入「② AI 撰写报告」子阶段且执行结果就绪、报告未生成时自动触发 runReport */
  useEffect(() => {
    if (reportPhase === "report" && flowStep === 4 && runResult && !reportResult && !reportBusy) {
      void runReport();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [reportPhase, flowStep, runResult, reportResult, reportBusy]);

  /** 加载历史分析报告（localStorage） */
  useEffect(() => {
    try {
      const prev = JSON.parse(localStorage.getItem("app_finmod_report_history") || "[]") as ReportHistoryItem[];
      if (Array.isArray(prev)) setReportHistory(prev);
    } catch { /* 忽略损坏历史 */ }
  }, []);

  /** 历史分析报告：删除一条 */
  const handleDeleteReport = useCallback((id: string) => {
    setReportHistory((prev) => {
      const next = prev.filter((p) => p.id !== id);
      localStorage.setItem("app_finmod_report_history", JSON.stringify(next));
      return next;
    });
  }, []);

  /** 历史分析报告：刷新（从 localStorage 重载） */
  const handleRefreshReports = useCallback(() => {
    try {
      const prev = JSON.parse(localStorage.getItem("app_finmod_report_history") || "[]") as ReportHistoryItem[];
      setReportHistory(Array.isArray(prev) ? prev : []);
    } catch { /* 忽略损坏 */ }
  }, []);

  /** 在【新标签页】打开一份历史报告（复用预览功能，不影响当前页面） */
  const openReportInNewTab = useCallback((item: ReportHistoryItem) => {
    if (!appProject) return;
    const q = new URLSearchParams({
      preview: "1",
      project_id: appProject.id,
      path: item.rel_path,
    });
    window.open(`/?${q.toString()}`, "_blank");
  }, [appProject]);

  // ---------- 共享头部 ----------
  const appHeader = (
    <div className="border-b border-zinc-200 bg-white px-6 pt-4 pb-3">
      <div className="mx-auto max-w-6xl space-y-3">
        <div className="flex items-center justify-between gap-3">
          <div>
            <h1 className="text-lg font-semibold text-zinc-900">财务建模与分析</h1>
            <p className="mt-0.5 text-[13px] text-zinc-500">
              AI 引导完成「数据 → 模型 → 图表 → Markdown 报告」，计算与渲染 100% 确定性。
            </p>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            {/* 模型选择（P2：引导用的 AI 模型） */}
            <div className="rounded-lg border border-zinc-200 bg-white">
              <ModelPicker
                models={models}
                providers={providers}
                value={model}
                onChange={handleSelectModel}
                disabled={guideBusy}
                direction="down"
              />
            </div>
          </div>
        </div>

        {/* 应用专用 AI（折叠卡，v6.14-2：与应用一数据核对一致——点击查看职责与约束） */}
        {skill && (
          <details className="overflow-hidden rounded-xl border border-zinc-200">
            <summary className="flex cursor-pointer select-none items-center gap-2 px-3.5 py-2 transition-colors hover:bg-zinc-50">
              <BotIcon />
              <span className="text-[12.5px] font-semibold text-zinc-800">应用专用 AI</span>
              <span className="rounded-full bg-zinc-100 px-1.5 py-px text-[10px] font-medium text-zinc-500">financial-modeling skill</span>
              <span className="ml-auto text-[11px] text-zinc-400">点击查看 AI 职责与约束</span>
            </summary>
            <div className="border-t border-zinc-100 px-3.5 py-2.5">
              <p className="text-[12px] leading-relaxed text-zinc-600">
                本应用内 AI 是「财务建模专用工具」，不是通用智能体：只按流程引导完成数据 → 模型 → 图表 → 报告，
                计算与渲染 100% 确定性，禁止自由发挥、禁止绕过流程确认，使结果可复现。
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

  // ---------- 左侧竖排步骤导航 ----------
  const stepNav = (
    <nav className="flex w-44 shrink-0 flex-col border-r border-zinc-200 bg-white py-3">
      {FLOW_STEPS.map((s, i) => {
        const active = flowStep === s.n;
        const done = maxReached > s.n;
        const interactive = s.n <= maxReached;
        return (
          <div key={s.n} className={i > 0 ? "mt-1" : ""}>
            <button
              onClick={() => { if (interactive) { setFlowStep(s.n); if (s.n === 2) setMacroPhase("direction"); if (s.n === 4) setReportPhase("execute"); } }}
              disabled={!interactive}
              title={interactive ? `回到步骤 ${s.n}：${s.label}` : "尚未到达"}
              className={`flex w-full items-center gap-2.5 px-5 py-2.5 text-[12.5px] transition-colors ${
                active
                  ? "bg-zinc-50 font-semibold text-zinc-900"
                  : interactive
                    ? "text-zinc-600 hover:bg-zinc-50"
                    : "cursor-not-allowed text-zinc-300"
              }`}
            >
              <span
                className={`flex size-5 shrink-0 items-center justify-center rounded-full text-[11px] font-semibold ${
                  active ? "bg-zinc-900 text-white" : done ? "bg-emerald-100 text-emerald-600" : interactive ? "bg-zinc-200 text-zinc-500" : "bg-zinc-100 text-zinc-300"
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

      {/* 第 5 项：历史记录（独立页面，与上面 4 个步骤同款导航项） */}
      <div className="mt-2 border-t border-zinc-100 pt-2">
        <button
          onClick={() => { setFlowStep(5); }}
          title="历史记录：管理所有历史分析报告"
          className={`flex w-full items-center gap-2.5 px-5 py-2.5 text-[12.5px] transition-colors ${
            flowStep === 5 ? "bg-zinc-50 font-semibold text-zinc-900" : "text-zinc-600 hover:bg-zinc-50"
          }`}
        >
          <span className={`flex size-5 shrink-0 items-center justify-center rounded-full text-[11px] font-semibold ${
            flowStep === 5 ? "bg-zinc-900 text-white" : "bg-zinc-200 text-zinc-500"
          }`}>
            <History size={12} />
          </span>
          历史记录
          {reportHistory.length > 0 && (
            <span className="ml-auto rounded-full bg-blue-50 px-1.5 py-0.5 text-[10px] font-medium text-blue-600">
              {reportHistory.length}
            </span>
          )}
          {flowStep === 5 && <span className="ml-auto h-1.5 w-1.5 rounded-full bg-zinc-900" />}
        </button>
      </div>
    </nav>
  );

  // ---------- 步骤 1：诉求入口 ----------
  const step1Panel = (
    <div className="min-h-0 flex-1 overflow-y-auto px-6 pt-5 pb-4">
      <div className="mx-auto max-w-3xl space-y-4">
        <div>
          <h2 className="text-[14px] font-semibold text-zinc-800">你的分析目标是什么？</h2>
          <p className="mt-0.5 text-[12px] text-zinc-400">用一句话描述诉求；也可以先上传数据文件，让 AI 根据数据推荐分析方向。</p>
        </div>

        {/* 诉求输入 */}
        <textarea
          value={goal}
          onChange={(e) => setGoal(e.target.value)}
          placeholder="例如：我想看今年利润为什么下降 / 帮我预测明年销售额 / 分析各产品线的盈利能力…"
          rows={3}
          className="w-full resize-none rounded-lg border border-zinc-200 bg-white px-3.5 py-3 text-[13.5px] leading-relaxed text-zinc-800 outline-none transition-colors placeholder:text-zinc-400 focus:border-blue-400 focus:ring-2 focus:ring-blue-100"
        />

        {/* 数据文件区 */}
        <div className="rounded-lg border border-zinc-200 bg-white">
          <div className="flex items-center justify-between border-b border-zinc-100 px-4 py-2.5">
            <span className="flex items-center gap-2 text-[13px] font-medium text-zinc-700">
              <Database size={14} className="text-zinc-400" />
              数据文件
              <span className="text-[11px] font-normal text-zinc-400">（项目数据库 · 已导入 {files.length} 个）</span>
            </span>
            <button
              onClick={() => setDbOpen(true)}
              className="flex items-center gap-1.5 rounded-md bg-blue-600 px-3 py-1.5 text-[12px] font-medium text-white transition-colors hover:bg-blue-500"
            >
              <FileSpreadsheet size={13} />
              管理数据（上传/删除）
            </button>
          </div>
          <div className="px-4 py-3">
            {files.length === 0 ? (
              <p className="py-4 text-center text-[12.5px] text-zinc-400">
                还没有数据文件——可点上方「管理数据」上传 Excel；或先填写诉求让 AI 告诉你要准备哪些字段。
              </p>
            ) : (
              <div className="flex flex-wrap gap-2">
                {files.map((f) => {
                  const isSel = analysisFiles.some((sf) => sf.file_name === f.file_name);
                  return (
                    <button
                      key={f.id}
                      onClick={() => toggleAnalysisFile(f)}
                      className={`flex items-center gap-1.5 rounded-full border px-3 py-1 text-[12px] transition-colors ${
                        isSel
                          ? "border-blue-300 bg-blue-50 text-blue-700"
                          : "border-zinc-200 bg-zinc-50 text-zinc-500 hover:border-zinc-300"
                      }`}
                    >
                      {isSel ? <Check size={12} className="text-blue-500" /> : <FileSpreadsheet size={12} className="text-zinc-400" />}
                      {f.file_name}
                      <span className="text-[10px] opacity-70">{f.sheet_count} 表 · {f.total_rows} 行</span>
                    </button>
                  );
                })}
              </div>
            )}
            {analysisFiles.length > 1 && (
              <p className="mt-2 flex items-center gap-1 text-[11.5px] text-blue-600">
                <Layers size={11} />
                已选 {analysisFiles.length} 个文件参与分析，将自动合并建模
              </p>
            )}
          </div>
        </div>

        {/* 下一步 */}
        <div className="flex items-center justify-between">
          <p className="text-[12px] text-zinc-400">
            {goal.trim() || files.length > 0
              ? goal.trim() && files.length > 0
                ? "诉求 + 数据已就绪 → 让 AI 分析（模式 B）"
                : goal.trim()
                  ? "有目标无数据 → AI 将输出数据需求清单（模式 A）"
                  : "有数据无目标 → AI 将给出讲解引导（模式 C）"
              : "请填写诉求或上传数据文件"}
          </p>
          <button
            onClick={handleNextToGuide}
            disabled={!goal.trim() && files.length === 0}
            className={`flex items-center gap-1.5 rounded-lg px-5 py-2 text-[13px] font-medium transition-colors ${
              goal.trim() || files.length > 0
                ? "bg-zinc-900 text-white hover:bg-zinc-700"
                : "cursor-not-allowed bg-zinc-100 text-zinc-400"
            }`}
          >
            <Sparkles size={14} />
            开始建模
            <ArrowRight size={14} />
          </button>
        </div>
      </div>
    </div>
  );

  // ---------- 步骤 2：建模方向（AI 引导 + 模型库补充，v1.9 合并原步骤 2/3） ----------
  const step2Panel = (
    <div className="min-h-0 flex-1 overflow-y-auto px-6 pt-5 pb-4">
      <div className="mx-auto max-w-4xl space-y-5">
        {/* 引导中 loading（点状动画） */}
        {guideBusy && (
          <div className="flex items-center gap-2 rounded-lg border border-zinc-200 bg-white px-4 py-3 text-[13px] text-zinc-500">
            <LoadingState label="正在对照诉求与数据列名找合适的模型…" />
            <span className="ml-auto text-[11px] text-zinc-400">1 次模型调用</span>
          </div>
        )}
        {guideError && (
          <div className="flex items-center gap-2 rounded-md bg-red-50 px-3 py-2 text-[13px] text-red-600">
            <AlertTriangle size={14} />
            {guideError}
          </div>
        )}

        {/* 模式 A：数据需求清单卡 */}
        {!guideBusy && guideResult?.mode === "A" && (
          <div className="rounded-lg border border-amber-200 bg-amber-50/40">
            <div className="border-b border-amber-100 px-4 py-3">
              <h3 className="flex items-center gap-2 text-[13.5px] font-semibold text-zinc-800">
                <AlertTriangle size={14} className="text-amber-500" />
                需要先准备数据：请按下方清单上传 Excel
              </h3>
              <p className="mt-0.5 text-[12px] text-zinc-500">{guideResult.message || "已分析你的诉求，识别出以下所需字段："}</p>
            </div>
            <div className="px-4 py-3">
              <div className="overflow-x-auto rounded-md border border-zinc-200 bg-white">
                <table className="w-full border-collapse text-[12.5px]">
                  <thead>
                    <tr>
                      <th className="border-b border-zinc-200 bg-zinc-50 px-2.5 py-2 text-left font-medium text-zinc-600">字段</th>
                      <th className="border-b border-zinc-200 bg-zinc-50 px-2.5 py-2 text-left font-medium text-zinc-600">类型</th>
                      <th className="border-b border-zinc-200 bg-zinc-50 px-2.5 py-2 text-left font-medium text-zinc-600">示例</th>
                      <th className="border-b border-zinc-200 bg-zinc-50 px-2.5 py-2 text-left font-medium text-zinc-600">用途</th>
                      <th className="border-b border-zinc-200 bg-zinc-50 px-2.5 py-2 text-left font-medium text-zinc-600">建议图表</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(guideResult.data_needs || []).map((n, i) => (
                      <tr key={i} className="border-b border-zinc-100 last:border-b-0">
                        <td className="px-2.5 py-1.5 font-medium text-zinc-800">{n.field}</td>
                        <td className="px-2.5 py-1.5 text-zinc-500">{n.type}</td>
                        <td className="px-2.5 py-1.5 text-zinc-500">{n.example}</td>
                        <td className="px-2.5 py-1.5 text-zinc-500">{n.purpose}</td>
                        <td className="px-2.5 py-1.5">
                          {n.suggested_chart && (
                            <span className="rounded bg-zinc-100 px-1.5 py-0.5 font-mono text-[10px] text-zinc-500">{n.suggested_chart}</span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="mt-3 flex items-center gap-2">
                <button
                  onClick={() => setDbOpen(true)}
                  className="flex items-center gap-1.5 rounded-lg bg-blue-600 px-4 py-2 text-[12.5px] font-medium text-white hover:bg-blue-500"
                >
                  <FileSpreadsheet size={13} />
                  上传数据文件
                </button>
                <button
                  onClick={() => handleRerunGuide()}
                  disabled={files.length === 0}
                  className={`flex items-center gap-1.5 rounded-lg px-4 py-2 text-[12.5px] font-medium transition-colors ${
                    files.length > 0 ? "bg-zinc-900 text-white hover:bg-zinc-700" : "cursor-not-allowed bg-zinc-100 text-zinc-400"
                  }`}
                >
                  <Sparkles size={13} />
                  补齐后重新引导（{files.length > 0 ? `已上传 ${files.length} 个文件` : "待上传"}）
                </button>
              </div>
              <p className="mt-2 text-[11.5px] text-zinc-400">提示：上传数据后点「重新引导」，将基于实际列名推荐模型。</p>
            </div>
          </div>
        )}

        {/* 模式 C：讲解卡 + 诉求输入 */}
        {!guideBusy && guideResult?.mode === "C" && (
          <div className="rounded-lg border border-blue-200 bg-blue-50/40">
            <div className="border-b border-blue-100 px-4 py-3">
              <h3 className="flex items-center gap-2 text-[13.5px] font-semibold text-zinc-800">
                <BookOpen size={14} className="text-blue-500" />
                财务建模能帮你做什么
              </h3>
              <p className="mt-0.5 text-[12px] text-zinc-500">先看看模型能做什么；说出目标后即可开始。</p>
            </div>
            <div className="px-4 py-3">
              {guideResult.explanation && (
                <div className="rounded-md border border-zinc-200 bg-white px-3 py-2.5">
                  {/* v6.14-2：AI 讲解文案自动分点 + 更小字体（页面主流字号 13px） */}
                  <MarkdownBlock
                    text={autoListify(guideResult.explanation)}
                    className="text-[13px]"
                  />
                </div>
              )}
              <div className="mt-3">
                <textarea
                  value={goal}
                  onChange={(e) => setGoal(e.target.value)}
                  placeholder="现在告诉我你的目标，例如：我想分析回款效率…"
                  rows={2}
                  className="w-full resize-none rounded-lg border border-zinc-200 bg-white px-3 py-2.5 text-[13px] text-zinc-800 outline-none placeholder:text-zinc-400 focus:border-blue-400 focus:ring-2 focus:ring-blue-100"
                />
                <button
                  onClick={() => handleRerunGuide(goal)}
                  disabled={!goal.trim()}
                  className={`mt-2 flex items-center gap-1.5 rounded-lg px-4 py-2 text-[12.5px] font-medium transition-colors ${
                    goal.trim() ? "bg-zinc-900 text-white hover:bg-zinc-700" : "cursor-not-allowed bg-zinc-100 text-zinc-400"
                  }`}
                >
                  <Sparkles size={13} />
                  说出目标后重新引导
                </button>
              </div>
            </div>
          </div>
        )}

        {/* 降级：LLM 不可用 → 提示 + 直接走模型库（同页） */}
        {!guideBusy && guideResult && !guideResult.success && (
          <div className="rounded-lg border border-amber-200 bg-amber-50/40 px-4 py-3">
            <p className="flex items-center gap-2 text-[13px] font-medium text-amber-700">
              <AlertTriangle size={14} />
              {guideResult.message || "AI 引导不可用"}
            </p>
            <p className="mt-1 text-[12px] text-zinc-500">你仍可手动勾选下方模型库的模型完成建模。</p>
          </div>
        )}

        {/* AI 推荐区（模式 B：引导成功出方向，默认勾选） */}
        {!guideBusy && guideResult?.success && guideResult.mode === "B" && (
          <section>
            {/* R2：数据不完备提示 + 数据需求卡（选中模型有真正缺失变量时） */}
            {selectedMissingNeeds.total > 0 && (
              <div className="mb-3 rounded-lg border border-amber-200 bg-amber-50/50">
                <div className="border-b border-amber-100 px-4 py-3">
                  <h3 className="flex items-center gap-2 text-[13.5px] font-semibold text-zinc-800">
                    <AlertTriangle size={14} className="text-amber-500" />
                    还需补充 {selectedMissingNeeds.total} 个数据字段
                  </h3>
                  <p className="mt-0.5 text-[12px] text-zinc-500">
                    已选模型缺少以下变量。补传数据后点「重新引导」，AI 将基于新列名重新推荐方向；字段也可用已有列派生。
                  </p>
                </div>
                <div className="space-y-2 px-4 py-3">
                  {selectedMissingNeeds.models.map((m) => (
                    <div key={`${m.code}-${m.name}`} className="rounded-md border border-zinc-200 bg-white px-3 py-2">
                      <p className="text-[12.5px] font-semibold text-zinc-700">
                        <span className="font-mono text-zinc-400">{m.code}</span> {m.name}
                      </p>
                      <div className="mt-1.5 flex flex-wrap gap-1.5">
                        {m.missing.map((v) => (
                          <span key={v.var_name} className="inline-flex items-center gap-1 rounded-md bg-red-50 px-2 py-0.5 text-[11px] text-red-600">
                            <X size={10} className="opacity-60" />
                            {v.var_name}
                            {v.meaning && <span className="text-red-400">· {v.meaning}</span>}
                          </span>
                        ))}
                        {m.derivable.length > 0 && (
                          <span className="inline-flex items-center gap-1 rounded-md bg-emerald-50 px-2 py-0.5 text-[11px] text-emerald-600">
                            可派生：{m.derivable.slice(0, 4).join("、")}{m.derivable.length > 4 ? " 等" : ""}
                          </span>
                        )}
                      </div>
                    </div>
                  ))}
                  <div className="flex flex-wrap items-center gap-2 pt-1">
                    <button
                      onClick={() => setDbOpen(true)}
                      className="flex items-center gap-1.5 rounded-lg bg-blue-600 px-4 py-2 text-[12.5px] font-medium text-white hover:bg-blue-500"
                    >
                      <FileSpreadsheet size={13} />
                      上传/补数据文件
                    </button>
                    <button
                      onClick={() => handleRerunGuide()}
                      className="flex items-center gap-1.5 rounded-lg bg-zinc-900 px-4 py-2 text-[12.5px] font-medium text-white hover:bg-zinc-700"
                    >
                      <Sparkles size={13} />
                      重新引导（{analysisFiles.length > 0 ? `已选 ${analysisFiles.length} 个文件` : "待补数据"}）
                    </button>
                  </div>
                  <p className="text-[11.5px] text-zinc-400">提示：补传数据后需在步骤 1 勾选该文件参与分析，再点「重新引导」。</p>
                </div>
              </div>
            )}

            <div className="mb-2 flex items-center gap-2">
              <Sparkles size={15} className="text-blue-500" />
              <h3 className="text-[14px] font-semibold text-zinc-800">建议的建模方向</h3>
              <span className="text-[11px] text-zinc-400">（默认已勾选，可取消；下方模型库可再补充）</span>
            </div>
            {(guideResult.directions || []).length === 0 ? (
              <div className="flex items-center gap-2 rounded-md bg-amber-50 px-3 py-2 text-[13px] text-amber-600">
                <AlertTriangle size={14} />
                没能给出方向建议，可以直接从下方模型库选择
              </div>
            ) : (
              <div className="space-y-2.5">
                {(guideResult.directions || []).map((d, i) => (
                  <GuideCard
                    key={d.model_id}
                    direction={d}
                    selected={selectedModels.has(d.model_id)}
                    onToggle={() => toggleModel(d.model_id)}
                    index={i}
                  />
                ))}
              </div>
            )}
          </section>
        )}

        {/* 模型库补充（A-G 分类勾选；模式 B 或降级后可用） */}
        {!guideBusy && guideResult && (guideResult.success ? guideResult.mode === "B" : true) && (
          <section>
            <div className="mb-2 flex items-center gap-2">
              <BookOpen size={14} className="text-zinc-400" />
              <h2 className="text-[13.5px] font-semibold text-zinc-800">模型库补充</h2>
              <span className="text-[11px] text-zinc-400">32 个模型按 A-G 分类 · 点击卡展开详情 · 勾选加入清单</span>
            </div>
            {metaError && (
              <div className="flex items-center gap-2 rounded-md bg-red-50 px-3 py-2 text-[13px] text-red-600">
                <AlertTriangle size={14} />
                {metaError}
              </div>
            )}
            {!meta && !metaError && (
              <div className="flex items-center gap-2 py-6 text-[13px] text-zinc-400">
                <LoadingState label="正在加载模型目录…" />
              </div>
            )}
            {meta && meta.model_categories.map((cat) => (
              <section key={cat.key}>
                <div className="mb-1.5 flex items-baseline gap-2">
                  <span className="flex size-5 items-center justify-center rounded bg-zinc-900 text-[11px] font-bold text-white">{cat.key}</span>
                  <span className="text-[13px] font-semibold text-zinc-700">{cat.label}</span>
                  <span className="text-[11px] text-zinc-400">{cat.models.length} 个</span>
                </div>
                <div className="space-y-1.5">
                  {cat.models.map((m) => (
                    <ModelCard
                      key={m.id}
                      meta={m}
                      expanded={expandedModel === m.id}
                      onToggle={() => setExpandedModel(expandedModel === m.id ? null : m.id)}
                      selected={selectedModels.has(m.id)}
                      onSelect={() => toggleModel(m.id)}
                    />
                  ))}
                </div>
              </section>
            ))}
          </section>
        )}

        {/* 已选清单 + 下一步（变量映射） */}
        {!guideBusy && guideResult && (guideResult.success ? guideResult.mode === "B" : true) && (
          <div className="rounded-lg border border-zinc-200 bg-white px-4 py-3">
            <div className="flex items-center justify-between gap-3">
              <div className="min-w-0">
                <p className="text-[12px] font-medium text-zinc-500">已选模型（{selectedModels.size} 个）</p>
                <div className="mt-1.5 flex flex-wrap gap-1.5">
                  {selectedModels.size === 0 ? (
                    <span className="text-[12px] text-zinc-400">至少选择 1 个模型才能继续</span>
                  ) : (
                    Array.from(selectedModels).map((id) => {
                      const m = meta?.models.find((x) => x.id === id);
                      return (
                        <span key={id} className="flex items-center gap-1 rounded-full bg-blue-50 px-2.5 py-1 text-[12px] font-medium text-blue-700">
                          {m ? `${m.code} ${m.name}` : id}
                          <button onClick={() => toggleModel(id)} className="text-blue-400 hover:text-blue-600" title="移除">
                            <X size={12} />
                          </button>
                        </span>
                      );
                    })
                  )}
                </div>
              </div>
              <div className="flex-shrink-0 text-right">
                {selectedMissingNeeds.total > 0 && (
                  <p className="mb-1.5 max-w-[220px] text-[11px] leading-relaxed text-amber-600">
                    有 {selectedMissingNeeds.total} 个字段待补，可先在变量映射派生或标记缺失
                  </p>
                )}
                <button
                  onClick={() => { setMaxReached((m) => Math.max(m, 2)); setMacroPhase("varmap"); void loadVarmap(); }}
                  disabled={selectedModels.size === 0}
                  className={`shrink-0 rounded-lg px-5 py-2 text-[13px] font-medium transition-colors ${
                    selectedModels.size > 0 ? "bg-zinc-900 text-white hover:bg-zinc-700" : "cursor-not-allowed bg-zinc-100 text-zinc-400"
                  }`}
                >
                  下一步（变量映射）
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );

  // ---------- 步骤 3：变量映射（P3） ----------
  // ---------- 步骤 3：图表风格（R4：P4 图表配置增强） ----------
  const step4Panel = (
    <div className="min-h-0 flex-1 overflow-y-auto px-6 pt-5 pb-4">
      <div className="mx-auto max-w-4xl space-y-5">
        {/* R4 图表风格偏好：复杂度 + 类别偏好 + 配色（用户表达「希望出现什么风格」，非硬性勾选） */}
        <div className="space-y-3 rounded-lg border border-zinc-200 bg-white px-4 py-3.5">
          <div className="flex items-center gap-2">
            <ChartColumn size={15} className="text-zinc-400" />
            <span className="text-[13px] font-semibold text-zinc-700">图表风格偏好</span>
            <span className="text-[11px] text-zinc-400">告诉 AI 你希望报告里出现什么风格的图——最终图表构成由 AI 按报告内容决定</span>
          </div>
          {/* 复杂度档位 */}
          <div className="flex flex-wrap items-center gap-3">
            <span className="text-[12px] text-zinc-500">复杂度</span>
            <div className="flex gap-1.5">
              {(["L1", "L2", "L3"] as const).map((lv) => (
                <button
                  key={lv}
                  onClick={() => {
                    setChartLevel(lv);
                    setStylePrefs((p) => ({ ...p, level: lv }));
                    handleLevelChange(lv);
                  }}
                  className={`rounded-full px-3 py-1 text-[12px] font-medium transition-colors ${
                    chartLevel === lv
                      ? lv === "L1" ? "bg-emerald-600 text-white"
                        : lv === "L2" ? "bg-blue-600 text-white"
                          : "bg-violet-600 text-white"
                      : "border border-zinc-200 bg-white text-zinc-500 hover:bg-zinc-100"
                  }`}
                >
                  {lv === "L1" ? "简单" : lv === "L2" ? "中等" : "复杂"}
                </button>
              ))}
            </div>
          </div>
          {/* 类别偏好（多选） */}
          <div className="flex flex-wrap items-center gap-3">
            <span className="text-[12px] text-zinc-500">偏好类型</span>
            <div className="flex flex-wrap gap-1.5">
              {CHART_CATEGORY_OPTIONS.map((c) => {
                const on = (stylePrefs.categories || []).includes(c.id);
                return (
                  <button
                    key={c.id}
                    onClick={() => togglePrefCategory(c.id)}
                    className={`rounded-full px-2.5 py-1 text-[11.5px] font-medium transition-colors ${
                      on ? "bg-blue-600 text-white" : "border border-zinc-200 bg-white text-zinc-500 hover:bg-zinc-100"
                    }`}
                  >
                    {on ? `✓ ${c.label}` : c.label}
                  </button>
                );
              })}
            </div>
            <span className="text-[10.5px] text-zinc-400">（多选；命中偏好的图标记为「优先」）</span>
          </div>
          {/* 配色偏好 */}
          <div className="flex flex-wrap items-center gap-3">
            <span className="text-[12px] text-zinc-500">配色</span>
            <select
              value={stylePrefs.colors || "auto"}
              onChange={(e) => setStylePrefs((p) => ({ ...p, colors: e.target.value }))}
              className="rounded-md border border-zinc-200 bg-white px-2 py-1 text-[12px] text-zinc-700 outline-none focus:border-blue-400"
            >
              {[
                { v: "auto", l: "自动（蓝橙主色）" },
                { v: "blues", l: "蓝色系渐变" },
                { v: "greens", l: "绿色系渐变" },
                { v: "reds", l: "红色系渐变" },
                { v: "oranges", l: "橙色系渐变" },
                { v: "purples", l: "紫色系渐变" },
                { v: "blacks", l: "黑灰色系" },
              ].map((o) => (
                <option key={o.v} value={o.v}>{o.l}</option>
              ))}
            </select>
            <span className="ml-auto text-[11.5px] text-zinc-400">
              {chartManifest.length} 张图已加入{chartSuggest ? ` · ${chartSuggest.note}` : ""}
            </span>
          </div>
        </div>

        {/* AI 推荐图表（来自 charts-suggest：guide 优先 + 模型映射 + 偏好）
            v6.8：与图表库同款展开卡——折叠=名称+理由+加入；展开=模板预览+示例数据
            R4：折叠行增加 importance 徽章（优先/按需/兜底） */}
        <section>
          <div className="mb-2 flex items-center gap-2">
            <Sparkles size={14} className="text-blue-500" />
            <h2 className="text-[13.5px] font-semibold text-zinc-800">AI 推荐图表</h2>
            <span className="text-[11px] text-zinc-400">（默认加入清单，可移除；点击展开看效果）</span>
          </div>
          {chartBusy && (
            <div className="flex items-center gap-2 rounded-lg border border-zinc-200 bg-white px-4 py-3 text-[13px] text-zinc-500">
              <LoadingState label="正在推荐图表…" />
            </div>
          )}
          {chartError && (
            <div className="flex items-center gap-2 rounded-md bg-red-50 px-3 py-2 text-[13px] text-red-600">
              <AlertTriangle size={14} />
              {chartError}
            </div>
          )}
          {!chartBusy && chartSuggest && (
            <div className="space-y-2">
              {chartSuggest.suggestions.map((s) => {
                const selected = chartManifest.some((m) => (m.variant || m.template) === s.template);
                const open = suggestOpen === s.template;
                return (
                  <div
                    key={s.template}
                    className={`rounded-lg border transition-colors ${
                      open ? "border-blue-300 bg-white shadow-sm" : "border-zinc-200 bg-white hover:border-zinc-300"
                    }`}
                  >
                    {/* 折叠行：AI 徽章 + 名称 + 档位 + 重要性 + 加入按钮 */}
                    <div className="flex items-center gap-2 px-3 py-2">
                      <Sparkles size={13} className="shrink-0 text-blue-500" />
                      <span className={`rounded px-1 py-0.5 text-[9.5px] font-bold ${
                        s.level === "L1" ? "bg-emerald-50 text-emerald-700"
                          : s.level === "L2" ? "bg-blue-50 text-blue-700"
                            : "bg-violet-50 text-violet-700"
                      }`}>
                        {s.level}
                      </span>
                      {/* R4：importance 徽章（优先/按需/兜底）+ 类别 */}
                      <span
                        title="报告生成时 AI 的优先级参考：优先=必出 · 按需=内容需要才出 · 兜底=备选"
                        className={`rounded px-1 py-0.5 text-[9.5px] font-medium ${
                          s.importance === "primary"
                            ? "bg-amber-50 text-amber-700"
                            : s.importance === "secondary"
                              ? "bg-zinc-100 text-zinc-500"
                              : "bg-zinc-50 text-zinc-400"
                        }`}
                      >
                        {s.importance === "primary" ? "优先" : s.importance === "secondary" ? "按需" : "兜底"}
                      </span>
                      {s.category_label && (
                        <span className="rounded bg-zinc-50 px-1 py-0.5 text-[9.5px] text-zinc-400">{s.category_label}</span>
                      )}
                      <button
                        onClick={() => setSuggestOpen((p) => (p === s.template ? null : s.template))}
                        className="flex min-w-0 flex-1 items-center gap-2 text-left"
                      >
                        <span className="truncate text-[13px] font-medium text-zinc-800">{s.name}</span>
                        <span className="shrink-0 font-mono text-[10.5px] text-zinc-400">{s.template}</span>
                        {s.reason && (
                          <span className="hidden min-w-0 flex-1 truncate text-[11.5px] text-zinc-500 sm:block">
                            {s.reason}
                          </span>
                        )}
                      </button>
                      <button
                        onClick={() => {
                          if (selected) {
                            const item = chartManifest.find((m) => m.variant === s.template);
                            if (item) removeChart(item.id);
                          } else {
                            toggleMicroChart(s.template, s.name, s.level, [s.template]);
                          }
                        }}
                        className={`shrink-0 rounded-md px-2 py-0.5 text-[10.5px] font-medium transition-colors ${
                          selected ? "bg-blue-600 text-white hover:bg-blue-500" : "bg-zinc-100 text-zinc-600 hover:bg-zinc-200"
                        }`}
                      >
                        {selected ? "已加入 ✓" : "加入清单"}
                      </button>
                    </div>
                    {/* 展开区：模板预览（最终效果）+ 示例数据表（与图表库同款） */}
                    {open && (
                      <div className="border-t border-zinc-100 px-4 py-3">
                        <div className="space-y-3">
                          <div className="min-w-0">
                            <div className="mb-1 flex items-center gap-1.5">
                              <span className="flex items-center gap-1.5 text-[11px] font-semibold text-zinc-500">
                                <Wrench size={12} className="text-blue-500" />
                                模板预览
                              </span>
                              <span className="text-[10px] text-zinc-300">此即最终图表效果（示例数据）</span>
                            </div>
                            <ChartPreview template={s.template} height={320} />
                          </div>
                          <div className="min-w-0">
                            <div className="mb-1 text-[11px] font-semibold text-zinc-400">示例数据</div>
                            <SampleTable template={s.template} />
                          </div>
                        </div>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </section>

        {/* 微观勾选：图表库（按档位 tab 列模板，勾选「希望出现」的具体模板 = 优先建议） */}
        <section>
          <div className="mb-2 flex items-center gap-2">
            <BookOpen size={14} className="text-zinc-400" />
            <h2 className="text-[13.5px] font-semibold text-zinc-800">图表库勾选（可选微调）</h2>
            <span className="text-[11px] text-zinc-400">勾选你「希望出现」的图（优先建议）· AI 报告可按内容增减</span>
          </div>
          <ChartLibrary
            chartLevels={meta?.chart_levels ?? []}
            empty={!meta && !metaError}
            selectable
            selectedSet={new Set(chartManifest.map((m) => m.variant))}
            onSelect={(template, name, level) => {
              const cmeta = meta?.charts.find((c) => c.id === template.split("-")[0]);
              toggleMicroChart(template, name, level, cmeta?.variants || [template]);
            }}
          />
        </section>

        {/* 确认清单（chart_manifest 收敛；R4：=优先建议清单，AI 报告可增减） */}
        <section>
          <div className="mb-2 flex items-center gap-2">
            <CheckCircle2 size={14} className="text-emerald-500" />
            <h2 className="text-[13.5px] font-semibold text-zinc-800">图表构成偏好清单</h2>
            <span className="text-[11px] text-zinc-400">（{chartManifest.length} 张 · 变体/配色/排序可调 · 作为报告图表构成建议，AI 可按内容增减）</span>
          </div>
          <ChartManifest
            manifest={chartManifest}
            onRemove={removeChart}
            onMove={moveChart}
            onVariantChange={changeVariant}
            onColorChange={changeColor}
          />
        </section>

        {/* 下一步（AI 撰写报告）——至少 1 张图 */}
        <div className="rounded-lg border border-zinc-200 bg-white px-4 py-3">
          <div className="flex items-center justify-between gap-3">
            <p className="text-[12px] text-zinc-500">
              已确认 {chartManifest.length} 张图
              <span className="ml-2 text-[11.5px] text-zinc-400">
                {chartManifest.length > 0 ? "清单已收敛 → 进入 AI 撰写报告（执行+报告）" : "至少选择 1 张图才能继续"}
              </span>
            </p>
            <button
              onClick={enterStep6}
              disabled={chartManifest.length === 0}
              className={`shrink-0 rounded-lg px-5 py-2 text-[13px] font-medium transition-colors ${
                chartManifest.length > 0 ? "bg-zinc-900 text-white hover:bg-zinc-700" : "cursor-not-allowed bg-zinc-100 text-zinc-400"
              }`}
            >
              下一步（AI 撰写报告）
            </button>
          </div>
        </div>
      </div>
    </div>
  );

  // ---------- 步骤 3：变量映射（P3） ----------
  const step3Panel = (
    <div className="min-h-0 flex-1 overflow-y-auto px-6 pt-5 pb-4">
      <div className="mx-auto max-w-4xl space-y-4">
        {/* 数据文件选择（P3 简化：取第一个已导入文件；P5 支持多文件） */}
        <div className="flex items-center gap-2">
          <Database size={14} className="text-zinc-400" />
          <span className="text-[12.5px] text-zinc-500">数据文件：</span>
          <select
            value={files[0]?.file_name || ""}
            onChange={() => { setVarmap(null); void loadVarmap(); }}
            className="max-w-72 truncate rounded-md border border-zinc-200 bg-white px-2 py-1 text-[12.5px] text-zinc-700 outline-none focus:border-blue-400"
          >
            {files.map((f) => (
              <option key={f.id} value={f.file_name}>{f.file_name}</option>
            ))}
          </select>
          <span className="text-[11.5px] text-zinc-400">AI 已按模型变量 + 文件列名预填映射，请确认或修正；统计量（均值/标准差等）自动计算</span>
        </div>

        {/* V3：数据准备（可选：清洗/合并/透视/面板化） */}
        {!varmapBusy && varmap && (
          <DataPrepPanel
            allCols={varmap.all_cols}
            sheetNames={(files[0]?.sheets || []).map((s) => s.sheet_name)}
            steps={prepSteps}
            onChangeSteps={setPrepSteps}
            result={prepResult}
            busy={prepBusy}
          />
        )}

        {/* v2.0 V2：AI 匹配状态提示（v3.6 区分「无需映射」全 output 模型） */}
        {!varmapBusy && varmap && (() => {
          // 全 output/统计量模型（无待映射 input）→ 模型自动计算，非"AI 匹配不可用"
          const needMap = (varmap.models || []).some((m) =>
            (m.variables || []).some((v) => v.direction === "input"));
          const ok = aiUsed || !needMap;
          return (
            <div className={`flex items-center gap-2 rounded-lg px-3.5 py-2.5 text-[12.5px] ${
              ok
                ? "border border-emerald-200 bg-emerald-50/50 text-emerald-700"
                : "border border-amber-200 bg-amber-50/50 text-amber-700"
            }`}>
              <Sparkles size={13} />
              {needMap
                ? (aiUsed
                    ? "AI 已匹配变量并绑定统计量（均值/标准差/样本量自动计算）；低置信项可手动调整"
                    : "AI 匹配不可用，已按列名相似度预填；统计量请手动绑定函数与来源列")
                : "模型自动计算，无需外部变量映射"}
            </div>
          );
        })()}

        {varmapBusy && (
          <div className="flex items-center gap-2 rounded-lg border border-zinc-200 bg-white px-4 py-3 text-[13px] text-zinc-500">
            <LoadingState label="AI 正在识别最契合的变量列…" />
          </div>
        )}
        {varmapError && (
          <div className="flex items-center gap-2 rounded-md bg-red-50 px-3 py-2 text-[13px] text-red-600">
            <AlertTriangle size={14} />
            {varmapError}
          </div>
        )}
        {!varmapBusy && varmap && (
          <VariableMapTable
            models={mergedVarmapModels}
            allCols={varmap.all_cols}
            periodCols={varmap.period_cols}
            periodCol={periodCol}
            onPeriodChange={setPeriodCol}
            onMappingChange={handleMappingChange}
            statBindings={statBindings}
            onStatBindingChange={handleStatBindingChange}
            aiMappings={aiMappings}
            aiStatBindings={aiStatBindings}
            derivedFormulas={derivedFormulas}
            onAddDerived={addDerived}
            onRemoveDerived={removeDerived}
            onDerivedChange={changeDerived}
            derivedBusy={derivedBusy}
            derivedResults={derivedResults}
            derivedErrors={derivedErrors}
          />
        )}

        {/* 完成条件 */}
        <div className="rounded-lg border border-zinc-200 bg-white px-4 py-3">
          <div className="flex items-center justify-between gap-3">
            <p className="text-[12px] text-zinc-500">
              {varmap ? varmap.message : "等待变量映射…"}
              <span className="ml-2 text-[11.5px] text-zinc-400">
                {varmapReady()
                  ? "所有变量已匹配或可派生 ✓"
                  : `仍有 ${trulyMissingCount} 个变量需补数据——可上传数据或勾选「允许缺失分析」`}
              </span>
            </p>
            <button
              onClick={enterStep5}
              disabled={!varmapReady()}
              className={`shrink-0 rounded-lg px-5 py-2 text-[13px] font-medium transition-colors ${
                varmapReady() ? "bg-zinc-900 text-white hover:bg-zinc-700" : "cursor-not-allowed bg-zinc-100 text-zinc-400"
              }`}
            >
              下一步（图表风格）
            </button>
          </div>
          {/* v3.5 软警告放行：真正缺失数据时，勾选「允许缺失分析」即可继续（报告会给出说明） */}
          {varmap && trulyMissingCount > 0 && !varmapReady() && (
            <label className="mt-3 flex cursor-pointer items-center gap-2 rounded-md border border-amber-200 bg-amber-50/60 px-3 py-2 text-[12px] text-amber-700">
              <input
                type="checkbox"
                checked={allowMissingAnalysis}
                onChange={(e) => setAllowMissingAnalysis(e.target.checked)}
                className="h-3.5 w-3.5 accent-amber-600"
              />
              <span>
                允许缺失分析——有 {trulyMissingCount} 个变量数据未补全，将用空值填充并在报告给出「数据补充说明」
              </span>
            </label>
          )}
        </div>
      </div>
    </div>
  );

  // ---------- 步骤 5：确定性执行（P5） ----------
  const step5Panel = (
    <div className="min-h-0 flex-1 overflow-y-auto px-6 pt-5 pb-4">
      <div className="mx-auto max-w-4xl space-y-5">
        {/* 执行中 loading */}
        {runBusy && (
          <div className="flex items-center gap-2 rounded-lg border border-zinc-200 bg-white px-4 py-4 text-[13px] text-zinc-500">
            <LoadingState label={`正在确定性执行 ${selectedModels.size} 个模型（并行计算，0 LLM）…`} />
            <span className="ml-auto text-[11px] text-zinc-400">TmpRun 快照 · 主库零污染</span>
          </div>
        )}
        {runError && (
          <div className="flex items-center gap-2 rounded-md bg-red-50 px-3 py-2 text-[13px] text-red-600">
            <AlertTriangle size={14} />
            {runError}
          </div>
        )}

        {/* 数据分析器入口（高级用户自由计算） */}
        <button
          onClick={() => setAnalyzerOpen((o) => !o)}
          className="flex w-full items-center justify-between rounded-lg border border-zinc-200 bg-white px-4 py-2.5 text-[13px] font-medium text-zinc-700 hover:border-blue-300"
        >
          <span className="flex items-center gap-2">
            <Sparkles size={14} className="text-blue-500" />
            {analyzerOpen ? "收起数据分析器" : "+ 打开数据分析器"}
          </span>
          <span className="text-[11px] font-normal text-zinc-400">自由计算 · 结果直接进报告</span>
        </button>
        {analyzerOpen && appProject && files[0] && (
          <DataAnalyzer
            projectId={appProject.id}
            fileName={files[0].file_name}
            allCols={varmap?.all_cols || []}
          />
        )}

        {/* 执行结果：模型结果摘要 */}
        {runResult && (
          <>
            <section>
              <div className="mb-2 flex items-center gap-2">
                <CheckCircle2 size={14} className="text-emerald-500" />
                <h2 className="text-[13.5px] font-semibold text-zinc-800">模型计算结果</h2>
                <span className="text-[11px] text-zinc-400">（确定性引擎 · 共 {runResult.models.length} 个模型）</span>
              </div>
              <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                {runResult.models.map((m) => (
                  <div key={m.model_id} className="rounded-lg border border-zinc-200 bg-white p-3.5">
                    <div className="flex items-center gap-2">
                      <span className="rounded bg-blue-50 px-1.5 py-0.5 text-[11px] font-bold text-blue-700">{m.code}</span>
                      <span className="text-[13px] font-semibold text-zinc-800">{m.name}</span>
                      {m.ok ? (
                        <span className="ml-auto rounded-full bg-emerald-50 px-2 py-0.5 text-[10.5px] font-medium text-emerald-600">成功</span>
                      ) : (
                        <span className="ml-auto rounded-full bg-red-50 px-2 py-0.5 text-[10.5px] font-medium text-red-600">失败</span>
                      )}
                    </div>
                    <div className="mt-2 rounded-md bg-zinc-50 px-2.5 py-2 text-[11.5px] leading-relaxed text-zinc-600">
                      <pre className="whitespace-pre-wrap font-mono text-[10.5px]">{JSON.stringify(m.summary, null, 1).slice(0, 600)}</pre>
                    </div>
                  </div>
                ))}
              </div>
            </section>

            {/* 图表渲染（run 返回的数据 → ChartRenderer） */}
            <section>
              <div className="mb-2 flex items-center gap-2">
                <ChartColumn size={14} className="text-zinc-400" />
                <h2 className="text-[13.5px] font-semibold text-zinc-800">图表（{runResult.charts.length} 张）</h2>
                <span className="text-[11px] text-zinc-400">确定性渲染 · 所见即所得</span>
              </div>
              <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
                {runResult.charts.map((ch) => (
                  <ChartRenderer
                    key={ch.chart_id || ch.variant}
                    spec={{
                      template: ch.variant,
                      title: ch.name,
                      option: {
                        data: ch.data,
                        ...(ch.color_scheme && ch.color_scheme !== "auto" ? { color_scheme: ch.color_scheme } : {}),
                      },
                      data_table: ch.data_table,
                    }}
                  />
                ))}
              </div>
            </section>

            {/* 下一步（报告） */}
            <div className="rounded-lg border border-zinc-200 bg-white px-4 py-3">
              <div className="flex items-center justify-between gap-3">
                <p className="text-[12px] text-zinc-500">
                  {runResult.models.filter((m) => m.ok).length}/{runResult.models.length} 个模型执行成功 · 图表 {runResult.charts.length} 张
                  <span className="ml-2 text-[11.5px] text-zinc-400">确定性执行完成，点击「下一步生成」由 AI 撰写报告</span>
                </p>
                <button
                  onClick={() => { setMaxReached((m) => Math.max(m, 4)); setFlowStep(4); setReportPhase("report"); if (!reportBusy) void runReport(); }}
                  disabled={reportBusy}
                  className="shrink-0 rounded-lg bg-zinc-900 px-5 py-2 text-[13px] font-medium text-white hover:bg-zinc-700 disabled:cursor-not-allowed disabled:bg-zinc-200 disabled:text-zinc-400"
                >
                  {reportBusy ? <><LoadingState label="生成中…" /></> : "下一步生成"}
                </button>
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );

  // ---------- 历史记录（第 5 步，独立页面） ----------
  const stepHistoryPanel = (
    <div className="min-h-0 flex-1 overflow-y-auto px-6 pt-5 pb-4">
      <div className="mx-auto max-w-3xl space-y-4">
        <div className="flex items-center gap-2">
          <History size={16} className="text-zinc-400" />
          <h2 className="text-[16px] font-semibold text-zinc-800">历史记录</h2>
          <span className="text-[12px] text-zinc-400">（{reportHistory.length} 份分析报告 · 点击在新标签页打开）</span>
          <button
            onClick={handleRefreshReports}
            title="刷新历史"
            className="ml-auto flex items-center gap-1 rounded-md border border-zinc-200 px-3 py-1.5 text-[12px] text-zinc-600 hover:border-blue-300 hover:text-blue-600"
          >
            <RefreshCw size={12} />刷新
          </button>
        </div>

        {reportHistory.length === 0 ? (
          <div className="rounded-lg border border-dashed border-zinc-300 p-10 text-center text-[13px] text-zinc-400">
            暂无历史报告
            <div className="mt-1.5 text-[12px] text-zinc-300">完成一次「AI 撰写报告」后，报告会出现在这里</div>
          </div>
        ) : (
          <div className="space-y-2">
            {reportHistory.map((h) => (
              <div
                key={h.id}
                className="flex items-center gap-3 rounded-lg border border-zinc-200 bg-white px-4 py-3"
              >
                <div className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-blue-50">
                  <FileText size={16} className="text-blue-500" />
                </div>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="truncate text-[13.5px] font-medium text-zinc-800">{h.filename}</span>
                    <span className="text-[11px] text-zinc-400">{new Date(h.createdAt).toLocaleString()}</span>
                  </div>
                  <p className="mt-0.5 truncate text-[12px] text-zinc-500">{h.goal}</p>
                </div>
                <div className="flex shrink-0 items-center gap-1.5">
                  <button
                    onClick={() => openReportInNewTab(h)}
                    title={`打开 ${h.filename}（新标签页）`}
                    className="flex items-center gap-1.5 rounded-md border border-zinc-200 px-3 py-1.5 text-[12px] text-zinc-600 hover:border-blue-300 hover:text-blue-600"
                  >
                    <BookOpen size={12} />打开
                  </button>
                  <button
                    onClick={() => handleDeleteReport(h.id)}
                    title="删除此报告"
                    className="flex items-center gap-1 rounded-md border border-zinc-200 px-2.5 py-1.5 text-[12px] text-zinc-500 hover:border-red-300 hover:text-red-500"
                  >
                    <Trash2 size={12} />
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );

  // ---------- 步骤 6：报告交付（P6） ----------
  const step6Panel = (
    <div className="min-h-0 flex-1 overflow-y-auto px-6 pt-5 pb-4">
      <div className="mx-auto max-w-4xl space-y-5">
        {/* AI 撰写报告中：进度条（自动触发后展示）；完成后由 reportResult 走 FileEditor 预览 */}
        {!reportResult && (
          <div className="rounded-lg border border-zinc-200 bg-white px-6 py-10">
            {reportBusy ? (
              <div className="flex flex-col items-center gap-4">
                <LoadingState label="AI 正在撰写报告…" />
                <p className="text-[12px] text-zinc-400">
                  正在落盘图表并让 AI 撰写含公式与图表引用的 Markdown 报告，请稍候
                </p>
              </div>
            ) : (
              <div className="flex items-center gap-3">
                <AlertTriangle size={14} className="text-amber-500" />
                <p className="text-[12.5px] text-zinc-500">未自动生成报告，请点击返回"① 确定性执行"后点「下一步生成」</p>
              </div>
            )}
            {reportError && (
              <div className="mt-3 flex items-center gap-2 rounded-md bg-red-50 px-3 py-2 text-[12.5px] text-red-600">
                <AlertTriangle size={14} />{reportError}
              </div>
            )}
          </div>
        )}

        {/* 已落盘图表清单 */}
        {savedCharts.length > 0 && (
          <section>
            <div className="mb-2 flex items-center gap-2">
              <FolderOpen size={14} className="text-zinc-400" />
              <h2 className="text-[13.5px] font-semibold text-zinc-800">已落盘图表（{savedCharts.length}）</h2>
              <span className="text-[11px] text-zinc-400">assets/ 目录 · 相对路径已写入报告</span>
            </div>
            <div className="flex flex-wrap gap-2">
              {savedCharts.map((f) => (
                <a
                  key={f.filename}
                  href={finmodAssetUrl(runResult?.runId || runResult?.run_id || "", f.filename)}
                  target="_blank"
                  rel="noreferrer"
                  className="flex items-center gap-1.5 rounded-md border border-zinc-200 bg-white px-2.5 py-1.5 text-[11.5px] text-zinc-600 transition-colors hover:border-blue-300 hover:text-blue-600"
                >
                  {f.format === "svg" ? <ChartColumn size={12} className="text-blue-500" /> : <BookOpen size={12} className="text-amber-500" />}
                  {f.filename}
                </a>
              ))}
            </div>
          </section>
        )}

        {/* 报告预览 = 内嵌 FileEditor（按 project_id + rel_path 打开报告 md，复用预览组件） */}
        {reportResult && appProject && (
          <>
            <section className="rounded-lg border border-zinc-200 bg-white">
              <div className="flex items-center gap-2 border-b border-zinc-100 px-4 py-2.5">
                <FileSpreadsheet size={14} className="text-blue-600" />
                <span className="text-[13px] font-semibold text-zinc-800">报告预览</span>
                {reportResult.used_llm ? (
                  <span className="rounded-full bg-emerald-50 px-2 py-0.5 text-[10.5px] font-medium text-emerald-600">AI 报告</span>
                ) : (
                  <span className="rounded-full bg-amber-50 px-2 py-0.5 text-[10.5px] font-medium text-amber-600">确定性降级</span>
                )}
                <span className="ml-auto text-[11px] text-zinc-400">{reportResult.filename}</span>
              </div>
              {/* 内嵌 FileEditor：按项目路径加载报告 md（渲染 + 编辑 + 保存 + 导出 Word/PDF） */}
              <FileEditor
                key={reportResult.rel_path}
                projectId={appProject.id}
                filePath={reportResult.rel_path}
                onClose={() => {}}
                onSaved={() => {}}
                embedded
                resolveImageUrl={(path) => rawFileUrl(appProject.id, path)}
              />
            </section>

            {/* 一键重跑 */}
            <div className="flex items-center justify-between rounded-lg border border-zinc-200 bg-white px-4 py-3">
              <p className="text-[12px] text-zinc-500">
                报告已生成：<span className="font-medium text-zinc-700">{reportResult.filename}</span>
                <span className="ml-2 text-[11.5px] text-zinc-400">（{reportResult.rel_path}）</span>
              </p>
              <div className="flex items-center gap-2">
                <button
                  onClick={() => { setFlowStep(3); }}
                  className="flex items-center gap-1.5 rounded-md border border-zinc-200 px-3 py-1.5 text-[12px] text-zinc-600 hover:border-blue-300 hover:text-blue-600"
                >
                  <RotateCcw size={12} />调整后重跑
                </button>
                <button
                  onClick={() => { setFlowStep(1); setMaxReached(1); setReportResult(null); setSavedCharts([]); setGoal(""); setMacroPhase("direction"); setReportPhase("execute"); }}
                  className="rounded-md bg-zinc-900 px-4 py-1.5 text-[12px] font-medium text-white hover:bg-zinc-700"
                >
                  新分析
                </button>
              </div>
            </div>
          </>
        )}

        {/* 历史运行：已由四步导航下方「历史报告」区接管（点击新标签页预览，不触发重新生成） */}
      </div>
    </div>
  );

  return (
    <div className="relative flex min-w-0 flex-1 flex-col bg-zinc-50">
      {appHeader}
      <div className="flex min-h-0 min-w-0 flex-1">
        {stepNav}
        <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden">
          {/* R3：步骤 2/步骤 4 内部子阶段分段条（不改变主状态机） */}
          {flowStep === 2 && (
            <div className="flex items-center gap-1 border-b border-zinc-200 bg-white px-5 pt-2.5 pb-0">
              {([
                { id: "direction", label: "① 建模方向" },
                { id: "varmap", label: "② 变量映射" },
              ] as const).map((t) => (
                <button
                  key={t.id}
                  onClick={() => { setMacroPhase(t.id); if (t.id === "varmap") void loadVarmap(); }}
                  className={`rounded-t-lg border-b-2 px-4 py-2 text-[12.5px] font-medium transition-colors ${
                    macroPhase === t.id
                      ? "border-blue-500 text-blue-600"
                      : "border-transparent text-zinc-500 hover:text-zinc-700"
                  }`}
                >
                  {t.label}
                  <span className="ml-1.5 text-[10.5px] text-zinc-400">
                    {t.id === "varmap" ? `（${selectedModels.size} 模型）` : ""}
                  </span>
                </button>
              ))}
            </div>
          )}
          {flowStep === 4 && (
            <div className="flex items-center gap-1 border-b border-zinc-200 bg-white px-5 pt-2.5 pb-0">
              {([
                { id: "execute", label: "① 确定性执行" },
                { id: "report", label: "② AI 撰写报告" },
              ] as const).map((t) => (
                <button
                  key={t.id}
                  onClick={() => {
                    setReportPhase(t.id);
                    // 仅在无执行结果时点击「执行」才触发 run（已有结果则直接查看，不重跑）
                    if (t.id === "execute" && !runResult && !runBusy) void enterStep6();
                  }}
                  className={`rounded-t-lg border-b-2 px-4 py-2 text-[12.5px] font-medium transition-colors ${
                    reportPhase === t.id
                      ? "border-blue-500 text-blue-600"
                      : "border-transparent text-zinc-500 hover:text-zinc-700"
                  }`}
                >
                  {t.label}
                </button>
              ))}
            </div>
          )}
          {flowStep === 1 && (appProject ? step1Panel : (
            <div className="flex flex-1 items-center justify-center gap-2 text-[13px] text-zinc-400">
              {appError ? <span className="text-red-500">{appError}</span> : <LoadingState label="正在初始化应用数据区…" />}
            </div>
          ))}
          {/* R3 4步化：步骤 2 = 建模方向 + 变量映射（子阶段切换）；步骤 4 = 执行 + 报告（子阶段切换） */}
          {flowStep === 2 && (macroPhase === "direction" ? step2Panel : step3Panel)}
          {flowStep === 3 && step4Panel}
          {flowStep === 4 && (reportPhase === "execute" ? step5Panel : step6Panel)}
          {flowStep === 5 && stepHistoryPanel}
        </div>
      </div>

      {/* 项目数据库抽屉（上传/表头锚定/索引查看/删除/刷新，复用 AppDataPanel） */}
      {(dbOpen || dbClosing) && appProject && (
        <AppDataPanel
          projectId={appProject.id}
          closing={dbClosing}
          onClose={requestCloseDb}
          onImported={() => setDbTick((t) => t + 1)}
        />
      )}
    </div>
  );
}

/** 示例数据表（v6.8：AI 推荐卡展开区用，与图表库 SampleDataTable 同源 sampleDataToRows） */
function SampleTable({ template }: { template: string }) {
  const { columns, rows } = useMemo(() => sampleDataToRows(template), [template]);
  return (
    <div className="max-h-60 overflow-auto rounded-md border border-zinc-200 bg-white">
      <table className="w-full border-collapse text-[12px]">
        <thead className="sticky top-0 bg-zinc-50">
          <tr>
            {columns.map((c) => (
              <th key={c} className="border-b border-zinc-200 px-2 py-1 text-left font-medium text-zinc-500">
                {c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} className={i % 2 ? "bg-zinc-50/60" : ""}>
              {r.map((v, j) => (
                <td key={j} className="border-b border-zinc-100 px-2 py-1 text-zinc-600 last:border-b-0">
                  {v}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
