/** ReconWizard — 数据核对向导面板（6 步流程中的 1-4：配置阶段）。
 *
 * 由 DataCheckAppPage 统一管理 6 步流程（1 数据 → 2 匹配键 → 3 核对变量 →
 * 4 容差&处理策略 → 5 校验 → 6 修改）。本组件只渲染步骤 1-4 的面板（受控 step），
 * 不做内部步骤条——步骤条常驻在 DataCheckAppPage，用户随时可回退。
 * 步骤 4 合并「容差 + 处理策略」（容差本身是一种处理策略）。
 */

import { useEffect, useMemo, useState } from "react";
import {
  FileSpreadsheet, KeyRound, Play, Loader2, Sparkles, ChevronLeft, ChevronRight,
  CheckCircle2, Database, Coins, ClipboardList,
} from "lucide-react";
import {
  listDataFiles, dataIndex,
  type DataFileRecord, type DataSheet,
} from "../lib/api";

export interface MatchKeys {
  k1: string;   // 一级（必填）
  k2: string;   // 二级（可空）
  k3: string;   // 三级（可空）
  k2On: boolean;
  k3On: boolean;
}

export interface ReconParams {
  baseFile: string;
  detailFile: string;
  matchKeys: MatchKeys;
  /** 核对变量（分表字段名，可多选） */
  variables: string[];
  /** 依据表金额列（两表列名不同时必填；与 variables 第一项对应） */
  baseAmountCol: string;
  /** 容差（元） */
  tolerance: number;
  /** 匹配不上处理：list | fallback | mark | 自定义文本 */
  unmatchedAction: string;
  /** A 类差异自动写回 */
  autoFix: boolean;
}

const ACTION_LABEL: Record<string, string> = {
  list: "A. 列清单供人工复核",
  fallback: "B. 按（人员+客户）降级匹配",
  mark: "C. 全部标记无法匹配",
};

/** 所有 sheet 的字段去重并集 */
function collectFields(sheets: DataSheet[] | undefined): string[] {
  const set = new Set<string>();
  for (const s of sheets || []) {
    for (const h of s.headers || []) if (h.name) set.add(h.name);
  }
  return Array.from(set);
}

/** 归一化字段名（去空格/下划线/括号）供相似度比较 */
function norm(s: string): string {
  return s.replace(/[\s_\-（）()]/g, "").toLowerCase();
}

/** 两字段名相似（归一化后相等或互相包含） */
function similar(a: string, b: string): boolean {
  const na = norm(a), nb = norm(b);
  if (!na || !nb) return false;
  return na === nb || na.includes(nb) || nb.includes(na);
}

/** 金额类列名推荐（AI 推荐置顶） */
function isAmountField(name: string, type: string, nonNull?: number): boolean {
  const nameHit = /金额|提成|款|额|合计|回款|工资|奖金|补贴/.test(name);
  const typeHit = /num|int|float|double|decimal/i.test(type || "");
  const dense = nonNull == null || nonNull >= 0.8;
  return (nameHit && typeHit) || (nameHit && dense) || (typeHit && dense && nameHit);
}

