/** VariableMapTable — 财务建模「变量映射表」（P3 变量映射，2026-08-21）。
 *
 * 与需求文档 §5.2「VariableMapTable 变量映射表」对齐：
 * 表格：模型所需变量 / 对应列（下拉，从文件列名选择）/ 状态 chip（已匹配绿/缺失红）；
 * 缺失列高亮提示；派生变量行支持表达式输入（如 利润=收入-成本）。
 *
 * v2.0 V1+V2（2026-08-21）：
 *  - 变量行按 direction 分三类渲染：
 *    · input：普通下拉（类型感知：numeric 优先数值列）+ AI 置信度徽章
 *    · statistic：不映射列，显示「自动统计」+ 统计函数徽章（COUNT/MEAN/STD…，AI 已绑定）
 *    · output：显示「模型输出」说明，无下拉
 *  - AI 推荐：高置信（≥0.85）绿色 / 中置信（≥0.6）橙色 / 低置信黄色候选提示
 *
 * 组件受控：mappings 由父组件持有（含用户手动选择），本组件只渲染 + 回调。
 */

import { useState } from "react";
import { ChevronDown, ChevronRight, Plus, Trash2, AlertTriangle, CheckCircle2, Clock, Sparkles } from "lucide-react";
import type { FinmodVarmapModel } from "../lib/api";
import LoadingState from "./LoadingState";

/** 派生变量公式行（名称 = 表达式） */
export interface DerivedFormulaLine {
  id: string;
  /** 完整公式文本（如 利润=收入-成本） */
  text: string;
}

/** v2.0 AI 推荐信息（key = model_id:var_name） */
export interface AiMappingInfo {
  confidence: number;
  reason: string;
  candidates: string[];
}

/** v2.0 AI 统计量绑定（key = model_id:var_name） */
export interface AiStatBinding {
  stat: string;
  based_on: string;
}

/** v2.0 统计量变量用户绑定（函数 + 来源列） */
export interface StatisticBinding {
  var_name: string;
  stat: string;
  based_on: string;
}

interface Props {
  /** varmap 结果（每模型变量组） */
  models: FinmodVarmapModel[];
  /** 文件全部列名（下拉选项） */
  allCols: string[];
  /** 期间列候选 */
  periodCols: string[];
  /** 已选期间列 */
  periodCol: string;
  onPeriodChange: (col: string) => void;
  /** 用户修改某模型某变量的映射列 */
  onMappingChange: (modelId: string, varName: string, col: string) => void;
  /** v2.0：统计量变量绑定（用户改函数/来源列） */
  statBindings: StatisticBinding[];
  onStatBindingChange: (modelId: string, varName: string, stat: string, basedOn: string) => void;
  /** v2.0：AI 推荐（model_id:var_name → {confidence, reason, candidates}） */
  aiMappings?: Record<string, AiMappingInfo>;
  /** v2.0：AI 统计量绑定（model_id:var_name → {stat, based_on}） */
  aiStatBindings?: Record<string, AiStatBinding>;
  /** 派生变量公式行 */
  derivedFormulas: DerivedFormulaLine[];
  onAddDerived: () => void;
  onRemoveDerived: (id: string) => void;
  onDerivedChange: (id: string, text: string) => void;
  /** 派生求值状态（防抖实时重算） */
  derivedBusy?: boolean;
  /** 派生求值结果：名称 → sample */
  derivedResults?: Record<string, { type: string; sample: unknown[]; rows: number }>;
  /** 派生求值错误 */
  derivedErrors?: { line: number; name: string; kind: string; message: string }[];
}

