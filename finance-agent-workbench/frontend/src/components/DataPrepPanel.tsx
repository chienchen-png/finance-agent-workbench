/** DataPrepPanel — 财务建模「数据准备」折叠区（V3/V4，2026-08-21）。
 *
 * Stata/SPSS 式分析就绪流程：清洗 / 类型修正 / 多 sheet 合并 / 透视面板化。
 * 可视化操作卡（选操作 → 填参数 → 预览前 5 行 → 加入步骤链）；步骤链可删除/重排；
 * 实时调 `POST /api/apps/finmod/prep-data` 预览变换结果。
 *
 * 交互原则（V4 两类用户）：
 *  - 无基础：AI 已给建议步骤（props.aiSuggestions）→ 一键应用 → 直接下一步
 *  - 有基础：手动添加/调整操作卡，实时预览
 */

import { useState } from "react";
import { Plus, Trash2, AlertTriangle, Table as TableIcon, Sparkles, Wand2, ChevronDown, ChevronUp } from "lucide-react";
import type { FinmodPrepStep, FinmodPrepResult } from "../lib/api";
import LoadingState from "./LoadingState";

interface Props {
  /** 当前数据文件列名（操作卡下拉用） */
  allCols: string[];
  /** 文件全部 sheet 名（合并操作用） */
  sheetNames: string[];
  /** 已应用步骤链 */
  steps: FinmodPrepStep[];
  onChangeSteps: (steps: FinmodPrepStep[]) => void;
  /** AI 建议步骤（V3 可选：LLM 生成） */
  aiSuggestions?: FinmodPrepStep[];
  /** 预览结果（父组件持有，防抖触发） */
  result?: FinmodPrepResult | null;
  busy?: boolean;
}

const OP_LABELS: Record<string, string> = {
  clean: "清洗",
  cast: "类型修正",
  merge: "合并",
  pivot: "透视/面板化",
};