export default function ReconWizard({
  projectId,
  initial,
  step,
  onStepChange,
  onStart,
  running,
  onOpenDb,
  refreshTick,
}: {
  projectId: string;
  initial?: ReconParams | null;
  /** 当前配置步骤（1-5，由父级 8 步流程控制） */
  step: number;
  onStepChange: (s: number) => void;
  onStart: (params: ReconParams) => void;
  running?: boolean;
  /** 打开应用专属「项目数据库」抽屉（上传/删除/刷新） */
  onOpenDb?: () => void;
  /** 数据库变更触发号（父级 onImported/删除后自增，本组件据此重新拉取文件） */
  refreshTick?: number;
}) {
  // 步骤 1：文件
  const [files, setFiles] = useState<DataFileRecord[]>([]);
  const [baseId, setBaseId] = useState("");
  const [detailId, setDetailId] = useState("");

  // ---------- 步骤 2：匹配键 ----------
  const [matchKeys, setMatchKeys] = useState<MatchKeys>({ k1: "", k2: "", k3: "", k2On: false, k3On: false });

  // ---------- 步骤 3：核对变量 ----------
  const [variables, setVariables] = useState<string[]>([]);
  const [baseAmountCol, setBaseAmountCol] = useState("");

  // ---------- 步骤 4：容差 ----------
  const [tolerance, setTolerance] = useState<number>(1);

  // ---------- 步骤 5：策略 ----------
  const [unmatchedAction, setUnmatchedAction] = useState("list");
  const [customAction, setCustomAction] = useState("");
  const [autoFix, setAutoFix] = useState(true);

  // ---------- 数据预取（dataIndex → 字段） ----------
  const [baseSheets, setBaseSheets] = useState<DataSheet[]>([]);
  const [detailSheets, setDetailSheets] = useState<DataSheet[]>([]);

  // 初始值回填（结果页「修改参数重新核对」）
  useEffect(() => {
    if (!initial) return;
    const b = files.find((f) => f.file_name === initial.baseFile);
    const d = files.find((f) => f.file_name === initial.detailFile);
    if (b) setBaseId(b.id);
    if (d) setDetailId(d.id);
    setMatchKeys(initial.matchKeys);
    setVariables(initial.variables);
    setBaseAmountCol(initial.baseAmountCol);
    setTolerance(initial.tolerance);
    setUnmatchedAction(initial.unmatchedAction);
    if (!["list", "fallback", "mark"].includes(initial.unmatchedAction)) {
      setCustomAction(initial.unmatchedAction);
    }
    setAutoFix(initial.autoFix);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initial]);

  // 加载文件列表
  // ---------- 步骤 1：文件（导入/删除/刷新由「项目数据库」抽屉负责，见 onOpenDb） ----------
  // 抽屉内上传导入完成后 onImported → 父级 refreshTick+1 → 本组件重新拉取下拉
  useEffect(() => {
    let cancelled = false;
    listDataFiles(projectId)
      .then((r) => {
        if (cancelled) return;
        setFiles(r.files);
        if (initial) {
          const b = r.files.find((f) => f.file_name === initial.baseFile);
          const d = r.files.find((f) => f.file_name === initial.detailFile);
          if (b) setBaseId(b.id);
          if (d) setDetailId(d.id);
        }
      })
      .catch(() => {});
    return () => { cancelled = true; };
  }, [projectId, initial]);

  // 数据库抽屉变更后重新拉取文件列表
  useEffect(() => {
    let cancelled = false;
    listDataFiles(projectId)
      .then((r) => { if (!cancelled) setFiles(r.files); })
      .catch(() => {});
    return () => { cancelled = true; };
  }, [refreshTick, projectId]);

  // 选中文件 → 预取字段（步骤 2/3 的数据源）
  useEffect(() => {
    if (!baseId) { setBaseSheets([]); return; }
    let cancelled = false;
    dataIndex(baseId)
      .then((r) => { if (!cancelled) setBaseSheets(r.sheets || []); })
      .catch(() => {});
    return () => { cancelled = true; };
  }, [baseId]);

  useEffect(() => {
    if (!detailId) { setDetailSheets([]); return; }
    let cancelled = false;
    dataIndex(detailId)
      .then((r) => { if (!cancelled) setDetailSheets(r.sheets || []); })
      .catch(() => {});
    return () => { cancelled = true; };
  }, [detailId]);

  // ---------- 派生数据 ----------
  const baseFile = files.find((f) => f.id === baseId);
  const detailFile = files.find((f) => f.id === detailId);

  const baseFields = useMemo(() => collectFields(baseSheets), [baseSheets]);
  const detailFields = useMemo(() => collectFields(detailSheets), [detailSheets]);
  const unionFields = useMemo(() => Array.from(new Set([...baseFields, ...detailFields])), [baseFields, detailFields]);

  /** 字段是否两表共有或相似（推荐徽标）：同名 或 归一化后包含（如 合同编号 vs 合同号） */
  const sharedField = (f: string) => {
    if (baseFields.includes(f) && detailFields.includes(f)) return true;
    const other = baseFields.includes(f) ? detailFields : baseFields;
    return other.some((x) => similar(f, x));
  };

  /** 核对变量推荐：金额类字段置顶（列名含金额词 + 数值类型/高非空率） */
  const recommendedVars = useMemo(() => {
    const all = detailSheets.flatMap((s) => s.headers || []);
    const uniq = new Map<string, { type: string; nonNull?: number }>();
    for (const h of all) {
      if (!h.name) continue;
      const prev = uniq.get(h.name);
      uniq.set(h.name, {
        type: h.type || "",
        nonNull: prev?.nonNull ?? h.non_null_rate,
      });
    }
    return Array.from(uniq.entries())
      .filter(([name, meta]) => isAmountField(name, meta.type, meta.nonNull))
      .map(([name]) => name);
  }, [detailSheets]);

  // ---------- 校验 ----------
  const canNext = (s: number) => {
    switch (s) {
      case 1: return !!baseId && !!detailId;
      case 2: return !!matchKeys.k1;
      case 3: return variables.length > 0 && !!baseAmountCol;
      // 步骤 4 合并「容差 + 处理策略」：都合法才可进入校验
      case 4: return (
        !Number.isNaN(tolerance) && tolerance >= 0 &&
        (unmatchedAction !== "custom" || customAction.trim().length > 0)
      );
      default: return true;
    }
  };

  const actionText = unmatchedAction === "custom" ? customAction.trim() : unmatchedAction;

  // ---------- 提交 ----------
  function handleStart() {
    if (!baseFile || !detailFile) return;
    onStart({
      baseFile: baseFile.file_name,
      detailFile: detailFile.file_name,
      matchKeys,
      variables,
      baseAmountCol,
      tolerance,
      unmatchedAction: actionText,
      autoFix,
    });
  }

  const matchKeyChain = [matchKeys.k1, matchKeys.k2On ? matchKeys.k2 : "", matchKeys.k3On ? matchKeys.k3 : ""].filter(Boolean).join(" > ");

  // ================================================================
  return (
    // min-h-0：flex 子项默认 min-height:auto，内容超出时会被撑开而非滚动
    <div className="min-h-0 flex-1 overflow-y-auto px-6 pt-6 pb-4">
      <div className="mx-auto max-w-2xl">
        {/* 步骤 1-5 面板（页头 + 应用专用 AI 卡已由父级共享头部提供） */}

        {/* ===== 步骤 1：数据文件 ===== */}
        {step === 1 && (
          <section className="rounded-xl border border-zinc-200 bg-white p-5">
            <div className="flex items-center gap-2">
              <span className="flex size-5 items-center justify-center rounded-full bg-zinc-900 text-[11px] font-semibold text-white">1</span>
              <h2 className="text-[15px] font-semibold text-zinc-800">选择数据文件</h2>
              <button
                onClick={onOpenDb}
                className="ml-auto flex items-center gap-1 rounded-md border border-zinc-200 px-2 py-1 text-[11.5px] text-zinc-600 transition-colors hover:bg-zinc-100"
              >
                <Database size={12} />
                项目数据库
              </button>
            </div>
            <p className="mt-1 text-[12px] text-zinc-400">
              从项目数据库选取核对文件；点「项目数据库」可上传 Excel、删除或刷新数据表。
            </p>

            <div className="mt-4 space-y-3">
              <FilePicker
                label="依据表（基准）"
                files={files}
                value={baseId}
                onChange={setBaseId}
              />
              <FilePicker
                label="分表（待核对）"
                files={files}
                value={detailId}
                onChange={setDetailId}
              />
            </div>
          </section>
        )}

        {/* ===== 步骤 2：匹配键 ===== */}
        {step === 2 && (
          <section className="rounded-xl border border-zinc-200 bg-white p-5">
            <div className="flex items-center gap-2">
              <span className="flex size-5 items-center justify-center rounded-full bg-zinc-900 text-[11px] font-semibold text-white">2</span>
              <h2 className="text-[15px] font-semibold text-zinc-800">匹配键</h2>
            </div>
            <p className="mt-1 text-[12px] text-zinc-400">
              按优先级从高到低选择；「两表共有」字段为 AI 推荐。匹配规则：优先按一级，若多条再按二级、三级。
            </p>

            <div className="mt-4 space-y-3">
              <MatchKeyRow
                label="一级（必填）"
                options={unionFields}
                shared={sharedField}
                value={matchKeys.k1}
                onChange={(v) => setMatchKeys((m) => ({ ...m, k1: v }))}
              />
              <MatchKeyRow
                label="二级"
                options={unionFields}
                shared={sharedField}
                value={matchKeys.k2}
                enabled={matchKeys.k2On}
                onToggle={() => setMatchKeys((m) => ({ ...m, k2On: !m.k2On }))}
                onChange={(v) => setMatchKeys((m) => ({ ...m, k2: v }))}
              />
              <MatchKeyRow
                label="三级"
                options={unionFields}
                shared={sharedField}
                value={matchKeys.k3}
                enabled={matchKeys.k3On}
                onToggle={() => setMatchKeys((m) => ({ ...m, k3On: !m.k3On }))}
                onChange={(v) => setMatchKeys((m) => ({ ...m, k3: v }))}
              />
            </div>

            {matchKeyChain && (
              <div className="mt-3 flex items-center gap-1.5 rounded-md bg-zinc-50 px-3 py-2 text-[12px] text-zinc-600">
                <KeyRound size={13} className="text-zinc-400" />
                匹配键链：<span className="font-medium text-zinc-800">{matchKeyChain}</span>
              </div>
            )}
          </section>
        )}

        {/* ===== 步骤 3：核对变量 ===== */}
        {step === 3 && (
          <section className="rounded-xl border border-zinc-200 bg-white p-5">
            <div className="flex items-center gap-2">
              <span className="flex size-5 items-center justify-center rounded-full bg-zinc-900 text-[11px] font-semibold text-white">3</span>
              <h2 className="text-[15px] font-semibold text-zinc-800">核对变量</h2>
            </div>

            {/* 分表核对变量（可多选） */}
            <p className="mt-3 text-[12px] font-medium text-zinc-500">① 分表金额列（待核对，可多选）</p>
            <p className="mt-0.5 text-[12px] text-zinc-400">
              选择要核对的金额列。AI 已按「金额类列名 + 数值类型 + 高非空率」推荐置顶。
            </p>

            {detailFields.length === 0 ? (
              <p className="mt-4 text-[13px] text-zinc-400">未读取到分表字段，请先在上一步选择分表。</p>
            ) : (
              <div className="mt-3 grid grid-cols-1 gap-1.5 sm:grid-cols-2">
                {[...recommendedVars, ...detailFields.filter((f) => !recommendedVars.includes(f))].map((f) => {
                  const rec = recommendedVars.includes(f);
                  const on = variables.includes(f);
                  return (
                    <button
                      key={f}
                      type="button"
                      onClick={() => setVariables((v) => (v.includes(f) ? v.filter((x) => x !== f) : [...v, f]))}
                      className={`flex items-center gap-2 rounded-lg border px-2.5 py-2 text-left text-[13px] transition-colors ${
                        on ? "border-zinc-900 bg-zinc-50" : "border-zinc-200 hover:bg-zinc-50"
                      }`}
                    >
                      <Coins size={13} className={on ? "text-zinc-900" : "text-zinc-300"} />
                      <span className="min-w-0 flex-1 truncate text-zinc-700">{f}</span>
                      {rec && (
                        <span className="flex shrink-0 items-center gap-0.5 rounded-full bg-blue-50 px-1.5 py-px text-[10px] font-medium text-blue-600">
                          <Sparkles size={9} /> AI 推荐
                        </span>
                      )}
                      <span
                        className={`flex size-4 shrink-0 items-center justify-center rounded-[5px] transition-colors ${
                          on ? "bg-zinc-900 text-white" : "shadow-[inset_0_0_0_1.5px_#d4d4d8]"
                        }`}
                      >
                        {on && <CheckCircle2 size={11} />}
                      </span>
                    </button>
                  );
                })}
              </div>
            )}

            {/* 依据表金额列（单选，与分表变量第一项对应） */}
            <p className="mt-5 text-[12px] font-medium text-zinc-500">
              ② 依据表金额列（与分表第一项对应）
            </p>
            <p className="mt-0.5 text-[12px] text-zinc-400">
              两表列名相同时自动选中；不同时（如「个人提成金额_元」 vs「兑现销售提成金额_2025年一季度」）请手动选择依据表的对应金额列。
            </p>

            {baseFields.length === 0 ? (
              <p className="mt-3 text-[13px] text-zinc-400">未读取到依据表字段，请先在上一步选择依据表。</p>
            ) : (
              <div className="mt-3 grid grid-cols-1 gap-1.5 sm:grid-cols-2">
                {baseFields.map((f) => {
                  const on = baseAmountCol === f;
                  const rec = variables[0] && (f === variables[0] || similar(f, variables[0]));
                  return (
                    <button
                      key={f}
                      type="button"
                      onClick={() => setBaseAmountCol(f)}
                      className={`flex items-center gap-2 rounded-lg border px-2.5 py-2 text-left text-[13px] transition-colors ${
                        on ? "border-zinc-900 bg-zinc-50" : "border-zinc-200 hover:bg-zinc-50"
                      }`}
                    >
                      <Database size={13} className={on ? "text-zinc-900" : "text-zinc-300"} />
                      <span className="min-w-0 flex-1 truncate text-zinc-700">{f}</span>
                      {rec && (
                        <span className="flex shrink-0 items-center gap-0.5 rounded-full bg-blue-50 px-1.5 py-px text-[10px] font-medium text-blue-600">
                          <Sparkles size={9} /> 匹配
                        </span>
                      )}
                      <span
                        className={`flex size-4 shrink-0 items-center justify-center rounded-full transition-colors ${
                          on ? "bg-zinc-900 text-white" : "shadow-[inset_0_0_0_1.5px_#d4d4d8]"
                        }`}
                      >
                        {on && <CheckCircle2 size={11} />}
                      </span>
                    </button>
                  );
                })}
              </div>
            )}
          </section>
        )}

        {/* ===== 步骤 4：容差 & 处理策略（合并：容差本身是一种处理策略） ===== */}
        {step === 4 && (
          <section className="rounded-xl border border-zinc-200 bg-white p-5">
            <div className="flex items-center gap-2">
              <span className="flex size-5 items-center justify-center rounded-full bg-zinc-900 text-[11px] font-semibold text-white">4</span>
              <h2 className="text-[15px] font-semibold text-zinc-800">容差 & 处理策略</h2>
            </div>
            <p className="mt-1 text-[12px] text-zinc-400">
              容差是处理策略的一部分：差异 ≤ 容差视为一致，超出的进入差异分级处理。
            </p>

            {/* ① 容差 */}
            <p className="mt-4 text-[12px] font-medium text-zinc-500">① 容差（元）</p>
            <div className="mt-2 flex items-center gap-2">
              <input
                type="number"
                min={0}
                step={0.01}
                value={Number.isNaN(tolerance) ? "" : tolerance}
                onChange={(e) => setTolerance(parseFloat(e.target.value))}
                className="w-32 rounded-md border border-zinc-200 px-3 py-2 text-[13px] text-zinc-800 outline-none transition-colors focus:border-zinc-400"
              />
              <span className="text-[12px] text-zinc-400">元</span>
              <div className="ml-auto flex items-center gap-1">
                {[0, 0.01, 0.1, 1, 5].map((v) => (
                  <button
                    key={v}
                    onClick={() => setTolerance(v)}
                    className={`rounded-md border px-2 py-1 text-[11.5px] transition-colors ${
                      tolerance === v ? "border-zinc-900 bg-zinc-900 text-white" : "border-zinc-200 text-zinc-500 hover:bg-zinc-100"
                    }`}
                  >
                    {v}
                  </button>
                ))}
              </div>
            </div>

            {/* ② 匹配不上处理 */}
            <p className="mt-5 text-[12px] font-medium text-zinc-500">② 匹配不上的记录如何处理</p>
            <div className="mt-2 space-y-1">
              {[
                { v: "list", label: "A. 列清单供人工复核", desc: "标记无法匹配，输出清单由人工判断（默认）" },
                { v: "fallback", label: "B. 按（人员+客户）降级匹配", desc: "合同编号匹配不上时退而用人员+客户组合" },
                { v: "mark", label: "C. 全部标记无法匹配", desc: "不做降级，一律标为 C 类" },
                { v: "custom", label: "D. 自定义", desc: "自定义其他处理方式" },
              ].map((opt) => (
                <button
                  key={opt.v}
                  type="button"
                  onClick={() => setUnmatchedAction(opt.v)}
                  className={`flex w-full items-start gap-2.5 rounded-lg border px-3 py-2 text-left transition-colors ${
                    unmatchedAction === opt.v ? "border-zinc-900 bg-zinc-50" : "border-zinc-200 hover:bg-zinc-50"
                  }`}
                >
                  <span
                    className={`mt-0.5 flex size-4 shrink-0 items-center justify-center rounded-full border transition-colors ${
                      unmatchedAction === opt.v ? "border-zinc-900 bg-zinc-900" : "border-zinc-300"
                    }`}
                  >
                    {unmatchedAction === opt.v && <span className="size-1.5 rounded-full bg-white" />}
                  </span>
                  <span className="min-w-0">
                    <span className="block text-[13px] text-zinc-800">{opt.label}</span>
                    <span className="block text-[11.5px] text-zinc-400">{opt.desc}</span>
                  </span>
                </button>
              ))}
            </div>
            {unmatchedAction === "custom" && (
              <input
                value={customAction}
                onChange={(e) => setCustomAction(e.target.value)}
                placeholder="请输入自定义处理方式…"
                className="mt-2 w-full rounded-md border border-zinc-200 px-3 py-2 text-[13px] text-zinc-800 outline-none transition-colors focus:border-zinc-400"
              />
            )}

            {/* ③ A 类差异自动写回 */}
            <div className="mt-5 flex items-center justify-between rounded-lg bg-zinc-50 px-3.5 py-2.5">
              <div>
                <p className="text-[13px] font-medium text-zinc-800">③ A 类差异自动写回</p>
                <p className="text-[11.5px] text-zinc-400">漏填缺失/金额误差等可自动修正的差异，核对后直接写入数据库</p>
              </div>
              <button
                type="button"
                onClick={() => setAutoFix((v) => !v)}
                className={`relative h-5 w-9 shrink-0 rounded-full transition-colors ${autoFix ? "bg-zinc-900" : "bg-zinc-300"}`}
              >
                <span
                  className={`absolute top-0.5 size-4 rounded-full bg-white shadow transition-all ${autoFix ? "left-[18px]" : "left-0.5"}`}
                />
              </button>
            </div>

            {/* 配置摘要（确认后进入校验） */}
            <div className="mt-4 rounded-lg border border-zinc-100 p-4">
              <p className="mb-2 flex items-center gap-1.5 text-[12px] font-medium text-zinc-500">
                <ClipboardList size={13} className="text-zinc-400" />
                配置摘要（确认后进入校验）
              </p>
              <div className="space-y-2">
                <SummaryRow label="依据表" value={baseFile?.file_name || ""} />
                <SummaryRow label="分表" value={detailFile?.file_name || ""} />
                <SummaryRow label="匹配键链" value={matchKeyChain} />
                <SummaryRow label="核对变量" value={variables.join("、")} />
                <SummaryRow label="依据金额列" value={baseAmountCol} />
                <SummaryRow label="容差" value={`${tolerance} 元`} />
                <SummaryRow label="匹配不上" value={ACTION_LABEL[actionText] || actionText} />
                <SummaryRow label="自动写回" value={autoFix ? "开启（A 类自动）" : "关闭（仅报告）"} />
              </div>
            </div>
          </section>
        )}

        {/* 底部操作栏 */}
        <div className="mt-6 flex items-center justify-between">
          <button
            onClick={() => onStepChange(Math.max(1, step - 1))}
            disabled={step === 1}
            className="flex items-center gap-1 rounded-lg border border-zinc-200 bg-white px-3.5 py-2 text-[13px] font-medium text-zinc-600 transition-colors hover:bg-zinc-100 disabled:cursor-not-allowed disabled:opacity-40"
          >
            <ChevronLeft size={14} /> 上一步
          </button>

          {step < 4 ? (
            <button
              onClick={() => onStepChange(step + 1)}
              disabled={!canNext(step)}
              className="flex items-center gap-1 rounded-lg bg-zinc-900 px-4 py-2 text-[13px] font-medium text-white transition-colors hover:bg-zinc-700 disabled:cursor-not-allowed disabled:bg-zinc-300"
            >
              下一步 <ChevronRight size={14} />
            </button>
          ) : (
            <button
              onClick={handleStart}
              disabled={running || !canNext(4)}
              className="flex items-center gap-1.5 rounded-lg bg-zinc-900 px-4 py-2 text-[13px] font-medium text-white transition-colors hover:bg-zinc-700 disabled:cursor-not-allowed disabled:bg-zinc-300"
            >
              {running ? <Loader2 size={13} className="animate-spin" /> : <Play size={13} />}
              开始校验
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

/* ================= 子组件 ================= */

function FilePicker({
  label, files, value, onChange,
}: {
  label: string;
  files: DataFileRecord[];
  value: string;
  onChange: (id: string) => void;
}) {
  const picked = files.find((f) => f.id === value);
  return (
    <div>
      <div className="mb-1 flex items-center gap-1.5 text-[12px] font-medium text-zinc-500">
        <FileSpreadsheet size={14} className="text-zinc-400" />
        {label}
      </div>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-full rounded-md border border-zinc-200 bg-white px-3 py-2 text-[13px] text-zinc-800 outline-none transition-colors focus:border-zinc-400"
      >
        <option value="">请选择文件…</option>
        {files.map((f) => (
          <option key={f.id} value={f.id}>
            {f.file_name}
            {f.total_rows ? `（${f.total_rows.toLocaleString()} 行）` : ""}
          </option>
        ))}
      </select>
      {picked && (
        <div className="mt-1.5 flex items-center gap-2 text-[11px] text-zinc-400">
          <span className="flex items-center gap-0.5 rounded-full bg-emerald-50 px-2 py-px font-medium text-emerald-600">
            <Database size={9} /> 已导入项目库
          </span>
          {picked.sheet_count > 0 && <span>{picked.sheet_count} 个工作表</span>}
          {picked.updated_at && <span>{picked.updated_at.slice(0, 10)}</span>}
        </div>
      )}
    </div>
  );
}

function MatchKeyRow({
  label, options, shared, value, enabled, onToggle, onChange,
}: {
  label: string;
  options: string[];
  shared: (f: string) => boolean;
  value: string;
  enabled?: boolean;
  onToggle?: () => void;
  onChange: (v: string) => void;
}) {
  const useEnabled = enabled !== undefined;
  return (
    <div>
      <div className="mb-1 flex items-center gap-1.5 text-[12px] font-medium text-zinc-500">
        <KeyRound size={13} className="text-zinc-400" />
        {label}
        {useEnabled && (
          <button
            type="button"
            onClick={onToggle}
            className={`rounded-full px-2 py-px text-[10.5px] transition-colors ${
              enabled ? "bg-zinc-900 text-white" : "bg-zinc-100 text-zinc-400 hover:bg-zinc-200"
            }`}
          >
            {enabled ? "启用" : "可空"}
          </button>
        )}
      </div>
      <select
        value={enabled === false ? "" : value}
        onChange={(e) => onChange(e.target.value)}
        disabled={enabled === false}
        className={`w-full rounded-md border px-3 py-2 text-[13px] outline-none transition-colors focus:border-zinc-400 ${
          enabled === false ? "cursor-not-allowed border-zinc-100 bg-zinc-50 text-zinc-300" : "border-zinc-200 bg-white text-zinc-800"
        }`}
      >
        <option value="">{enabled === false ? "未启用（不参与匹配）" : `选择${label}字段…`}</option>
        {options.map((f) => (
          <option key={f} value={f}>
            {f}
            {shared(f) ? "（两表共有/相似）" : "（仅一表）"}
          </option>
        ))}
      </select>
      {value && shared(value) && (
        <div className="mt-1 flex items-center gap-0.5 text-[10.5px] text-blue-600">
          <Sparkles size={9} /> 两表共有/相似字段，AI 推荐优先匹配
        </div>
      )}
    </div>
  );
}

function SummaryRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline gap-3 text-[13px]">
      <span className="w-20 shrink-0 text-zinc-400">{label}</span>
      <span className="min-w-0 break-all font-medium text-zinc-800">{value || "—"}</span>
    </div>
  );
}
