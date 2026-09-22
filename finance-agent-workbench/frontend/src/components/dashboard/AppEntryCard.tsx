/** AppEntryCard — 工作台总览应用入口卡（D5）。
 *
 * 设计文档：`docs/工作台总览设计方案.md` §2.2 ⑤
 * - 显示应用图标/名称/描述 + 应用内 run 数 + 累计使用时长
 * - 点击 → 直接进入对应应用视图（onNavigate）
 */

import { ArrowUpRight } from "lucide-react";
import { formatDuration } from "../../pages/DashboardPage";

export default function AppEntryCard({
  id,
  name,
  desc,
  runs,
  durationSec,
  onNavigate,
}: {
  id: string;
  name: string;
  desc: string;
  runs: number;
  durationSec: number;
  onNavigate: (view: string) => void;
}) {
  return (
    <button
      onClick={() => onNavigate(id)}
      className="group flex w-full items-center justify-between rounded-xl border border-zinc-100 px-3.5 py-2.5 text-left transition-all hover:border-blue-200 hover:bg-blue-50/60"
    >
      <span className="min-w-0">
        <span className="flex items-center gap-1.5">
          <span className="block truncate text-[13px] font-medium text-zinc-700 transition-colors group-hover:text-blue-700">
            {name}
          </span>
          <ArrowUpRight size={13} className="shrink-0 text-zinc-300 transition-colors group-hover:text-blue-500" />
        </span>
        <span className="mt-0.5 block truncate text-[11px] text-zinc-400">{desc}</span>
      </span>
      <span className="ml-3 shrink-0 text-right text-[11px] text-zinc-400">
        <span className="block">{runs} 次运行</span>
        <span className="mt-0.5 block tabular-nums text-zinc-500">{formatDuration(durationSec)}</span>
      </span>
    </button>
  );
}
