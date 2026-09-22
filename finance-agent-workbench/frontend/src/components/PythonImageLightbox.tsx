/** PythonImageLightbox — Python(mplot3d) 生成的 3D 图（base64 PNG）「点击放大 + 下载」组件。
 *
 * 背景（v6.9-2）：3D 模板（waterfall3d/bar3d/scatter3d）改用 Python 生成 PNG 后，
 * 前端用 <img> 展示。为了对齐 2D 图表（DownloadPanel 模态放大 + 下载）的能力，
 * 这里提供等效交互：
 *   - 点击缩略图 → 全屏 lightbox 放大预览
 *   - lightbox 内提供「下载 PNG」按钮（触发浏览器下载 base64）
 *
 * 复用点：ChartRenderer（对话图表）与 ChartPreview（图表库预览）都使用本组件，
 * 保证 Python 3D 图在所有入口获得一致的放大/下载能力。
 */

import { useEffect, useState } from "react";
import { X, Download } from "lucide-react";

/** 触发浏览器下载 base64 PNG */
function downloadB64(b64: string, filename: string) {
  const a = document.createElement("a");
  a.href = `data:image/png;base64,${b64}`;
  a.download = filename;
  a.click();
}

/** 可复用的「点击放大 + 下载」容器。
 * children 为已生成的 <img>（缩略图，点击打开放大预览）；组件同时在底部提供下载按钮。
 */
export default function PythonImageLightbox({
  b64,
  filename,
  alt,
  children,
  bodyClassName = "",
}: {
  b64: string;
  filename: string;
  alt: string;
  /** 缩略图渲染（默认生成一个居中 <img>） */
  children?: React.ReactNode;
  /** 缩略图外层容器 className（用于缩放/布局） */
  bodyClassName?: string;
}) {
  const [open, setOpen] = useState(false);

  // 打开 lightbox 时锁定滚动；关闭恢复
  useEffect(() => {
    if (!open) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = prev;
    };
  }, [open]);

  // Esc 关闭
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  return (
    <>
      {/* 缩略图（点击放大） */}
      <div
        className={`relative cursor-zoom-in ${bodyClassName}`}
        onClick={() => setOpen(true)}
        title="点击放大"
        role="button"
        tabIndex={0}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            setOpen(true);
          }
        }}
      >
        {children || (
          <img
            src={`data:image/png;base64,${b64}`}
            alt={alt}
            className="max-h-full w-auto max-w-full object-contain"
          />
        )}
      </div>

      {/* 全屏 lightbox */}
      {open && (
        <div
          className="fixed inset-0 z-[100] flex items-center justify-center bg-black/80 p-4"
          onClick={() => setOpen(false)}
        >
          <div
            className="relative flex max-h-[92vh] max-w-[92vw] flex-col items-center"
            onClick={(e) => e.stopPropagation()}
          >
            {/* 关闭按钮 */}
            <button
              onClick={() => setOpen(false)}
              className="absolute -top-10 right-0 flex items-center gap-1 rounded-md px-2 py-1 text-[12px] text-white/90 transition-colors hover:bg-white/10 hover:text-white"
              title="关闭 (Esc)"
            >
              <X size={16} />
              关闭
            </button>
            {/* 放大图 */}
            <img
              src={`data:image/png;base64,${b64}`}
              alt={alt}
              className="max-h-[86vh] max-w-full border border-zinc-800 bg-white object-contain shadow-2xl"
            />
            {/* 底部操作栏 */}
            <div className="mt-3 flex items-center gap-3">
              <button
                onClick={() => downloadB64(b64, filename)}
                className="flex items-center gap-1.5 rounded-md bg-blue-600 px-3 py-1.5 text-[13px] font-medium text-white transition-colors hover:bg-blue-700"
              >
                <Download size={15} />
                下载 PNG
              </button>
              <span className="text-[12px] text-white/60">{alt}</span>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
