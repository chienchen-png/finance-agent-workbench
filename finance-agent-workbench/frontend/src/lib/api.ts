/** api.ts — 统一后端 API 封装。
 *
 * 阶段 2：新前端对接现有 Flask 后端（函数与变量总文档 二、routes/）。
 * 所有响应遵循 { success, data } 包裹；本模块统一请求/错误处理。
 */

const BASE = "";

export async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const resp = await fetch(BASE + path, {
    headers: { "Content-Type": "application/json" },
    cache: "no-store", // 阶段 7.9.2：禁用 HTTP 缓存，操作后刷新必拿最新数据
    ...options,
  });
  const json = await resp.json().catch(() => ({}));
  if (!resp.ok || json.success === false) {
    const err = new Error(json.error || json.message || `HTTP ${resp.status}`);
    (err as Error & { status?: number }).status = resp.status; // 供调用方识别 404 等
    throw err;
  }
  return json.data as T;
}

// =====================================================================
// 项目 /api/projects
// =====================================================================

export interface Project {
  id: string;
  name: string;
  description: string | null;
  work_dir: string;
  year: number | null;
  quarter: number | null;
  default_agent: string | null;
  default_model: string | null;
  work_mode?: "manual" | "auto";
  created_at: string;
  updated_at: string;
}

export function listProjects(includeHidden = false): Promise<Project[]> {
  // includeHidden=true：应用内部（ensureAppProject）显式查找/复用 __app_ 隐藏项目
  return request<Project[]>(`/api/projects${includeHidden ? "?include_hidden=1" : ""}`);
}

