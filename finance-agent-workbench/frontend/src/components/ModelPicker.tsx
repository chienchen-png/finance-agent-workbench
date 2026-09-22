/** ModelPicker — AI 模型选择器（2026-08-20 抽取为可复用组件）。
 *
 * 来源：ChatPage 的「模型徽标 + 按供应商分组下拉菜单」（阶段 7.9.2 设计）。
 * 现在 ChatPage 与集成应用（DataCheckAppPage）共用，保证全站模型选择 UI 统一：
 *   - 徽标按钮：官方 logo + 模型名 + chevron（hover 淡背景）
 *   - 下拉：按供应商分组，模型带 logo/默认徽标，向上弹出
 *
 * 语义：用户选择的模型 = 每次调用 AI 服务时请求的 API 模型；
 * 任务开始执行后默认一直用该模型；用户更改后下一次调用任务时用最新选择。
 */

import { useState } from "react";
import { ChevronDown } from "lucide-react";
import type { ModelOption } from "../lib/api";
import ModelIcon from "./ModelIcon";

/** 供应商（只用到 id/name 用于分组） */
export interface PickerProvider {
  id: string;
  name: string;
}

function ServerDot() {
  return (
    <svg viewBox="0 0 24 24" width="11" height="11" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="shrink-0">
      <rect x="2" y="2" width="20" height="8" rx="2" />
      <rect x="2" y="14" width="20" height="8" rx="2" />
      <path d="M6 6h.01M6 18h.01" />
    </svg>
  );
}

export default function ModelPicker({
  models,
  providers,
  value,
  onChange,
  disabled = false,
  /** 弹出方向：up（向上，默认，适合底部工具行）/ down（向下，适合顶部头部） */
  direction = "up",
}: {
  models: ModelOption[];
  providers: PickerProvider[];
  /** 当前选中模型 id */
  value: string;
  onChange: (m: ModelOption) => void;
  disabled?: boolean;
  direction?: "up" | "down";
}) {
  const [open, setOpen] = useState(false);
  const chatModels = models.filter((m) => m.type === "chat");
  const byProvider = providers
    .map((p) => ({ provider: p, models: chatModels.filter((m) => m.provider_id === p.id) }))
    .filter((g) => g.models.length > 0);
  const current = models.find((m) => m.id === value) || null;
  const currentProvider = providers.find((p) => p.id === current?.provider_id) || null;

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => !disabled && setOpen((o) => !o)}
        disabled={disabled}
        title={`当前模型：${current?.name || value}${currentProvider ? `（供应商：${currentProvider.name}）` : ""}，点击切换${disabled ? "（任务执行中不可切换）" : ""}`}
        className={`flex h-7 items-center gap-1.5 rounded-md px-2 text-[12px] transition-colors ${
          disabled ? "cursor-not-allowed opacity-50" : "text-zinc-500 hover:bg-zinc-100"
        }`}
      >
        <ModelIcon name={current?.name || value} icon={current?.icon} size={13} />
        <span className="max-w-40 truncate font-medium text-zinc-600">{current?.name || value}</span>
        <ChevronDown size={11} className="text-zinc-400" />
      </button>
      {open && (
        <>
          {/* 点击外部关闭 */}
          <div className="fixed inset-0 z-20" onClick={() => setOpen(false)} />
          {/* 弹出菜单（按供应商分组） */}
          <div
            className={`absolute left-0 z-30 max-h-72 w-64 overflow-y-auto rounded-lg border border-zinc-200 bg-white p-1 shadow-xl ${
              direction === "up" ? "bottom-full mb-1" : "top-full mt-1"
            }`}
          >
            <div className="px-2 py-1 text-[10px] font-medium uppercase tracking-wide text-zinc-400">选择模型（按供应商）</div>
            {byProvider.map((g) => (
              <div key={g.provider.id} className="mb-0.5">
                <div className="flex items-center gap-1 px-2 py-1 text-[10px] font-semibold text-zinc-400">
                  <ServerDot />
                  <span className="truncate">{g.provider.name}</span>
                </div>
                {g.models.map((m) => (
                  <button
                    key={m.id}
                    type="button"
                    onClick={() => { setOpen(false); onChange(m); }}
                    className={`flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-[12px] hover:bg-zinc-100 ${
                      m.id === value ? "bg-blue-50 text-blue-700" : "text-zinc-600"
                    }`}
                  >
                    <ModelIcon name={m.name} icon={m.icon} size={12} />
                    <span className="flex-1 truncate">{m.name}</span>
                    {m.is_default === 1 && <span className="rounded bg-blue-50 px-1.5 text-[9px] text-blue-600">默认</span>}
                  </button>
                ))}
              </div>
            ))}
            {byProvider.length === 0 && (
              <div className="px-2 py-2 text-[11px] text-zinc-400">无可用的对话模型</div>
            )}
          </div>
        </>
      )}
    </div>
  );
}