export default function DataPrepPanel({
  allCols,
  sheetNames,
  steps,
  onChangeSteps,
  aiSuggestions,
  result,
  busy,
}: Props) {
  const [open, setOpen] = useState(false);
  const [op, setOp] = useState<"clean" | "cast" | "merge" | "pivot">("clean");
  // clean 子参数
  const [cleanAction, setCleanAction] = useState("filter");
  const [cleanCol, setCleanCol] = useState(allCols[0] || "");
  const [cleanOp, setCleanOp] = useState("gt");
  const [cleanVal, setCleanVal] = useState("0");
  // cast 参数
  const [castCol, setCastCol] = useState(allCols[0] || "");
  const [castTo, setCastTo] = useState("numeric");
  // merge 参数
  const [mergeSheets, setMergeSheets] = useState<string[]>(sheetNames.slice(0, 2));
  const [mergeHow, setMergeHow] = useState("concat");
  const [mergeOn, setMergeOn] = useState("");
  // pivot 参数
  const [pivotMode, setPivotMode] = useState("long");
  const [pivotIndex, setPivotIndex] = useState("");
  const [pivotColumns, setPivotColumns] = useState("");
  const [pivotValues, setPivotValues] = useState("");

  const addStep = () => {
    const step: FinmodPrepStep = { op };
    if (op === "clean") {
      step.action = cleanAction;
      if (cleanAction === "filter" || cleanAction === "replace") {
        step.where = { col: cleanCol, op: cleanOp, value: Number(cleanVal) };
      } else if (cleanAction === "dedup") {
        // 全部列去重
      }
      if (cleanAction === "replace") step.with = null;
    } else if (op === "cast") {
      step.col = castCol;
      step.to = castTo;
    } else if (op === "merge") {
      step.sheets = mergeSheets.length ? mergeSheets : sheetNames.slice(0, 2);
      step.how = mergeHow;
      if (mergeHow === "join" && mergeOn) step.on = [mergeOn];
    } else if (op === "pivot") {
      step.mode = pivotMode;
      if (pivotMode === "long") {
        step.id_vars = [pivotIndex].filter(Boolean);
        step.var_name = "变量";
        step.value_name = "值";
      } else {
        step.index = pivotIndex;
        step.columns = pivotColumns;
        step.values = pivotValues;
      }
    }
    onChangeSteps([...steps, step]);
  };

  const applyAi = () => {
    if (aiSuggestions && aiSuggestions.length > 0) {
      onChangeSteps(aiSuggestions);
    }
  };

  return (
    <div className="rounded-lg border border-zinc-200 bg-white">
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center gap-2 px-4 py-3 text-left"
      >
        <TableIcon size={14} className="text-zinc-400" />
        <span className="text-[13px] font-semibold text-zinc-800">数据准备（可选）</span>
        <span className="text-[11px] text-zinc-400">
          清洗 / 合并 / 透视 —— 整理成可直接分析的面板数据
        </span>
        {aiSuggestions && aiSuggestions.length > 0 && (
          <span className="rounded-full bg-violet-50 px-2 py-0.5 text-[10.5px] font-medium text-violet-600">
            <Sparkles size={10} className="mr-0.5 inline" />
            AI 建议 {aiSuggestions.length} 步
          </span>
        )}
        <span className="ml-auto flex items-center gap-1 text-[11.5px] text-zinc-400">
          {steps.length > 0 && (
            <span className="rounded-full bg-blue-50 px-2 py-0.5 font-medium text-blue-600">{steps.length} 步已应用</span>
          )}
          {open ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
        </span>
      </button>

      {open && (
        <div className="border-t border-zinc-100 px-4 py-3">
          {/* AI 建议一键应用 */}
          {aiSuggestions && aiSuggestions.length > 0 && (
            <div className="mb-3 flex items-center justify-between rounded-md border border-violet-200 bg-violet-50/50 px-3 py-2">
              <span className="text-[12px] text-violet-700">
                已识别需要整理数据（如合并多表/清理异常值），可一键应用或手动调整：
              </span>
              <button
                onClick={applyAi}
                className="flex items-center gap-1 rounded-md bg-violet-600 px-3 py-1.5 text-[12px] font-medium text-white hover:bg-violet-500"
              >
                <Wand2 size={12} />一键应用
              </button>
            </div>
          )}

          {/* 操作卡编辑器 */}
          <div className="flex flex-wrap items-center gap-2 rounded-md border border-zinc-200 bg-zinc-50/50 px-3 py-2.5">
            <select value={op} onChange={(e) => setOp(e.target.value as never)}
              className="rounded-md border border-zinc-200 bg-white px-2 py-1.5 text-[12.5px] text-zinc-700">
              {Object.entries(OP_LABELS).map(([k, v]) => (
                <option key={k} value={k}>{v}</option>
              ))}
            </select>

            {op === "clean" && (
              <>
                <select value={cleanAction} onChange={(e) => setCleanAction(e.target.value)}
                  className="rounded-md border border-zinc-200 bg-white px-2 py-1.5 text-[12.5px]">
                  <option value="filter">过滤行</option>
                  <option value="replace">替换异常值</option>
                  <option value="dedup">去重行</option>
                </select>
                {cleanAction !== "dedup" && (
                  <>
                    <select value={cleanCol} onChange={(e) => setCleanCol(e.target.value)}
                      className="rounded-md border border-zinc-200 bg-white px-2 py-1.5 text-[12.5px]">
                      {allCols.map((c) => <option key={c} value={c}>{c}</option>)}
                    </select>
                    <select value={cleanOp} onChange={(e) => setCleanOp(e.target.value)}
                      className="rounded-md border border-zinc-200 bg-white px-2 py-1.5 text-[12.5px]">
                      <option value="gt">&gt;</option><option value="gte">≥</option>
                      <option value="lt">&lt;</option><option value="lte">≤</option>
                      <option value="eq">=</option><option value="ne">≠</option>
                    </select>
                    <input value={cleanVal} onChange={(e) => setCleanVal(e.target.value)}
                      className="w-20 rounded-md border border-zinc-200 bg-white px-2 py-1.5 text-[12.5px]"
                      placeholder="值" />
                  </>
                )}
              </>
            )}

            {op === "cast" && (
              <>
                <select value={castCol} onChange={(e) => setCastCol(e.target.value)}
                  className="rounded-md border border-zinc-200 bg-white px-2 py-1.5 text-[12.5px]">
                  {allCols.map((c) => <option key={c} value={c}>{c}</option>)}
                </select>
                <select value={castTo} onChange={(e) => setCastTo(e.target.value)}
                  className="rounded-md border border-zinc-200 bg-white px-2 py-1.5 text-[12.5px]">
                  <option value="numeric">→ 数值</option>
                  <option value="date">→ 日期</option>
                  <option value="category">→ 分类</option>
                  <option value="text">→ 文本</option>
                </select>
              </>
            )}

            {op === "merge" && (
              <>
                <select value={mergeHow} onChange={(e) => setMergeHow(e.target.value)}
                  className="rounded-md border border-zinc-200 bg-white px-2 py-1.5 text-[12.5px]">
                  <option value="concat">纵向拼接</option>
                  <option value="join">横向按 key 合并</option>
                </select>
                {mergeHow === "join" && (
                  <input value={mergeOn} onChange={(e) => setMergeOn(e.target.value)}
                    className="w-28 rounded-md border border-zinc-200 bg-white px-2 py-1.5 text-[12.5px]"
                    placeholder="合并 key 列" />
                )}
                <span className="text-[11.5px] text-zinc-400">与</span>
                <select value={mergeSheets[1] || ""}
                  onChange={(e) => setMergeSheets([mergeSheets[0], e.target.value])}
                  className="max-w-44 rounded-md border border-zinc-200 bg-white px-2 py-1.5 text-[12.5px]">
                  {sheetNames.map((s) => <option key={s} value={s}>{s}</option>)}
                </select>
              </>
            )}

            {op === "pivot" && (
              <>
                <select value={pivotMode} onChange={(e) => setPivotMode(e.target.value)}
                  className="rounded-md border border-zinc-200 bg-white px-2 py-1.5 text-[12.5px]">
                  <option value="long">宽转长（堆叠）</option>
                  <option value="wide">长转宽（展开）</option>
                </select>
                <input value={pivotIndex} onChange={(e) => setPivotIndex(e.target.value)}
                  className="w-24 rounded-md border border-zinc-200 bg-white px-2 py-1.5 text-[12.5px]"
                  placeholder={pivotMode === "long" ? "保留列" : "索引列"} />
                {pivotMode === "wide" && (
                  <>
                    <input value={pivotColumns} onChange={(e) => setPivotColumns(e.target.value)}
                      className="w-24 rounded-md border border-zinc-200 bg-white px-2 py-1.5 text-[12.5px]"
                      placeholder="展开列" />
                    <input value={pivotValues} onChange={(e) => setPivotValues(e.target.value)}
                      className="w-24 rounded-md border border-zinc-200 bg-white px-2 py-1.5 text-[12.5px]"
                      placeholder="值列" />
                  </>
                )}
              </>
            )}

            <button
              onClick={addStep}
              className="flex items-center gap-1 rounded-md bg-zinc-900 px-3 py-1.5 text-[12px] font-medium text-white hover:bg-zinc-700"
            >
              <Plus size={12} />加入步骤
            </button>
          </div>

          {/* 步骤链 */}
          {steps.length > 0 && (
            <div className="mt-3 space-y-1.5">
              {steps.map((s, i) => (
                <div key={i} className="flex items-center gap-2 rounded-md border border-zinc-200 px-3 py-1.5 text-[12px]">
                  <span className="rounded bg-zinc-900 px-1.5 py-0.5 text-[10px] font-bold text-white">{i + 1}</span>
                  <span className="font-medium text-zinc-700">{OP_LABELS[s.op] || s.op}</span>
                  <span className="text-zinc-400">
                    {s.op === "clean" ? `${s.action} ${s.where?.col ?? ""} ${s.where?.op ?? ""} ${s.where?.value ?? ""}` :
                     s.op === "cast" ? `${s.col} → ${s.to}` :
                     s.op === "merge" ? `${s.how} ${(s.sheets || []).join(" + ")}` :
                     `mode=${s.mode}`}
                  </span>
                  <button onClick={() => onChangeSteps(steps.filter((_, j) => j !== i))}
                    className="ml-auto text-zinc-400 hover:text-red-500">
                    <Trash2 size={12} />
                  </button>
                </div>
              ))}
            </div>
          )}

          {/* 预览结果 */}
          {busy && (
            <div className="mt-3 flex items-center gap-2 text-[12px] text-zinc-400">
              <LoadingState label="正在预览变换结果…" />
            </div>
          )}
          {result && (
            <div className="mt-3">
              <div className="mb-1.5 flex items-center gap-2 text-[11.5px]">
                <TableIcon size={12} className="text-zinc-400" />
                <span className="text-zinc-500">预览（{result.rows} 行 · {result.columns.length} 列）</span>
                <span className="text-zinc-400">{result.logs.slice(-2).join("；")}</span>
                {result.errors.length > 0 && (
                  <span className="flex items-center gap-1 text-red-500">
                    <AlertTriangle size={11} />{result.errors.length} 步异常
                  </span>
                )}
              </div>
              <div className="overflow-x-auto rounded-md border border-zinc-200">
                <table className="w-full border-collapse text-[11.5px]">
                  <thead>
                    <tr>
                      {result.columns.map((c) => (
                        <th key={c.name} className="border-b border-zinc-200 bg-zinc-50 px-2 py-1 text-left font-medium text-zinc-600">
                          {c.name}
                          <span className="ml-1 text-[9px] text-zinc-400">{c.type}</span>
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {result.preview.map((row, i) => (
                      <tr key={i} className="border-b border-zinc-100 last:border-b-0">
                        {result.columns.map((c) => (
                          <td key={c.name} className="px-2 py-1 text-zinc-700">
                            {row[c.name] === null || row[c.name] === undefined ? "—" : String(row[c.name])}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
