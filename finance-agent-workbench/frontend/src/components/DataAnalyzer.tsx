/** DataAnalyzer — 财务建模「数据分析器」（P5 执行引擎，2026-08-21）。

 * 与需求文档 §5.2「DataAnalyzer 数据分析器」对齐：步骤 6 内嵌折叠 + 可独立弹窗；
 * 左公式编辑器（多行 `名称=表达式` + 列名 chips 自动补全 + 防抖实时重算）
 * + 右结果表（分页/千分位）+ 行内错误红字。
 *
 * 本质 = 面向非工程师的轻量数据分析器（类 Excel 公式，作用于整列，支持聚合）。
 * 后端 POST /analyze（_finmod_eval 求值，0 LLM）。
 */

import { useEffect, useRef, useState } from "react";
import { Plus, Trash2, CheckCircle2, AlertTriangle } from "lucide-react";
import type { FinmodAnalyzeResult } from "../lib/api";
import { finmodAnalyze } from "../lib/api";
import LoadingState from "./LoadingState";

interface Props {
  projectId: string;
  fileName: string;
  /** 可用列名（chips 自动补全） */
  allCols: string[];
}

interface FormulaLine {
  id: string;
  text: string;
}

export default function DataAnalyzer({ projectId, fileName, allCols }: Props) {
  const [formulas, setFormulas] = useState<FormulaLine[]>([{ id: `f${Date.now()}`, text: "" }]);
  const [result, setResult] = useState<FinmodAnalyzeResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  // 防抖 300ms 实时重算
  const timer = useRef<number | null>(null);

  const run = async (fs: FormulaLine[]) => {
    const texts = fs.map((f) => f.text).filter((t) => t.trim());
    if (texts.length === 0) {
      setResult(null);
      setError("");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const r = await finmodAnalyze(projectId, fileName, texts);
      setResult(r);
    } catch (e) {
      setError((e as Error).message || "求值失败");
    } finally {
      setBusy(false);
    }
  };

  useEffect(() => {
    if (timer.current) window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => { void run(formulas); }, 300);
    return () => { if (timer.current) window.clearTimeout(timer.current); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [formulas]);

  const change = (id: string, text: string) =>
    setFormulas((prev) => prev.map((f) => (f.id === id ? { ...f, text } : f)));
  const add = () => setFormulas((prev) => [...prev, { id: `f${Date.now()}`, text: "" }]);
  const remove = (id: string) => setFormulas((prev) => prev.filter((f) => f.id !== id));
  const insertCol = (col: string) => {
    setFormulas((prev) => {
      const last = prev[prev.length - 1];
      if (!last) return prev;
      return prev.map((f, i) => (i === prev.length - 1 ? { ...f, text: f.text + col } : f));
    });
  };

  // 数值千分位
  const fmt = (v: unknown): string => {
    if (v == null) return "—";
    if (typeof v === "number") return v.toLocaleString("zh-CN", { maximumFractionDigits: 2 });
    return String(v);
  };

  return (
    <div className="rounded-lg border border-zinc-200 bg-white">
      <div className="flex items-center justify-between border-b border-zinc-100 px-4 py-2.5">
        <span className="text-[13px] font-semibold text-zinc-800">数据分析器</span>
        <span className="text-[11px] text-zinc-400">自由计算 · 公式作用于整列 · 支持聚合（SUM/AVG/…）</span>
        <button
          onClick={add}
          className="flex items-center gap-1 rounded-md bg-zinc-900 px-3 py-1.5 text-[12px] font-medium text-white hover:bg-zinc-700"
        >
          <Plus size={12} />
          添加公式
        </button>
      </div>

      <div className="grid grid-cols-1 gap-0 lg:grid-cols-2">
        {/* 左：公式编辑器 */}
        <div className="border-b border-zinc-100 p-4 lg:border-b-0 lg:border-r">
          <div className="mb-2 flex flex-wrap gap-1">
            <span className="mr-1 self-center text-[11px] text-zinc-400">列名：</span>
            {(allCols || []).slice(0, 12).map((c) => (
              <button
                key={c}
                onClick={() => insertCol(c)}
                className="rounded bg-zinc-100 px-1.5 py-0.5 font-mono text-[10.5px] text-zinc-600 hover:bg-blue-100 hover:text-blue-700"
                title="点击插入列名"
              >
                {c}
              </button>
            ))}
            {(allCols || []).length > 12 && (
              <span className="self-center text-[10px] text-zinc-400">+{(allCols || []).length - 12}</span>
            )}
          </div>
          <div className="space-y-2">
            {formulas.map((f, idx) => {
              const err = result?.errors.find((e) => e.line === idx + 1);
              const name = f.text.split("=")[0].trim();
              const res = result?.results[name];
              return (
                <div key={f.id}>
                  <div className="flex items-center gap-2">
                    <input
                      value={f.text}
                      onChange={(e) => change(f.id, e.target.value)}
                      placeholder="名称 = 表达式（如 利润=收入-成本 / 总额=SUM(收入)）"
                      className="flex-1 rounded-md border border-zinc-200 bg-white px-3 py-2 font-mono text-[12.5px] text-zinc-800 outline-none focus:border-blue-400 focus:ring-2 focus:ring-blue-100"
                    />
                    <button
                      onClick={() => remove(f.id)}
                      className="shrink-0 rounded p-1.5 text-zinc-400 hover:bg-red-50 hover:text-red-500"
                      title="删除公式"
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
                  {!err && res && (
                    <p className="mt-1 flex items-center gap-1 text-[11.5px] text-emerald-600">
                      <CheckCircle2 size={11} />
                      {res.type === "scalar"
                        ? `结果：${fmt(res.sample)}`
                        : `已求值 ${res.rows} 行 · 示例 ${(res.sample as unknown[]).slice(0, 3).map((s) => fmt(s)).join(" / ")}`}
                    </p>
                  )}
                </div>
              );
            })}
          </div>
          {busy && (
            <div className="mt-2 flex items-center gap-2 text-[12px] text-zinc-400">
              <LoadingState label="正在计算…" />
            </div>
          )}
          {error && (
            <p className="mt-2 flex items-center gap-1 text-[11.5px] text-red-500">
              <AlertTriangle size={11} />
              {error}
            </p>
          )}
          <p className="mt-3 text-[11px] text-zinc-400">
            支持：四则运算、括号、比较、聚合（SUM/AVG/MAX/MIN/COUNT）、逐行（ROUND/ABS/IF）。
            前序公式结果可被后序引用。
          </p>
        </div>

        {/* 右：结果表 */}
        <div className="max-h-96 overflow-auto p-4">
          {!result || result.rows.length === 0 ? (
            <p className="py-8 text-center text-[12.5px] text-zinc-400">
              输入公式开始计算——结果表将显示在这里
            </p>
          ) : (
            <table className="w-full border-collapse text-[12px]">
              <thead className="sticky top-0">
                <tr>
                  {(result.columns || []).slice(0, 12).map((c) => (
                    <th key={c} className="border-b border-zinc-200 bg-zinc-50 px-2 py-1.5 text-left font-medium text-zinc-600">
                      {c}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {result.rows.map((row, i) => (
                  <tr key={i} className="border-b border-zinc-100 last:border-b-0">
                    {(result.columns || []).slice(0, 12).map((c) => (
                      <td key={c} className="px-2 py-1 text-zinc-700">{fmt(row[c])}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </div>
  );
}
