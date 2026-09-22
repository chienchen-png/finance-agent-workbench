/** ChartManifest — 财务建模「图表确认清单」（P4 图表配置，2026-08-21）。

 * 与需求文档 §四 步骤 5「确认清单」对齐：收敛为 chart_manifest[]——
 * 模板名 + 变体 + 数据口径 + color_scheme（配色，宏观选择后写入）+ 数据源列 +
 * 预览缩略，可增删/排序/改配色。
 *
 * 组件受控：manifest 由父组件持有，本组件只渲染 + 回调。
 */

import { ArrowDown, ArrowUp, Trash2 } from "lucide-react";
import type { FinmodChartManifestItem } from "../lib/api";

/** 配色方案选项（与 chart-style.md / generate_chart color_scheme 一致） */
export const COLOR_SCHEMES = [
  { key: "auto", label: "自动" },
  { key: "blues", label: "蓝色系" },
  { key: "greens", label: "绿色系" },
  { key: "reds", label: "红色系" },
  { key: "oranges", label: "橙色系" },
  { key: "purples", label: "紫色系" },
  { key: "blacks", label: "黑灰系" },
];

interface Props {
  manifest: FinmodChartManifestItem[];
  onRemove: (id: string) => void;
  onMove: (id: string, dir: -1 | 1) => void;
  /** v6.12：变体已锁定（前面选图时定好），确认清单不再改变体；仅保留配色。 */
  onVariantChange?: (id: string, variant: string) => void;
  onColorChange: (id: string, color: string) => void;
}

export default function ChartManifest({
  manifest,
  onRemove,
  onMove,
  onColorChange,
}: Props) {
  if (manifest.length === 0) {
    return (
      <div className="rounded-lg border border-dashed border-zinc-300 bg-white px-4 py-6 text-center text-[12.5px] text-zinc-400">
        还没有确认图表——至少选择 1 张图才能继续
      </div>
    );
  }
  return (
    <div className="space-y-2">
      {manifest.map((item, idx) => (
        <div
          key={item.id}
          className="flex items-center gap-3 rounded-lg border border-zinc-200 bg-white px-3 py-2.5"
        >
          {/* 序号徽章（左）—— 已删缩略图预览（v6.11：上方图表库已有大图预览，清单不再重复缩略） */}
          <span className="shrink-0 rounded bg-blue-50 px-1.5 py-0.5 text-[11px] font-bold text-blue-700">
            {idx + 1}
          </span>

          {/* 图表信息（中） */}
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <span className="truncate text-[13px] font-semibold text-zinc-800">{item.name}</span>
              <span className="font-mono text-[10.5px] text-zinc-400">{item.variant}</span>
              <span
                className={`rounded px-1.5 py-0.5 text-[10px] font-bold ${
                  item.level === "L1" ? "bg-emerald-50 text-emerald-700"
                    : item.level === "L2" ? "bg-blue-50 text-blue-700"
                      : "bg-violet-50 text-violet-700"
                }`}
              >
                {item.level}
              </span>
            </div>
            <div className="mt-1.5 flex flex-wrap items-center gap-3">
              {/* 变体（v6.12：锁定只读——前面选图时已定好，此处仅展示） */}
              <span className="flex items-center gap-1.5 text-[11px] text-zinc-500">
                变体
                <span className="rounded border border-zinc-200 bg-zinc-50 px-1.5 py-0.5 font-mono text-[11.5px] text-zinc-600">
                  {item.variant || item.template}
                </span>
              </span>
              {/* 配色（宏观写入；确认清单仅保留配色可改） */}
              <label className="flex items-center gap-1.5 text-[11px] text-zinc-500">
                配色
                <select
                  value={item.color_scheme || "auto"}
                  onChange={(e) => onColorChange(item.id, e.target.value)}
                  className="rounded border border-zinc-200 bg-white px-1.5 py-0.5 text-[11.5px] text-zinc-700 outline-none focus:border-blue-400"
                >
                  {COLOR_SCHEMES.map((c) => (
                    <option key={c.key} value={c.key}>{c.label}</option>
                  ))}
                </select>
              </label>
              {/* 数据口径（数据源列展示） */}
              {item.data_source && item.data_source.length > 0 && (
                <span className="text-[10.5px] text-zinc-400">
                  数据：{item.data_source.join(" · ")}
                </span>
              )}
              {item.reason && (
                <span className="text-[10.5px] text-zinc-400">{item.reason}</span>
              )}
            </div>
          </div>

          {/* 操作（右）：排序 + 移除 */}
          <div className="flex shrink-0 flex-col items-end gap-1">
            <div className="flex gap-0.5">
              <button
                onClick={() => onMove(item.id, -1)}
                disabled={idx === 0}
                className="rounded p-1 text-zinc-400 hover:bg-zinc-100 hover:text-zinc-600 disabled:opacity-30"
                title="上移"
              >
                <ArrowUp size={13} />
              </button>
              <button
                onClick={() => onMove(item.id, 1)}
                disabled={idx === manifest.length - 1}
                className="rounded p-1 text-zinc-400 hover:bg-zinc-100 hover:text-zinc-600 disabled:opacity-30"
                title="下移"
              >
                <ArrowDown size={13} />
              </button>
            </div>
            <button
              onClick={() => onRemove(item.id)}
              className="rounded p-1 text-zinc-400 hover:bg-red-50 hover:text-red-500"
              title="移除"
            >
              <Trash2 size={14} />
            </button>
          </div>
        </div>
      ))}
    </div>
  );
}