export function createProject(payload: {
  name: string;
  description?: string;
  work_dir?: string;
  default_model?: string;
}): Promise<Project> {
  return request<Project>("/api/projects", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function updateProject(
  projectId: string,
  payload: {
    name?: string;
    description?: string;
    year?: number | null;
    quarter?: number | null;
    default_agent?: string | null;
    default_model?: string | null;
    work_mode?: "manual" | "auto";  // 阶段 G4：工作模式持久化
  },
): Promise<Project> {
  return request<Project>(`/api/projects/${projectId}`, {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}

export function deleteProject(projectId: string): Promise<unknown> {
  return request<unknown>(`/api/projects/${projectId}`, {
    method: "DELETE",
  });
}

export function duplicateProject(projectId: string): Promise<Project> {
  return request<Project>(`/api/projects/${projectId}/duplicate`, {
    method: "POST",
  });
}

// =====================================================================
// 模型/Agent 选项 /api/options
// =====================================================================

export interface ModelOption {
  id: string;
  provider_id: string;
  name: string;
  type: string;
  capabilities: string;
  context_window: number;
  is_default: number;
  status: string;
  icon?: string;
}

export interface AgentOption {
  id: string;
  name: string;
  version: string;
  description: string;
  enabled: number;
}

export interface ToolEntry {
  name: string;
  description: string;
}

export interface ToolCategory {
  category: string;
  tools: ToolEntry[];
}

export interface AgentDetail {
  id: string;
  name: string;
  version: string;
  role: string;
  description: string;
  workflow?: Record<string, unknown>;
  context_policy?: Record<string, unknown>;
}

export function fetchAgent(agentId: string): Promise<{ agent: AgentDetail }> {
  return request<{ agent: AgentDetail }>(`/api/agents/${agentId}`);
}

export function fetchAgentTools(agentId: string): Promise<{ agent_id: string; catalog: ToolCategory[] }> {
  return request<{ agent_id: string; catalog: ToolCategory[] }>(`/api/agents/${agentId}/tools`);
}

// =====================================================================
// Skill 目录 /api/skills（2026-08-19：AI 功能配置 → Skill 配置，静态展示）
// =====================================================================

export interface SkillSummary {
  name: string;
  description: string;
  trigger_words: string[];
  step_count: number;
  path: string;
}

export interface SkillBranch {
  key: string;
  title: string;
  summary: string;
}

export interface SkillStep {
  n: number;
  title: string;
  summary: string;
  branch_point: boolean;
  branches: SkillBranch[];
}

export interface SkillModelCategory {
  category: string;
  name: string;
  count: number;
  items: string[];
}

export interface SkillCapabilities {
  models: SkillModelCategory[];
  stats: string[];
  charts: string[];
}

export interface SkillDetail {
  name: string;
  description: string;
  user_invocable: boolean;
  trigger_words: string[];
  purpose: string;
  steps: SkillStep[];
  constraints: string;
  capabilities: SkillCapabilities;
  content: string;
}

export function fetchSkills(): Promise<{ skills: SkillSummary[] }> {
  return request<{ skills: SkillSummary[] }>("/api/skills");
}

export function fetchSkillDetail(name: string): Promise<SkillDetail> {
  return request<SkillDetail>(`/api/skills/${encodeURIComponent(name)}`);
}

export interface Options {
  models: ModelOption[];
  agents: AgentOption[];
}

export function fetchOptions(): Promise<Options> {
  return request<Options>("/api/options");
}

// =====================================================================
// 目录树浏览 /api/browse（阶段 7.9.6 方案 B：自研目录选择器）
// =====================================================================

export interface BrowseTreeResult {
  path: string;
  name: string;
  parent: string | null;
  entries: { name: string; path: string; type: "directory" | "file" }[];
}

/** 服务端文件夹选择（阶段 7.9.7.3 恢复）：后端弹 Windows 原生对话框返回绝对路径。
 * 现代 Chrome(120+) 已移除 File.path，webkitdirectory 拿不到绝对路径，必须走服务端。 */
export function browseFolder(): Promise<{ path: string }> {
  return request<{ path: string }>("/api/browse-folder", { method: "POST" });
}

/** 列出磁盘目录的子目录（供目录树浏览备用）。 */
export function browseDirectory(path?: string): Promise<BrowseTreeResult> {
  const q = path ? `?path=${encodeURIComponent(path)}` : "";
  return request<BrowseTreeResult>(`/api/browse/tree${q}`);
}

/** 驱动器 + 常用位置（阶段 7.9.8：Windows 风格选择器侧栏数据）。 */
export interface BrowseDrivesResult {
  drives: { name: string; path: string; type: string }[];
  locations: { name: string; path: string; type: string }[];
  /** 初始目录（注册表真实桌面，兼容 OneDrive 重定向） */
  start?: string;
}
export function browseDrives(): Promise<BrowseDrivesResult> {
  return request<BrowseDrivesResult>("/api/browse/drives");
}

// =====================================================================
// 模型供应商/模型管理 /api/models
// =====================================================================

export interface Provider {
  id: string;
  name: string;
  api_url: string;
  api_key: string;
  api_key_url: string;
  description: string | null;
  status: string;
  icon?: string;
  created_at?: string;
}

export interface ModelRecord {
  id: string;
  provider_id: string;
  name: string;
  type: string;
  capabilities: string;
  context_window: number;
  is_default: number;
  status: string;
  icon?: string;
}

export function listProviders(): Promise<Provider[]> {
  return request<Provider[]>("/api/models/providers");
}

export function createProvider(payload: Partial<Provider>): Promise<Provider> {
  return request<Provider>("/api/models/providers", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function updateProvider(providerId: string, payload: Partial<Provider>): Promise<Provider> {
  return request<Provider>(`/api/models/providers/${providerId}`, {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}

export function deleteProvider(providerId: string): Promise<unknown> {
  return request<unknown>(`/api/models/providers/${providerId}`, {
    method: "DELETE",
  });
}

export function createModel(providerId: string, payload: Partial<ModelRecord>): Promise<ModelRecord> {
  return request<ModelRecord>(`/api/models/providers/${providerId}/models`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function updateModel(modelId: string, payload: Partial<ModelRecord>): Promise<ModelRecord> {
  return request<ModelRecord>(`/api/models/${modelId}`, {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}

export function deleteModel(modelId: string): Promise<unknown> {
  return request<unknown>(`/api/models/${modelId}`, {
    method: "DELETE",
  });
}

export function testModelConnection(payload: { api_url: string; api_key: string; model: string }): Promise<{ message: string }> {
  return request<{ message: string }>("/api/models/test", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

// =====================================================================
// 文件 /api/files
// =====================================================================

export interface FileEntry {
  name: string;
  path: string;
  size: number | null;
  type: "directory" | "file";
  updated_at?: number;
}

export interface FileTreeResponse {
  path: string;
  entries: FileEntry[];
}

export function fetchFileTree(projectId: string, path = ""): Promise<FileTreeResponse> {
  return request<FileTreeResponse>(
    `/api/files/tree?project_id=${encodeURIComponent(projectId)}&path=${encodeURIComponent(path)}`,
  );
}

export interface FileEntryFull {
  name: string;
  path: string;
  size: number | null;
  type: "directory" | "file";
  updated_at?: number;
}

export function readFileContent(projectId: string, path: string): Promise<{ file: FileEntryFull; content: string }> {
  return request<{ file: FileEntryFull; content: string }>(
    `/api/files/read?project_id=${encodeURIComponent(projectId)}&path=${encodeURIComponent(path)}`,
  );
}

/** D3：文件元信息（含 viewer_type / can_edit / can_open_external，双击分发依据） */
export interface FileMeta extends FileEntryFull {
  viewer_type: string;
  can_edit: boolean;
  can_open_external: boolean;
}

export function fileMeta(projectId: string, path: string): Promise<{ file: FileMeta }> {
  return request<{ file: FileMeta }>(
    `/api/files/meta?project_id=${encodeURIComponent(projectId)}&path=${encodeURIComponent(path)}`,
  );
}

/** D3：调本机程序打开文件（office 双击直接本地打开） */
export function openExternalFile(
  projectId: string,
  path: string,
): Promise<{ file: FileMeta; opened: boolean; message: string }> {
  return request<{ file: FileMeta; opened: boolean; message: string }>("/api/files/open-external", {
    method: "POST",
    body: JSON.stringify({ project_id: projectId, path }),
  });
}

/** D3：raw 二进制流 URL（pdf/图片浏览器预览） */
export function rawFileUrl(projectId: string, path: string, binary = true): string {
  return `/api/files/raw?project_id=${encodeURIComponent(projectId)}&path=${encodeURIComponent(path)}${binary ? "&binary=1" : ""}`;
}

/** D4：Markdown → Word 导出（后端 Pandoc）。content 传入则优先（未保存内容）。 */
export async function exportDocxFile(
  projectId: string,
  path: string,
  content?: string,
): Promise<Blob> {
  const resp = await fetch("/api/files/export-docx", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ project_id: projectId, path, content }),
  });
  if (!resp.ok) {
    let msg = `导出失败（HTTP ${resp.status}）`;
    try {
      const j = await resp.json();
      if (j && typeof j.message === "string") msg = j.message;
    } catch { /* 非 JSON 响应保留默认信息 */ }
    throw new Error(msg);
  }
  return await resp.blob();
}

/** D4：触发浏览器下载 Blob */
export function downloadBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

export function createFileItem(projectId: string, path: string, type: "file" | "directory", content = ""): Promise<FileEntryFull> {
  return request<FileEntryFull>("/api/files/create", {
    method: "POST",
    body: JSON.stringify({ project_id: projectId, path, type, content }),
  });
}

export function writeFileContent(projectId: string, path: string, content: string): Promise<unknown> {
  return request<unknown>("/api/files/write", {
    method: "PUT",
    body: JSON.stringify({ project_id: projectId, path, content }),
  });
}

export function renameFileItem(projectId: string, path: string, newPath: string): Promise<unknown> {
  return request<unknown>("/api/files/rename", {
    method: "PUT",
    body: JSON.stringify({ project_id: projectId, path, new_path: newPath }),
  });
}

export function copyFileItem(projectId: string, source: string, destination: string): Promise<unknown> {
  return request<unknown>("/api/files/copy", {
    method: "POST",
    body: JSON.stringify({ project_id: projectId, path: source, target_path: destination }),
  });
}

export function deleteFileItem(projectId: string, path: string): Promise<unknown> {
  return request<unknown>("/api/files", {
    method: "DELETE",
    body: JSON.stringify({ project_id: projectId, path }),
  });
}

/** 上传单个文件（multipart）。path=目标目录；relative_path=可选相对子路径（夹内上传用）。 */
export function uploadFile(
  projectId: string,
  path: string,
  file: File,
  relativePath?: string,
): Promise<unknown> {
  const form = new FormData();
  form.append("project_id", projectId);
  form.append("path", path);
  form.append("file", file);
  if (relativePath) form.append("relative_path", relativePath);
  return request<unknown>("/api/files/upload", {
    method: "POST",
    body: form,
    headers: {}, // FormData 自带 multipart 边界，勿覆盖 Content-Type
  });
}

// =====================================================================
// 项目数据 /api/project-data
// =====================================================================

export interface DataFileRecord {
  id: string;
  project_id: string;
  source_path: string;
  file_name: string;
  file_hash: string;
  format: string;
  sheet_count: number;
  total_rows: number;
  status: string;
  error_message: string | null;
  meta_json: string | null;
  created_at: string;
  updated_at: string;
  sheets?: DataSheet[];
  meta?: {
    file_size?: number;
    formulas_materialized?: boolean;
    layouts?: Record<string, SheetLayout>;
    uncorrected_cols?: Record<string, number[]>;
    col_audit?: string;
  };
  // Phase 17 P5：每文件变更计数（列表角标）
  changes_count?: { total: number; update: number; insert: number; delete: number };
}

export interface DataSheet {
  file_id: string;
  sheet_name: string;
  sheet_index: number;
  row_count: number;
  col_count: number;
  headers: {
    name: string;
    type: string;
    non_null_rate?: number;
    samples?: string[];
    excel_col?: string;  // Phase 17 P6：Excel 列字母（A/B/C…）
  }[];
}

// Phase 17 P6：表头识别布局（index 接口透传 meta.layouts）
export interface SheetLayout {
  header_row?: number;
  excel_header_row?: number;  // 1-based 表头行（直接显示）
  data_start_row?: number;    // 1-based 数据起始行
  confidence?: number;
  anchored_by?: "auto" | "user";
}

// Phase 17 P5：字段级修改日志（写回剧本）
export interface ChangeSummary {
  total: number;
  update: number;
  insert: number;
  delete: number;
}

export interface ChangeLogItem {
  id: number;
  file_id: string;
  sheet_name: string;
  row_index: number;      // 数据表 id
  col_index: number | null;
  col_name: string | null;  // 字段名（日志固化）
  key_value: string | null; // 行定位键（主键列值，日志固化）
  old_value: string | null;
  new_value: string | null;
  op_type: "update" | "insert" | "delete";
  created_at: string;
  excel_row: number | null; // Excel 物理行（header_row+1+序号）
  excel_col: string | null; // Excel 列字母（A/B/C…）
}

export function listDataFiles(projectId: string): Promise<{ files: DataFileRecord[] }> {
  return request<{ files: DataFileRecord[] }>(
    `/api/project-data/list?project_id=${encodeURIComponent(projectId)}`,
  );
}

export function importDataFile(
  projectId: string,
  path: string,
  opts: { alwaysAnchor?: boolean } = {},
): Promise<{ import_id: string }> {
  return request<{ import_id: string }>("/api/project-data/import", {
    method: "POST",
    body: JSON.stringify({
      project_id: projectId,
      path,
      always_anchor: opts.alwaysAnchor ?? false,
    }),
  });
}

export function importStatus(importId: string): Promise<Record<string, unknown>> {
  return request<Record<string, unknown>>(
    `/api/project-data/import/status?import_id=${encodeURIComponent(importId)}`,
  );
}

/** 提交表头行锚点后继续导入（Phase 14E：低置信度需人工确认表头行）。
 * anchors: {sheet_name: 0-based 表头行}——前端弹窗用 1-based UI，提交前 -1。 */
export function importAnchor(
  importId: string,
  anchors: Record<string, number>,
): Promise<{ import_id: string; resumed: boolean }> {
  return request<{ import_id: string; resumed: boolean }>("/api/project-data/import/anchor", {
    method: "POST",
    body: JSON.stringify({ import_id: importId, anchors }),
  });
}

export function dataIndex(fileId: string): Promise<{ file: DataFileRecord; sheets: DataSheet[]; changes: unknown[] }> {
  return request<{ file: DataFileRecord; sheets: DataSheet[]; changes: unknown[] }>(
    `/api/project-data/${encodeURIComponent(fileId)}/index`,
  );
}

export function dataChanges(
  fileId: string,
  opts: { limit?: number; offset?: number; sheet?: string; op?: string } = {},
): Promise<{ changes: ChangeLogItem[]; summary: ChangeSummary; has_more: boolean }> {
  const p = new URLSearchParams({ limit: String(opts.limit ?? 200) });
  if (opts.offset) p.set("offset", String(opts.offset));
  if (opts.sheet) p.set("sheet", opts.sheet);
  if (opts.op) p.set("op", opts.op);
  return request<{ changes: ChangeLogItem[]; summary: ChangeSummary; has_more: boolean }>(
    `/api/project-data/${encodeURIComponent(fileId)}/changes?${p.toString()}`,
  );
}

export function exportData(
  projectId: string,
  file: string,
  mode = "precise",
): Promise<{ export_id: string }> {
  return request<{ export_id: string }>("/api/project-data/export", {
    method: "POST",
    body: JSON.stringify({ project_id: projectId, file, mode }),
  });
}

// Phase 17 P7：写回任务进度轮询（贴边框进度条）
export interface ExportStatus {
  status: "running" | "done" | "failed";
  progress: number;
  message: string;
  written_cells: number;
  error: string | null;
  error_type?: string | null;  // Phase 17 P9：file_locked 等结构化错误类型
}

export function exportStatus(exportId: string): Promise<ExportStatus> {
  return request<ExportStatus>(
    `/api/project-data/export/status?export_id=${encodeURIComponent(exportId)}`,
  );
}

export function deleteDataFile(fileId: string): Promise<unknown> {
  return request<unknown>(`/api/project-data/${encodeURIComponent(fileId)}`, {
    method: "DELETE",
  });
}

// =====================================================================
// 工作台 /api/workspace
// =====================================================================

export interface StartRunResult {
  run_id: string;
  status: string;
}

export interface StartRunPayload {
  prompt: string;
  project_id: string;
  agent: string;
  model: string;
  engine?: "smol" | "legacy";
  work_mode?: "manual" | "auto";  // 阶段 G4：会话级临时切换（与模型切换同构）
  context_files?: string[];
}

export function startRun(payload: StartRunPayload): Promise<StartRunResult> {
  return request<StartRunResult>("/api/workspace/run", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function stopRun(runId: string): Promise<void> {
  return request<void>("/api/workspace/stop", {
    method: "POST",
    body: JSON.stringify({ run_id: runId }),
  });
}

// =====================================================================
// 集成应用 /api/apps（2026-08-20：混合模式——确定性核对 + 一次 LLM 报告）
// =====================================================================

export interface ReconVerifyParams {
  baseFile: string;
  detailFile: string;
  matchKeys: { k1: string; k2: string; k3: string; k2On: boolean; k3On: boolean };
  variables: string[];
  /** 依据表金额列（与 variables 第一项对应） */
  baseAmountCol: string;
  tolerance: number;
  unmatchedAction: string;
  autoFix: boolean;
}

/** 差异行（与页面 ReconDiff 兼容：字段宽松，含 index signature） */
export interface ReconDiffData {
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

export interface ReconDataPayload {
  summary: { ok: number; a1: number; a2: number; b: number; c: number };
  diffs: ReconDiffData[];
}

/** 待审计项（多轮审计循环：用户逐条决策 → 下一轮核对） */
export interface ReconAuditItem {
  key: string;
  /** base=总表独有 / detail=分表独有 / ambiguous=一对多模糊 */
  side: "base" | "detail" | "ambiguous" | string;
  reason: string;
  decision: string | null;
  candidates: number;
}

export interface ReconVerifyResult {
  runId: string;
  report: string;
  reconData: ReconDataPayload;
  auditItems: ReconAuditItem[];
  raw: { summary: Record<string, unknown>; amount_col: unknown; match_keys: unknown };
}

/** 校验（确定性核对 + 一次 LLM 报告；差异表直出工具 JSON） */
export function reconVerify(
  projectId: string,
  modelId: string,
  params: ReconVerifyParams,
): Promise<ReconVerifyResult> {
  return request<ReconVerifyResult>("/api/apps/recon/verify", {
    method: "POST",
    body: JSON.stringify({ project_id: projectId, model_id: modelId, params }),
  });
}

/** 审计决策（多轮核对闭环：提交决策 → 下一轮核对） */
export interface ReconAuditDecision {
  key: string;
  side: string;
  decision: string;
}

export interface ReconAuditResult {
  runId: string;
  reconData: ReconDataPayload;
  auditItems: ReconAuditItem[];
  raw: { summary: Record<string, unknown> };
  /** 本轮实际应用的决策数（不含挂起） */
  applied: number;
  /** 剩余待审计项数 */
  remaining: number;
}

export function reconAudit(
  runId: string,
  projectId: string,
  params: ReconVerifyParams,
  decisions: ReconAuditDecision[],
): Promise<ReconAuditResult> {
  return request<ReconAuditResult>("/api/apps/recon/audit", {
    method: "POST",
    body: JSON.stringify({ run_id: runId, project_id: projectId, params, decisions }),
  });
}

/** 确定性写回结果（2026-08-21：写回不再依赖 LLM Agent 编排） */
export interface ReconWritebackResult {
  written: number;
  skipped: number;
  export: { success: boolean; message?: string; error?: string; written_cells?: number };
  report: string;
}

export function reconWriteback(
  runId: string,
  projectId: string,
  params: ReconVerifyParams,
  diffs: ReconDiffData[],
): Promise<ReconWritebackResult> {
  return request<ReconWritebackResult>("/api/apps/recon/writeback", {
    method: "POST",
    body: JSON.stringify({ run_id: runId, project_id: projectId, params, diffs }),
  });
}

export function runStatus(runId: string): Promise<{ status: string }> {
  return request<{ status: string }>(
    `/api/workspace/status?run_id=${encodeURIComponent(runId)}`,
  );
}

// 历史恢复
export interface RunHistory {
  runs: {
    run_id: string;
    title: string;
    status: string;
    user_prompt: string;
    assistant_text: string;
    reasoning: string | null;
    tool_cards: unknown[];
    plan: unknown;
    created_at: string;
  }[];
}

export function fetchHistory(projectId: string): Promise<RunHistory> {
  return request<RunHistory>(
    `/api/workspace/history?project_id=${encodeURIComponent(projectId)}`,
  );
}

// =====================================================================
// 应用二「财务建模与分析」— finmod 元数据层（P1，2026-08-21）
// =====================================================================
// 数据源：financial-modeling skill references（.github/skills/financial-modeling/references）
// 端点：GET /api/apps/finmod/meta | /models/<id> | /charts/<id>

/** 模型元信息（meta 目录项） */
export interface FinmodModelMeta {
  /** 文件名 stem（如 a1-three-statement） */
  id: string;
  /** 编号（如 A1） */
  code: string;
  name: string;
  /** 分类键（A-G） */
  category: string;
  category_label: string;
}

/** 图表模板元信息（meta 目录项） */
export interface FinmodChartMeta {
  /** 模板 id（如 line） */
  id: string;
  name: string;
  /** 复杂度档位：L1/L2/L3 */
  level: "L1" | "L2" | "L3" | string;
  level_label: string;
  /** 可用变体名列表（如 line-smooth/line-area…） */
  variants: string[];
}

/** 模型分类分组（meta 的 model_categories 项） */
export interface FinmodModelGroup {
  key: string;
  label: string;
  models: FinmodModelMeta[];
}

/** 图表档位分组（meta 的 chart_levels 项） */
export interface FinmodChartGroup {
  key: string;
  label: string;
  charts: FinmodChartMeta[];
}

/** GET /api/apps/finmod/meta 响应 */
export interface FinmodMetaData {
  model_categories: FinmodModelGroup[];
  models: FinmodModelMeta[];
  chart_levels: FinmodChartGroup[];
  charts: FinmodChartMeta[];
  counts: { models: number; charts: number };
}

/** markdown 分节（详情通用） */
export interface FinmodSection {
  heading: string;
  content: string;
}

/** 模型详情（GET /api/apps/finmod/models/<id>） */
export interface FinmodModelDetail {
  id: string;
  code: string;
  name: string;
  category: string;
  category_label: string;
  /** 目的（「目的/用途」节） */
  purpose: string;
  /** 关键公式（$$...$$ 块，KaTeX 渲染） */
  formulas: string[];
  /** 变量含义表（[{变量, 含义, 单位}]） */
  variables: Record<string, string>[];
  /** 适用场景列表 */
  scenarios: string[];
  /** 注意事项列表 */
  notes: string[];
  /** 完整分节（保序，供逐节渲染） */
  sections: FinmodSection[];
  /** 原始 markdown 全文 */
  raw: string;
}

/** 图表详情（GET /api/apps/finmod/charts/<id>） */
export interface FinmodChartDetail {
  id: string;
  name: string;
  level: string;
  level_label: string;
  purpose: string;
  scenarios: string[];
  /** 数据结构示例（json 代码块） */
  data_structure: string;
  selection: string[];
  /** 变体清单（含主变体 + 别名 + 图表名 + 用途） */
  variants: { variant: string; aliases: string[]; chart: string; usage: string }[];
  notes: string[];
  sections: FinmodSection[];
  raw: string;
}

export function finmodMeta(): Promise<FinmodMetaData> {
  return request<FinmodMetaData>("/api/apps/finmod/meta");
}

export function finmodModelDetail(modelId: string): Promise<FinmodModelDetail> {
  return request<FinmodModelDetail>(
    `/api/apps/finmod/models/${encodeURIComponent(modelId)}`,
  );
}

export function finmodChartDetail(chartId: string): Promise<FinmodChartDetail> {
  return request<FinmodChartDetail>(
    `/api/apps/finmod/charts/${encodeURIComponent(chartId)}`,
  );
}

// =====================================================================
// 应用二 finmod — P2 引导引擎（2026-08-21）
// =====================================================================
// 建议型引导（需求文档 §2.1/§四 步骤 2）：诉求 + 列名索引 → LLM 建议 JSON。

/** 引导方向建议（模式 B：模型推荐卡） */
export interface FinmodDirection {
  model_id: string;
  code: string;
  name: string;
  /** AI 推荐理由（白话） */
  reason: string;
  /** 教学文案（白话讲解 + KaTeX 公式，Markdown） */
  teaching: string;
  /** 推荐图表模板名（如 radar/tornado/line） */
  recommended_charts: string[];
  /** 数据完备性（v3.2：步骤 2 建模方向确认时用统一精确口径评估，含可派生/真缺拆分） */
  var_coverage?: {
    /** 已匹配 input 变量数 */
    matched: number;
    /** 真正未匹配且不可派生的 input 变量数（数据不足） */
    missing: number;
    /** 统计量变量数（自动计算，不算缺失） */
    statistic: number;
    /** input 变量总数（不含 statistic/output） */
    input_vars: number;
    /** 真正缺失、需补数据的变量名列表 */
    missing_names: string[];
    /** 是否就绪（无 truly_missing 即 True，可放行建模） */
    ready: boolean;
    /** 缺失但可由已有数值列派生的变量名列表 */
    derivable: string[];
    /** 真正缺失、需补数据的变量名列表 */
    truly_missing: string[];
    /** 可派生变量详情（含含义/单位，v3.3） */
    derivable_details?: { var_name: string; meaning: string; unit: string; var_type: string }[];
    /** 真正缺失变量详情（含含义/单位 → 建议补什么数据，v3.3） */
    truly_missing_details?: { var_name: string; meaning: string; unit: string; var_type: string }[];
    /** 人类可读结论 */
    suggestion: string;
    /** 是否有数据文件 */
    has_file: boolean;
  };
}

/** 数据需求项（模式 A：无数据时的字段清单） */
export interface FinmodDataNeed {
  field: string;
  type: string;
  example: string;
  purpose: string;
  suggested_chart: string;
}

/** POST /api/apps/finmod/guide 响应 data */
export interface FinmodGuideResult {
  success: boolean;
  /** A 数据需求 / B 已有数据 / C 知识讲解（确定性判定，LLM 不覆盖） */
  mode: "A" | "B" | "C" | string;
  goal: string;
  message: string;
  directions: FinmodDirection[];
  data_needs: FinmodDataNeed[];
  /** 模式 C 讲解引导文案（Markdown） */
  explanation: string;
}

export function finmodGuide(
  projectId: string,
  modelId: string,
  goal: string,
  fileNames?: string[],
): Promise<FinmodGuideResult> {
  const body: Record<string, unknown> = { project_id: projectId, model_id: modelId, goal };
  if (fileNames && fileNames.length > 0) body.file_names = fileNames;
  return request<FinmodGuideResult>("/api/apps/finmod/guide", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

// =====================================================================
// 应用二 finmod — P3 变量映射（2026-08-21）
// =====================================================================
// 需求文档 §四 步骤 4：AI 预填映射 + 派生变量表达式 + 期间列识别。

/** 单个模型所需变量的映射行 */
export interface FinmodVarMapping {
  var_name: string;
  var_meaning: string;
  var_unit: string;
  /** 预填/用户选择的对应列（从文件列名选） */
  mapped_col: string;
  /** matched 已匹配 / missing 缺失（未选或未匹配）/ statistic 自动统计 / output 输出 */
  status: "matched" | "missing" | "statistic" | "output" | string;
  /** v2.0：变量方向 input 需映射 / statistic 统计量 / output 模型输出 */
  direction?: "input" | "statistic" | "output";
  /** v2.0：变量类型 numeric / category / period */
  var_type?: "numeric" | "category" | "period";
  /** v2.0：统计量/输出标记（direct/statistic/output） */
  suggested_mode?: "direct" | "statistic" | "output";
}

/** varmap 结果：每个模型的变量映射组 */
export interface FinmodVarmapModel {
  model_id: string;
  code: string;
  name: string;
  variables: FinmodVarMapping[];
}

/** GET/POST /api/apps/finmod/varmap 响应 data */
export interface FinmodVarmapResult {
  file: string;
  sheet: string;
  /** 文件全部列名（下拉选项） */
  all_cols: string[];
  /** 期间列候选（日期类型/列名含日期时间关键词） */
  period_cols: string[];
  models: FinmodVarmapModel[];
  missing_count: number;
  /** v2.0：输入变量总数（仅 direction=input） */
  input_count?: number;
  /** v2.0：统计量变量数 */
  statistic_count?: number;
  message: string;
  /** R1：参与映射的文件列表 */
  files?: string[];
  /** R1：列 → 来源文件列表（多文件时） */
  file_of_col?: Record<string, string[]>;
  /** R1：文件数 */
  file_count?: number;
}

/** V2 AI 变量匹配：单变量映射建议（LLM 推荐） */
export interface FinmodAiMapping {
  model_id: string;
  var_name: string;
  mapped_col: string;
  confidence: number;
  reason: string;
  candidates: string[];
}

/** V2 AI 统计量绑定：{stat: COUNT/MEAN/STD/..., based_on: 观测值变量} */
export interface FinmodAiStatBinding {
  model_id: string;
  var_name: string;
  stat: string;
  based_on: string;
}

/** v3.4：可派生变量的候选派生公式（内置公式库生成，供前端自动应用） */
export interface FinmodDerivedFormula {
  model_id: string;
  var_name: string;
  formula: string;
  based_on: string[];
  note: string;
}

/** POST /api/apps/finmod/varmap-suggest 响应 data */
export interface FinmodVarmapSuggestResult {
  varmap: FinmodVarmapResult;
  ai_suggestions: {
    mappings: FinmodAiMapping[];
    stat_bindings: FinmodAiStatBinding[];
  };
  /** v3.4：可派生变量候选公式（derivable 缺失变量 → 自动生成公式） */
  derived_formulas?: FinmodDerivedFormula[];
  used_llm: boolean;
}

export function finmodVarmap(
  projectId: string,
  fileName: string,
  modelIds: string[],
  sheetName?: string,
  fileNames?: string[],
): Promise<FinmodVarmapResult> {
  const body: Record<string, unknown> = {
    project_id: projectId,
    file_name: fileName,
    sheet_name: sheetName || "",
    model_ids: modelIds,
  };
  if (fileNames && fileNames.length > 0) body.file_names = fileNames;
  return request<FinmodVarmapResult>("/api/apps/finmod/varmap", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

/** V2 AI 变量匹配（LLM 推荐 + 置信度 + 统计量绑定；LLM 不可用降级确定性） */
export function finmodVarmapSuggest(
  projectId: string,
  fileName: string,
  modelIds: string[],
  llmModelId: string,
  sheetName?: string,
  fileNames?: string[],
): Promise<FinmodVarmapSuggestResult> {
  const body: Record<string, unknown> = {
    project_id: projectId,
    file_name: fileName,
    sheet_name: sheetName || "",
    model_ids: modelIds,
    model_id: llmModelId,
  };
  if (fileNames && fileNames.length > 0) body.file_names = fileNames;
  return request<FinmodVarmapSuggestResult>("/api/apps/finmod/varmap-suggest", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

// =====================================================================
// 应用二 finmod — V3 数据预处理（2026-08-21）
// =====================================================================
// Stata/SPSS 式「分析就绪」：清洗 / 类型修正 / 多 sheet 合并 / 透视面板化。

/** 数据预处理步骤（四类 op） */
export interface FinmodPrepStep {
  /** clean | cast | merge | pivot */
  op: string;
  action?: string;
  col?: string;
  to?: string;
  subset?: string[];
  /** clean.filter/replace 条件 */
  where?: { col: string; op: string; value?: unknown };
  with?: unknown;
  /** merge 参数 */
  sheets?: string[];
  how?: string;
  on?: string[];
  suffixes?: string[];
  /** pivot 参数 */
  mode?: string;
  id_vars?: string[];
  var_name?: string;
  value_name?: string;
  index?: string;
  columns?: string;
  values?: string;
}

/** POST /api/apps/finmod/prep-data 响应 data */
export interface FinmodPrepResult {
  success: boolean;
  columns: { name: string; type: string }[];
  rows: number;
  preview: Record<string, unknown>[];
  logs: string[];
  errors: { step: number; op: string; message: string }[];
}

export function finmodPrepData(
  projectId: string,
  fileName: string,
  steps: FinmodPrepStep[],
  sheetName?: string,
  fileNames?: string[],
): Promise<FinmodPrepResult> {
  const body: Record<string, unknown> = {
    project_id: projectId,
    file_name: fileName,
    sheet_name: sheetName || "",
    steps,
  };
  if (fileNames && fileNames.length > 0) body.file_names = fileNames;
  return request<FinmodPrepResult>("/api/apps/finmod/prep-data", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

/** 派生变量求值结果（每公式） */
export interface FinmodDerivedFormulaResult {
  type: "series" | "scalar" | string;
  /** 前 5 个示例值（series）或单值（scalar） */
  sample: unknown[];
  rows: number;
  dtype: string;
}

/** POST /api/apps/finmod/derived-eval 响应 data */
export interface FinmodDerivedEvalResult {
  results: Record<string, FinmodDerivedFormulaResult>;
  errors: { line: number; name: string; kind: string; message: string }[];
  all_cols: string[];
  row_count: number;
}

export function finmodDerivedEval(
  projectId: string,
  fileName: string,
  formulas: string[],
  mappings?: Record<string, string>,
  sheetName?: string,
  fileNames?: string[],
): Promise<FinmodDerivedEvalResult> {
  const body: Record<string, unknown> = {
    project_id: projectId,
    file_name: fileName,
    sheet_name: sheetName || "",
    formulas,
    mappings: mappings || {},
  };
  if (fileNames && fileNames.length > 0) body.file_names = fileNames;
  return request<FinmodDerivedEvalResult>("/api/apps/finmod/derived-eval", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

// =====================================================================
// 应用二 finmod — P4 图表配置（2026-08-21）
// =====================================================================
// 需求文档 §四 步骤 5：AI 推荐图表 + 档位白名单 + chart_manifest 收敛。

/** 图表推荐项（POST /charts-suggest） */
export interface FinmodChartSuggestion {
  template: string;
  name: string;
  level: string;
  level_label: string;
  default_variant: string;
  reason: string;
  /** R4：重要性 primary 首选 / secondary 次选 / optional 兜底 */
  importance?: "primary" | "secondary" | "optional";
  /** R4：图表类别（trend/compare/share/sensitivity/distribution/relation） */
  category?: string;
  /** R4：类别中文名 */
  category_label?: string;
}

/** POST /api/apps/finmod/charts-suggest 响应 data */
export interface FinmodChartSuggestResult {
  level: string;
  level_label: string;
  suggestions: FinmodChartSuggestion[];
  note: string;
  /** R4：可用图表类别（中文） */
  categories?: string[];
}

/** R4：图表风格偏好（用户表达，非硬性勾选） */
export interface FinmodStylePrefs {
  /** 复杂度档位 L1/L2/L3 */
  level?: string;
  /** 配色 auto/blues/greens/reds/oranges/purples/blacks */
  colors?: string;
  /** 偏好图表类别（trend 趋势/compare 对比/share 占比/sensitivity 敏感性/distribution 分布/relation 关系） */
  categories?: string[];
}

export function finmodChartSuggest(
  modelIds: string[],
  guideCharts?: string[],
  level?: string,
  stylePrefs?: FinmodStylePrefs,
): Promise<FinmodChartSuggestResult> {
  const body: Record<string, unknown> = {
    model_ids: modelIds,
    guide_charts: guideCharts || [],
    level: level || "L2",
  };
  if (stylePrefs) body.style_prefs = stylePrefs;
  return request<FinmodChartSuggestResult>("/api/apps/finmod/charts-suggest", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

/** chart_manifest 单项（步骤 5 确认清单收敛，P5 run 消费） */
export interface FinmodChartManifestItem {
  id: string;
  /** 模板名（类型，如 line） */
  template: string;
  /** 变体名（如 line-forecast / line-smooth；默认变体=template） */
  variant: string;
  /** 模板中文名 */
  name: string;
  /** 复杂度档位 L1/L2/L3 */
  level: string;
  /** 可用变体列表（下拉） */
  variants: string[];
  /** 配色（宏观选择写入；auto/blues/greens/reds/oranges/purples/blacks） */
  color_scheme: string;
  /** 数据源列（数据口径） */
  data_source: string[];
  /** 推荐理由（来自 charts-suggest） */
  reason?: string;
  /** R4：重要性（primary 优先使用 / secondary 按需 / optional 兜底；AI 报告可增减） */
  importance?: "primary" | "secondary" | "optional";
}

// =====================================================================
// 应用二 finmod — P5 执行引擎（2026-08-21）
// =====================================================================
// 需求文档 §四 步骤 6：确定性执行（0 LLM）+ 数据分析器。

/** 模型执行结果 */
export interface FinmodRunModelResult {
  model_id: string;
  code: string;
  name: string;
  ok: boolean;
  summary: Record<string, unknown>;
}

/** 图表数据（run 返回，供 ChartRenderer 渲染） */
export interface FinmodRunChart {
  chart_id: string;
  template: string;
  variant: string;
  name: string;
  level: string;
  color_scheme: string;
  data: { categories: string[]; series: { name: string; data: unknown[] }[] };
  data_table: Record<string, unknown>[];
}

/** POST /api/apps/finmod/run 响应 data */
export interface FinmodRunResult {
  run_id: string;
  runId: string;
  models: FinmodRunModelResult[];
  charts: FinmodRunChart[];
  row_count: number;
  /** v2.0 V1：派生/统计量公式错误（不阻塞执行） */
  derived_errors?: { line: number; name: string; kind: string; message: string }[];
  /** V3：数据预处理步骤日志（空=未用预处理） */
  prep_logs?: string[];
  /** R1：多文件合并策略（single/join/concat/union） */
  merge_strategy?: string;
  /** R1：合并日志 */
  merge_logs?: string[];
  /** R1：参与执行的文件列表 */
  files_used?: string[];
  /** R5：数据统计摘要（均值/极值/样本量，供报告数据概览） */
  data_stats?: Record<string, unknown>;
}

export function finmodRun(
  projectId: string,
  fileName: string,
  modelIds: string[],
  mappings: Record<string, Record<string, string>>,
  params: Record<string, Record<string, unknown>>,
  chartManifest: FinmodChartManifestItem[],
  derivedFormulas: string[] = [],
  prepSteps: FinmodPrepStep[] = [],
  fileNames?: string[],
): Promise<FinmodRunResult> {
  const body: Record<string, unknown> = {
    project_id: projectId,
    file_name: fileName,
    model_ids: modelIds,
    mappings,
    params,
    chart_manifest: chartManifest,
    derived_formulas: derivedFormulas,  // v2.0 V1：派生/统计量公式（统计量广播）
    prep_steps: prepSteps,              // V3：数据预处理步骤（清洗/合并/透视）
  };
  if (fileNames && fileNames.length > 0) body.file_names = fileNames;
  return request<FinmodRunResult>("/api/apps/finmod/run", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

/** POST /api/apps/finmod/analyze 响应 data */
export interface FinmodAnalyzeResult {
  results: Record<string, { type: string; sample: unknown[]; rows: number }>;
  errors: { line: number; name: string; kind: string; message: string }[];
  columns: string[];
  rows: Record<string, unknown>[];
  scalars: Record<string, unknown>;
}

export function finmodAnalyze(
  projectId: string,
  fileName: string,
  formulas: string[],
  fileNames?: string[],
): Promise<FinmodAnalyzeResult> {
  const body: Record<string, unknown> = { project_id: projectId, file_name: fileName, formulas };
  if (fileNames && fileNames.length > 0) body.file_names = fileNames;
  return request<FinmodAnalyzeResult>("/api/apps/finmod/analyze", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

// =====================================================================
// 应用二 finmod — P6 报告交付（2026-08-21）
// =====================================================================
// 需求文档 §四 步骤 7 + §六：SVG/PNG 落盘 → 静态代理 → md 报告（LLM/降级）。

/** POST /api/apps/finmod/save-chart 响应 data */
export interface FinmodSaveChartResult {
  path: string;
  rel_path: string;
  filename: string;
}

export function finmodSaveChart(
  projectId: string,
  runId: string,
  filename: string,
  content: string,
  format: "svg" | "png" = "svg",
): Promise<FinmodSaveChartResult> {
  return request<FinmodSaveChartResult>("/api/apps/finmod/save-chart", {
    method: "POST",
    body: JSON.stringify({ project_id: projectId, run_id: runId, filename, content, format }),
  });
}

/** POST /api/apps/finmod/py-chart 响应 data（Python 3D 图 → base64 PNG 静态图） */
export interface FinmodPyChartResult {
  b64: string;
  note: string;
  success: boolean;
  /** v6.11 plotly 交互 JSON——v6.13 起**前端不再渲染**（放弃在线拖拽/缩放），仅保留供
   * AI 提示词/Python 代码对照；前端只使用 base64 PNG。无则 null。 */
  fig_json?: string | null;
  /** 是否含交互 plotly 数据 */
  interactive?: boolean;
}

/** Python 3D 图（瀑布/柱状/散点）：data → mplot3d → base64 PNG 静态图。
 * 3D 模板（waterfall3d/bar3d/scatter3d）改用 Python 生成；前端只显示 <img> 静态图
 * （图片样例），点开可放大/下载（PythonImageLightbox）；不再用 plotly.js 渲染交互。 */
export function finmodPyChart(
  template: string,
  data: Record<string, unknown>,
): Promise<FinmodPyChartResult> {
  return request<FinmodPyChartResult>("/api/apps/finmod/py-chart", {
    method: "POST",
    body: JSON.stringify({ template, data }),
  });
}

/** POST /api/apps/finmod/export-md 响应 data */
export interface FinmodExportMdResult {
  path: string;
  rel_path: string;
  filename: string;
  report: string;
  used_llm: boolean;
}

export function finmodExportMd(params: {
  projectId: string;
  runId: string;
  goal: string;
  modelId: string;
  models: FinmodRunModelResult[];
  charts: (FinmodRunChart & { rel_path?: string })[];
  /** R5：数据统计摘要（run 返回） */
  dataStats?: Record<string, unknown>;
  /** R5：图表风格偏好 */
  stylePrefs?: FinmodStylePrefs;
}): Promise<FinmodExportMdResult> {
  const body: Record<string, unknown> = {
    project_id: params.projectId,
    run_id: params.runId,
    goal: params.goal,
    model_id: params.modelId,
    models: params.models,
    charts: params.charts,
  };
  if (params.dataStats) body.data_stats = params.dataStats;
  if (params.stylePrefs) body.style_prefs = params.stylePrefs;
  return request<FinmodExportMdResult>("/api/apps/finmod/export-md", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

/** 图表资源预览 URL（静态代理） */
export function finmodAssetUrl(runId: string, file: string): string {
  return `/api/apps/finmod/files/${runId}/assets/${encodeURIComponent(file)}`;
}

/** D5：应用二报告 Markdown → Word 导出（后端 Pandoc）。content 传入则优先（当前编辑内容）。 */
export async function finmodExportDocx(runId: string, content?: string): Promise<Blob> {
  const resp = await fetch("/api/apps/finmod/export-docx", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ run_id: runId, content }),
  });
  if (!resp.ok) {
    let msg = `导出失败（HTTP ${resp.status}）`;
    try {
      const j = await resp.json();
      if (j && typeof j.message === "string") msg = j.message;
    } catch { /* 非 JSON 响应保留默认信息 */ }
    throw new Error(msg);
  }
  return await resp.blob();
}
