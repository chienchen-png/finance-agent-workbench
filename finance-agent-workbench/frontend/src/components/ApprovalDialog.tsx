/** ApprovalDialog — 写操作审批弹窗（P12.3：Beautiful UI Approval Card 风格）。
 *
 * 在 smol 引擎发起写操作（update_rows/insert_rows/delete_rows/write_file 等）
 * 时弹出确认框。视觉对齐 beautifului.dev 的 #Approval Card：
 *   卡片（max-w-80）→ 问题标题 + 参数展示 + 可选备注输入
 *   footer：拒绝（文本） + 圆点分页 + 发送箭头（↑ 确认执行）
 *   确认后 → 绿色 confirmation badge「已确认执行」
 */

import { useState } from "react";
import { X, ArrowUp, Check } from "lucide-react";

function humanizeTool(name: string): string {
  const map: Record<string, string> = {
    update_rows: "更新行数据",
    insert_rows: "插入行数据",
    delete_rows: "删除行数据",
    write_file: "写入文件",
    write_excel: "写入 Excel",
    export_project_data: "写回 Excel",
    import_excel_to_db: "导入 Excel 到数据库",
  };
  return map[name] || name;
}

export default function ApprovalDialog({
  toolName,
  args,
  onConfirm,
  onDeny,
}: {
  toolName: string;
  args: string;
  onConfirm: () => void;
  onDeny: () => void;
}) {
  const [sent, setSent] = useState(false);
  const [note, setNote] = useState("");

  const handleSend = () => {
    setSent(true);
    // 延迟关闭，让确认徽标可见
    setTimeout(onConfirm, 500);
  };

  // 确认后 → 绿色 confirmation badge（对齐 beautifului Approval Card sent 态）
  if (sent) {
    return (
      <div className="pop-in fixed inset-0 z-50 flex items-center justify-center bg-black/30">
        <div className="pop-in flex items-center gap-2 rounded-full bg-green-50 py-1 pr-3 pl-1">
          <span className="flex size-5 items-center justify-center rounded-full bg-green-600 text-white">
            <Check size={12} strokeWidth={3} />
          </span>
          <span className="text-[12.5px] font-medium text-green-700">已确认执行</span>
        </div>
      </div>
    );
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30">
      <div className="pop-in w-full max-w-80 overflow-hidden rounded-2xl bg-white shadow-2xl">
        {/* 问题区 */}
        <div className="fade-up p-4">
          <div className="flex items-start justify-between gap-3">
            <span className="text-[13px] font-medium text-zinc-800">
              是否执行 {humanizeTool(toolName)}？
            </span>
            <button
              type="button"
              aria-label="关闭"
              onClick={onDeny}
              className="shrink-0 rounded-lg p-1 text-zinc-400 transition-colors duration-100 hover:bg-zinc-100 hover:text-zinc-600"
            >
              <X size={14} />
            </button>
          </div>

          {/* 参数展示 */}
          <div className="mt-2 max-h-40 overflow-auto rounded-lg bg-zinc-50 p-2 font-mono text-[11px] leading-relaxed whitespace-pre-wrap break-all text-zinc-600">
            {args}
          </div>

          {/* 可选备注 */}
          <label className="mt-1 flex items-center gap-2 rounded-lg px-1.5 py-1 transition-colors duration-100 focus-within:bg-zinc-50 hover:bg-zinc-50">
            <span aria-hidden="true" className="size-4 shrink-0" />
            <input
              value={note}
              onChange={(e) => setNote(e.target.value)}
              placeholder="备注（可选）…"
              aria-label="备注"
              className="min-w-0 flex-1 bg-transparent text-[13px] text-zinc-800 outline-none placeholder:text-zinc-400"
            />
          </label>
        </div>

        {/* footer：拒绝 + 圆点分页 + 发送箭头 */}
        <div className="flex items-center justify-between border-t border-zinc-100 px-3 py-2">
          <button
            type="button"
            onClick={onDeny}
            className="text-[12px] font-medium text-zinc-400 transition-colors duration-100 hover:text-zinc-600"
          >
            拒绝
          </button>
          <span className="flex items-center gap-1">
            <span className="size-2.5 rounded-full border-2 border-zinc-800" />
          </span>
          <button
            type="button"
            aria-label="确认执行"
            onClick={handleSend}
            className="flex size-7 items-center justify-center rounded-lg bg-zinc-800 text-white shadow-sm transition-[background-color,transform] duration-150 hover:bg-zinc-700 active:scale-95"
          >
            <ArrowUp size={14} strokeWidth={2.5} />
          </button>
        </div>
      </div>
    </div>
  );
}
