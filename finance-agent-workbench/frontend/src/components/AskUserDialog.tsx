/** AskUserDialog — AI 向用户提问（智能体优化 3.0 阶段 A2，内联卡片版）。
 *
 * 视觉对齐 VS Code Copilot 的 ask_user：**输入框上方内联弹出**，
 * 而非屏幕中央遮罩。由 ChatPage 在 composer 内用 absolute 定位承载。
 *
 * 支持：
 * - 单选（radio）：input_type=select 且 multi_select=false
 * - 多选（checkbox）：input_type=select 且 multi_select=true（逗号分隔提交）
 * - 填空（text）：input_type=text（Enter 或 ↑ 发送）
 * - 确认（confirm）：是/否 双按钮
 * - 跳过（allow_skip=true 时显示"跳过"）
 *
 * 触发链路：AI ask_user → smol 引擎发 user_input_required →
 * sse.ts onQuestion → 本组件内联弹出 → 用户回答 → POST /api/interactions/<id>/respond。
 */

import { useEffect, useRef, useState } from "react";
import { ArrowUp, X } from "lucide-react";

export interface AskUserPayload {
  interaction_id: string;
  question: string;
  input_type: string; // text | confirm | select
  options: string[];
  multi_select?: boolean;
  allow_skip?: boolean;
}

export default function AskUserDialog({
  payload,
  onAnswer,
  onCancel,
}: {
  payload: AskUserPayload;
  onAnswer: (response: string, cancelled: boolean) => void;
  onCancel: () => void;
}) {
  const [text, setText] = useState("");
  const [selected, setSelected] = useState<string[]>([]);
  const inputRef = useRef<HTMLInputElement | null>(null);
  const multi = Boolean(payload.multi_select);
  const allowSkip = Boolean(payload.allow_skip);
  const mode: "text" | "confirm" | "select" =
    payload.input_type === "confirm"
      ? "confirm"
      : payload.input_type === "select"
        ? "select"
        : "text";

  useEffect(() => {
    if (mode === "text") inputRef.current?.focus();
  }, [mode]);

  const hasAnswer =
    mode === "text"
      ? text.trim().length > 0
      : mode === "select"
        ? selected.length > 0
        : true;

  const submit = (value: string) => onAnswer(value, false);
  const cancel = (skip = false) => (skip ? onAnswer("", true) : onCancel());

  const toggleOption = (opt: string) => {
    if (multi) {
      setSelected((prev) =>
        prev.includes(opt) ? prev.filter((x) => x !== opt) : [...prev, opt],
      );
    } else {
      submit(opt);
    }
  };

  return (
    <div className="drawer-up absolute bottom-full left-0 right-0 z-30 mb-1.5 overflow-hidden rounded-xl border border-zinc-200 bg-white shadow-2xl">
      <div className="flex items-start justify-between gap-3 border-b border-zinc-100 px-3.5 py-2.5">
        <span className="text-[13px] font-medium text-zinc-800">
          {payload.question}
        </span>
        <button
          type="button"
          aria-label="关闭"
          onClick={() => cancel(false)}
          className="shrink-0 rounded-md p-0.5 text-zinc-400 transition-colors duration-100 hover:bg-zinc-100 hover:text-zinc-600"
        >
          <X size={14} />
        </button>
      </div>

      <div className="px-3.5 py-2.5">
        {mode === "select" && payload.options.length > 0 && (
          <div className="flex flex-col gap-0.5">
            {payload.options.map((opt) => {
              const on = selected.includes(opt);
              return (
                <button
                  key={opt}
                  type="button"
                  aria-pressed={on}
                  onClick={() => toggleOption(opt)}
                  className="-mx-1.5 flex items-center gap-2 rounded-lg px-1.5 py-1 text-left transition-colors duration-100 hover:bg-zinc-100"
                >
                  <span
                    className={`flex size-4 shrink-0 items-center justify-center transition-colors duration-200 ${
                      multi ? "rounded-[5px]" : "rounded-full"
                    } ${
                      on
                        ? "bg-zinc-800 text-white"
                        : "shadow-[inset_0_0_0_1.5px_#d4d4d8]"
                    }`}
                  >
                    {multi ? (
                      on && (
                        <svg
                          width="11"
                          height="11"
                          viewBox="0 0 24 24"
                          fill="none"
                          stroke="currentColor"
                          strokeWidth="3"
                          strokeLinecap="round"
                          strokeLinejoin="round"
                        >
                          <path d="M20 6L9 17l-5-5" />
                        </svg>
                      )
                    ) : (
                      <span
                        className="size-1.5 rounded-full bg-white transition-transform duration-200"
                        style={{ transform: on ? "scale(1)" : "scale(0)" }}
                      />
                    )}
                  </span>
                  <span
                    className={`text-[13px] transition-colors duration-200 ${
                      on ? "text-zinc-800" : "text-zinc-500"
                    }`}
                  >
                    {opt}
                  </span>
                </button>
              );
            })}
          </div>
        )}

        {mode === "confirm" && (
          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => submit("是")}
              className="flex-1 rounded-lg bg-zinc-800 py-2 text-[13px] font-medium text-white transition-colors hover:bg-zinc-700"
            >
              是
            </button>
            <button
              type="button"
              onClick={() => submit("否")}
              className="flex-1 rounded-lg border border-zinc-200 py-2 text-[13px] font-medium text-zinc-600 transition-colors hover:bg-zinc-50"
            >
              否
            </button>
          </div>
        )}

        {(mode === "text" || (mode === "select" && multi)) && (
          <div className="mt-1 flex items-center gap-2 rounded-lg px-1.5 py-1 transition-colors duration-100 focus-within:bg-zinc-100 hover:bg-zinc-100">
            <span aria-hidden="true" className="size-4 shrink-0" />
            <input
              ref={inputRef}
              value={text}
              onChange={(e) => setText(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && text.trim()) submit(text.trim());
              }}
              placeholder={mode === "text" ? "输入回答…" : "自定义补充…"}
              aria-label="回答输入"
              className="min-w-0 flex-1 bg-transparent text-[13px] text-zinc-800 outline-none placeholder:text-zinc-400"
            />
          </div>
        )}
      </div>

      <div className="flex items-center justify-between border-t border-zinc-100 px-3 py-2">
        <span className="flex items-center gap-1">
          <span className="size-2.5 rounded-full border-2 border-zinc-800" />
        </span>
        <div className="flex items-center gap-2">
          {allowSkip && (
            <button
              type="button"
              onClick={() => cancel(true)}
              className="text-[12px] font-medium text-zinc-400 transition-colors duration-100 hover:text-zinc-600"
            >
              跳过
            </button>
          )}
          <button
            type="button"
            aria-label="发送回答"
            disabled={!hasAnswer}
            onClick={() => {
              if (mode === "select" && multi) {
                const parts = [...selected];
                if (text.trim()) parts.push(text.trim());
                submit(parts.join(","));
              } else if (mode === "text") {
                submit(text.trim());
              }
            }}
            className="-mr-0.5 flex size-7 items-center justify-center rounded-[8px] transition-colors duration-200 disabled:opacity-40"
            style={{
              background: hasAnswer ? "#18181b" : "#f4f4f5",
              color: hasAnswer ? "#ffffff" : "#a1a1aa",
              boxShadow: hasAnswer ? "inset 0 1px 0 rgba(255,255,255,0.14)" : "none",
            }}
          >
            <ArrowUp size={14} strokeWidth={2.5} />
          </button>
        </div>
      </div>
    </div>
  );
}
