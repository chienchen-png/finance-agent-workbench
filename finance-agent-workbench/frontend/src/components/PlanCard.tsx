/** PlanCard — 对话流内联计划卡片（项目架构文档 4.2：替代常驻任务面板）。
 *
 * 展示 smol/legacy 引擎产出的计划步骤，可折叠；步骤状态实时更新。
 * 数据来源：plan_proposed / plan_updated 事件。
 */

import { useState } from "react";
import { ListChecks, ChevronDown, CheckCircle2, Circle, Loader2 } from "lucide-react";

export interface PlanStep {
  id?: string;
  title?: string;
  status?: "pending" | "running" | "completed" | "failed";
  weight?: number;
}

export default function PlanCard({ steps }: { steps: PlanStep[] }) {
  const [open, setOpen] = useState(true);
  if (!steps.length) return null;

  return (
    <div className="my-2 rounded-lg border border-zinc-200 bg-white overflow-hidden">
      <button
        className="flex w-full items-center gap-2 px-3 py-2 text-left text-[13px] font-medium text-zinc-700 hover:bg-zinc-50"
        onClick={() => setOpen((o) => !o)}
      >
        <ListChecks size={14} className="text-blue-600" />
        <span>执行计划</span>
        <span className="text-[11px] text-zinc-400">{steps.length} 步</span>
        <ChevronDown size={14} className={`ml-auto transition-transform ${open ? "" : "-rotate-90"}`} />
      </button>
      {open && (
        <div className="space-y-1 border-t border-zinc-100 px-3 py-2">
          {steps.map((s, i) => (
            <div key={s.id || i} className="flex items-center gap-2 py-0.5 text-[12.5px]">
              {s.status === "completed" ? (
                <CheckCircle2 size={14} className="shrink-0 text-green-600" />
              ) : s.status === "running" ? (
                <Loader2 size={14} className="shrink-0 animate-spin text-blue-600" />
              ) : s.status === "failed" ? (
                <Circle size={14} className="shrink-0 text-red-500" />
              ) : (
                <Circle size={14} className="shrink-0 text-zinc-300" />
              )}
              <span className={s.status === "completed" ? "text-zinc-500" : "text-zinc-700"}>
                {i + 1}. {s.title || "步骤"}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