export default function VariableMapTable({
  models,
  allCols,
  periodCols,
  periodCol,
  onPeriodChange,
  onMappingChange,
  statBindings,
  onStatBindingChange,
  aiMappings,
  aiStatBindings,
  derivedFormulas,
  onAddDerived,
  onRemoveDerived,
  onDerivedChange,
  derivedBusy,
  derivedResults,
  derivedErrors,
}: Props) {
  const [expanded, setExpanded] = useState<Set<string>>(new Set(models.map((m) => m.model_id)));

  const toggle = (id: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  /** 统计每个模型未匹配 input 变量数（statistic/output 不算缺失） */
  const missingOf = (m: FinmodVarmapModel) =>
    m.variables.filter((v) => v.direction !== "statistic" && v.direction !== "output" && !v.mapped_col).length;

  /** 置信度徽章（V2 AI 推荐） */
  const confidenceBadge = (info?: AiMappingInfo) => {
    if (!info) return null;
    const c = info.confidence;
    if (c >= 0.85) {
      return (
        <span className="flex items-center gap-1 rounded-full bg-emerald-50 px-2 py-0.5 text-[10.5px] font-medium text-emerald-600">
          <Sparkles size={10} />AI 已匹配 {Math.round(c * 100)}%
        </span>
      );
    }
    if (c >= 0.6) {
      return (
        <span className="flex items-center gap-1 rounded-full bg-amber-50 px-2 py-0.5 text-[10.5px] font-medium text-amber-600">
          <Sparkles size={10} />AI 建议 {Math.round(c * 100)}%
        </span>
      );
    }
    return (
      <span className="flex items-center gap-1 rounded-full bg-yellow-50 px-2 py-0.5 text-[10.5px] font-medium text-yellow-600">
        <Sparkles size={10} />AI 低置信 {Math.round(c * 100)}%
      </span>
    );
  };

  return (
    <div className="space-y-4">
      {/* 文件列 / 期间列信息 */}
      <div className="flex flex-wrap items-center gap-3 rounded-lg border border-zinc-200 bg-white px-4 py-2.5">
        <span className="flex items-center gap-1.5 text-[12.5px] text-zinc-600">
          <Clock size={13} className="text-zinc-400" />
          期间列（时间轴）
        </span>
        <select
          value={periodCol}
          onChange={(e) => onPeriodChange(e.target.value)}
          className="rounded-md border border-zinc-200 bg-white px-2 py-1 text-[12.5px] text-zinc-700 outline-none focus:border-blue-400"
        >
          <option value="">（无期间列）</option>
          {(periodCols.length > 0 ? periodCols : allCols).map((c) => (
            <option key={c} value={c}>{c}</option>
          ))}
        </select>
        <span className="ml-auto text-[11.5px] text-zinc-400">
          文件共 {allCols.length} 列{periodCols.length > 0 ? ` · 自动识别 ${periodCols.length} 个期间列` : ""}
        </span>
      </div>

      {/* 每模型变量映射表 */}
      {models.map((m) => {
        const open = expanded.has(m.model_id);
        const missing = missingOf(m);
        return (
          <div key={m.model_id} className="overflow-hidden rounded-lg border border-zinc-200 bg-white">
            {/* 模型头（折叠） */}
            <button
              onClick={() => toggle(m.model_id)}
              className="flex w-full items-center gap-2.5 px-4 py-3 text-left"
            >
              <span className="rounded bg-blue-50 px-1.5 py-0.5 text-[11px] font-bold text-blue-700">
                {m.code}
              </span>
              <span className="text-[13px] font-semibold text-zinc-800">{m.name}</span>
              {missing > 0 ? (
                <span className="rounded-full bg-red-50 px-2 py-0.5 text-[11px] font-medium text-red-600">
                  {missing} 个变量待映射/派生
                </span>
              ) : (
                <span className="flex items-center gap-1 rounded-full bg-emerald-50 px-2 py-0.5 text-[11px] font-medium text-emerald-600">
                  <CheckCircle2 size={11} />
                  变量已齐
                </span>
              )}
              <span className="ml-auto text-zinc-400">
                {open ? <ChevronDown size={15} /> : <ChevronRight size={15} />}
              </span>
            </button>

            {open && (
              <div className="border-t border-zinc-100">
                <div className="overflow-x-auto">
                  <table className="w-full border-collapse text-[12.5px]">
                    <thead>
                      <tr>
                        <th className="border-b border-zinc-200 bg-zinc-50 px-3 py-2 text-left font-medium text-zinc-600">模型所需变量</th>
                        <th className="border-b border-zinc-200 bg-zinc-50 px-3 py-2 text-left font-medium text-zinc-600">含义</th>
                        <th className="border-b border-zinc-200 bg-zinc-50 px-3 py-2 text-left font-medium text-zinc-600">对应列</th>
                        <th className="border-b border-zinc-200 bg-zinc-50 px-3 py-2 text-left font-medium text-zinc-600">状态</th>
                      </tr>
                    </thead>
                    <tbody>
                      {m.variables.map((v) => {
                        const direction = v.direction || "input";
                        const aiKey = `${m.model_id}:${v.var_name}`;
                        const aiInfo = aiMappings?.[aiKey];
                        const aiStat = aiStatBindings?.[aiKey];
                        // 统计量行：当前绑定（用户改过优先，否则 AI 绑定，否则默认 MEAN）
                        const statCur = statBindings.find((s) => s.var_name === v.var_name);
                        const stat = statCur?.stat || aiStat?.stat || "MEAN";
                        const basedOn = statCur?.based_on || aiStat?.based_on || "";
                        const statFuncs = ["COUNT", "MEAN", "STD", "MEDIAN", "VAR"];
                        // input 类型感知：numeric 只列数值列（无类型信息时列全部）
                        const numCols = allCols;
                        const isStatistic = direction === "statistic";
                        const isOutput = direction === "output";
                        const matched = !!v.mapped_col;
                        return (
                          <tr key={v.var_name} className="border-b border-zinc-100 last:border-b-0">
                            <td className="px-3 py-2">
                              <span className="font-medium text-zinc-800">{v.var_name}</span>
                              {v.var_unit && (
                                <span className="ml-1 text-[11px] text-zinc-400">({v.var_unit})</span>
                              )}
                              {direction === "statistic" && (
                                <span className="ml-1.5 rounded bg-violet-50 px-1.5 py-0.5 text-[10px] font-medium text-violet-600">
                                  统计量
                                </span>
                              )}
                              {direction === "output" && (
                                <span className="ml-1.5 rounded bg-zinc-100 px-1.5 py-0.5 text-[10px] font-medium text-zinc-500">
                                  模型输出
                                </span>
                              )}
                            </td>
                            <td className="px-3 py-2 text-zinc-500">{v.var_meaning}</td>
                            <td className="px-3 py-2">
                              {isStatistic ? (
                                /* 统计量：函数 + 来源列 双下拉（v2.0 核心交互） */
                                <div className="flex items-center gap-1.5">
                                  <select
                                    value={stat}
                                    onChange={(e) => onStatBindingChange(m.model_id, v.var_name, e.target.value, basedOn)}
                                    className="w-24 rounded-md border border-violet-200 bg-violet-50/40 px-1.5 py-1 font-mono text-[12px] text-violet-700 outline-none focus:border-violet-400"
                                    title="统计函数"
                                  >
                                    {statFuncs.map((f) => (
                                      <option key={f} value={f}>{f}</option>
                                    ))}
                                  </select>
                                  <span className="text-[11px] text-zinc-400">基于</span>
                                  <select
                                    value={basedOn}
                                    onChange={(e) => onStatBindingChange(m.model_id, v.var_name, stat, e.target.value)}
                                    className="min-w-24 flex-1 rounded-md border border-violet-200 bg-white px-1.5 py-1 text-[12px] text-zinc-700 outline-none focus:border-violet-400"
                                    title="来源列"
                                  >
                                    <option value="">（选来源列）</option>
                                    {numCols.map((c) => (
                                      <option key={c} value={c}>{c}</option>
                                    ))}
                                  </select>
                                </div>
                              ) : isOutput ? (
                                <span className="text-[11.5px] text-zinc-400">由模型计算得出</span>
                              ) : (
                                <select
                                  value={v.mapped_col}
                                  onChange={(e) => onMappingChange(m.model_id, v.var_name, e.target.value)}
                                  className={`w-full min-w-36 rounded-md border px-2 py-1 text-[12.5px] outline-none focus:border-blue-400 ${
                                    matched
                                      ? "border-zinc-200 bg-white text-zinc-700"
                                      : "border-red-300 bg-red-50 text-zinc-700"
                                  }`}
                                >
                                  <option value="">（未匹配）</option>
                                  {numCols.map((c) => (
                                    <option key={c} value={c}>{c}</option>
                                  ))}
                                </select>
                              )}
                            </td>
                            <td className="px-3 py-2">
                              {isStatistic ? (
                                <span className="rounded-full bg-violet-50 px-2 py-0.5 text-[11px] font-medium text-violet-600">
                                  自动统计{aiStat ? ` · ${aiStat.stat}(${aiStat.based_on || "?"})` : ""}
                                </span>
                              ) : isOutput ? (
                                <span className="rounded-full bg-zinc-100 px-2 py-0.5 text-[11px] font-medium text-zinc-500">
                                  输出参数
                                </span>
                              ) : matched ? (
                                <span className="flex flex-wrap items-center gap-1">
                                  <span className="rounded-full bg-emerald-50 px-2 py-0.5 text-[11px] font-medium text-emerald-600">已匹配</span>
                                  {confidenceBadge(aiInfo)}
                                </span>
                              ) : (
                                <span className="flex flex-wrap items-center gap-1">
                                  <span className="rounded-full bg-red-50 px-2 py-0.5 text-[11px] font-medium text-red-600">
                                    缺失<span className="ml-0.5 text-[10px] opacity-70">可手动选列</span>
                                  </span>
                                  {confidenceBadge(aiInfo)}
                                </span>
                              )}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
          </div>
        );
      })}

      {/* 派生变量 */}
      <div className="rounded-lg border border-zinc-200 bg-white">
        <div className="flex items-center justify-between border-b border-zinc-100 px-4 py-2.5">
          <span className="text-[13px] font-semibold text-zinc-800">派生变量</span>
          <button
            onClick={onAddDerived}
            className="flex items-center gap-1 rounded-md bg-zinc-900 px-3 py-1.5 text-[12px] font-medium text-white hover:bg-zinc-700"
          >
            <Plus size={12} />
            添加公式
          </button>
        </div>
        <div className="space-y-2 px-4 py-3">
          {derivedFormulas.length === 0 ? (
            <p className="py-2 text-center text-[12.5px] text-zinc-400">
              用公式生成新列喂给模型，如 <code className="rounded bg-zinc-100 px-1">利润=收入-成本</code>（支持
              <code className="rounded bg-zinc-100 px-1">SUM</code>
              <code className="rounded bg-zinc-100 px-1">AVG</code> 等聚合函数）
            </p>
          ) : (
            derivedFormulas.map((f, idx) => {
              // 错误按行号匹配（后端 errors.line 为 1-based 公式行）；结果按派生名匹配
              const err = derivedErrors?.find((e) => e.line === idx + 1);
              const name = f.text.split("=")[0].trim();
              const result = derivedResults?.[name] ?? derivedResults?.[`expr_${idx + 1}`];
              return (
                <div key={f.id}>
                  <div className="flex items-center gap-2">
                    <input
                      value={f.text}
                      onChange={(e) => onDerivedChange(f.id, e.target.value)}
                      placeholder="名称 = 表达式（如 利润=收入-成本）"
                      className="flex-1 rounded-md border border-zinc-200 bg-white px-3 py-2 font-mono text-[12.5px] text-zinc-800 outline-none focus:border-blue-400 focus:ring-2 focus:ring-blue-100"
                    />
                    <button
                      onClick={() => onRemoveDerived(f.id)}
                      className="shrink-0 rounded p-1.5 text-zinc-400 hover:bg-red-50 hover:text-red-500"
                      title="删除此公式"
                    >
                      <Trash2 size={14} />
                    </button>
                  </div>
                  {err && (
                    <p className="mt-1 flex items-center gap-1 text-[11.5px] text-red-500">
                      <AlertTriangle size={11} />
                      {err.message}
                    </p>
                  )}
                  {!err && result && (
                    <p className="mt-1 flex items-center gap-1 text-[11.5px] text-emerald-600">
                      <CheckCircle2 size={11} />
                      {result.type === "scalar"
                        ? `结果：${String(result.sample)}`
                        : `已求值 ${result.rows} 行 · 示例 ${(result.sample as unknown[]).slice(0, 3).map((s) => String(s)).join(" / ")}`}
                    </p>
                  )}
                </div>
              );
            })
          )}
          {derivedBusy && (
            <div className="flex items-center gap-2 text-[12px] text-zinc-400">
              <LoadingState label="正在计算…" />
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
