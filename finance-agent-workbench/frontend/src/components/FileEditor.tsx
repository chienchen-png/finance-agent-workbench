/** FileEditor — 文件预览/编辑容器（阶段 4 → D3 升级，2026-08-24）。
 *
 * 按 viewer_type 分发的统一预览容器（设计文档 §2.1 双击行为矩阵）：
 *  - markdown → MarkdownEditor（Vditor 渲染 + 编辑 + 保存；导出按钮 D4 接入）
 *  - pdf      → iframe 加载 raw 二进制流（浏览器内置 PDF 查看器，零依赖）
 *  - image    → <img> 浏览器预览
 *  - text/code→ textarea 编辑保存（原逻辑保留）
 *  - office   → 提示 + 「用系统打开」按钮（兜底；正常流程在 FileDrawer 已分流
 *               为双击直接 open-external，不会进入本容器）
 *
 * 加载：先取 fileMeta 得 viewer_type，再按需 readFileContent（仅文本类）。
 */

import { useEffect, useState } from "react";
import { Save, FileCode, ExternalLink } from "lucide-react";
import {
  readFileContent, writeFileContent, fileMeta, openExternalFile, rawFileUrl,
  exportDocxFile, downloadBlob,
} from "../lib/api";
import MarkdownEditor from "./MarkdownEditor";

export default function FileEditor({
  projectId,
  filePath,
  onClose,
  onSaved,
  embedded = false,
  resolveImageUrl,
}: {
  projectId: string;
  filePath: string;
  onClose: () => void;
  onSaved: () => void;
  /** 内嵌模式：显示在应用内容区（不用全屏 fixed 覆盖），隐藏「关闭」按钮 */
  embedded?: boolean;
  /** 图片相对路径解析（传给 MarkdownEditor，报告/文件预览图可加载） */
  resolveImageUrl?: (path: string) => string;
}) {
  const [viewerType, setViewerType] = useState<string>("");
  const [content, setContent] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError("");
    setViewerType("");
    setContent("");
    setDirty(false);
    (async () => {
      try {
        const meta = await fileMeta(projectId, filePath);
        if (cancelled) return;
        const vt = meta.file.viewer_type;
        setViewerType(vt);
        // 文本类（text/code/markdown）→ 读取内容供编辑器；二进制类无需读取
        if (vt === "text" || vt === "code" || vt === "markdown") {
          const d = await readFileContent(projectId, filePath);
          if (cancelled) return;
          setContent(d.content);
        }
      } catch (e) {
        if (!cancelled) setError((e as Error).message);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [projectId, filePath]);

  const isText = viewerType === "text" || viewerType === "code";
  const isMarkdown = viewerType === "markdown";
  const isOffice = viewerType === "docx" || viewerType === "xlsx" || viewerType === "xls"
    || viewerType === "ppt" || viewerType === "pptx";
  const isBinaryPreview = viewerType === "pdf" || viewerType === "image";

  // md 上传按钮：指向 filePath 所在目录
  const uploadUrl = isMarkdown
    ? (() => {
        const dir = filePath.includes("/") ? filePath.slice(0, filePath.lastIndexOf("/")) : "";
        return `/api/files/upload?project_id=${encodeURIComponent(projectId)}&path=${encodeURIComponent(dir)}`;
      })()
    : undefined;

  async function handleSave() {
    setSaving(true);
    try {
      await writeFileContent(projectId, filePath, content);
      setDirty(false);
      onSaved();
    } catch (e) {
      alert(`保存失败: ${(e as Error).message}`);
    } finally {
      setSaving(false);
    }
  }

  async function handleOpenExternal() {
    try {
      await openExternalFile(projectId, filePath);
    } catch (e) {
      alert(`打开失败: ${(e as Error).message}`);
    }
  }

  // D4：导出 Word（未保存的编辑内容直接导出）
  async function handleExportWord(md: string) {
    try {
      const blob = await exportDocxFile(projectId, filePath, md);
      const stem = filePath.split("/").pop()?.replace(/\.(md|markdown)$/i, "") || "document";
      downloadBlob(blob, `${stem}.docx`);
    } catch (e) {
      alert((e as Error).message);
    }
  }

  return (
    <div className={embedded ? "flex h-full min-h-0 flex-1 flex-col bg-zinc-50" : "fixed inset-0 z-40 flex flex-col bg-zinc-50"}>
      {/* 头部 */}
      <div className="flex items-center gap-2 border-b border-zinc-200 bg-white px-4 py-2">
        <FileCode size={14} className="text-blue-600" />
        <span className="truncate text-[13px] font-medium text-zinc-700">{filePath}</span>
        {dirty && <span className="text-[11px] text-amber-600">● 未保存</span>}
        <div className="ml-auto flex items-center gap-1.5">
          {(isMarkdown || isText) && (
            <button
              onClick={handleSave}
              disabled={!dirty || saving}
              className="flex items-center gap-1 rounded-md bg-blue-600 px-3 py-1.5 text-[12px] text-white hover:bg-blue-500 disabled:opacity-40"
            >
              <Save size={12} />
              {saving ? "保存中…" : "保存"}
            </button>
          )}
          {isOffice && (
            <button
              onClick={() => void handleOpenExternal()}
              className="flex items-center gap-1 rounded-md bg-blue-600 px-3 py-1.5 text-[12px] text-white hover:bg-blue-500"
            >
              <ExternalLink size={12} />
              用系统打开
            </button>
          )}
          {!embedded && (
            <button className="rounded-md px-2 py-1.5 text-[12px] text-zinc-500 hover:bg-zinc-100" onClick={onClose}>
              关闭
            </button>
          )}
        </div>
      </div>

      {/* 内容 */}
      <div className="flex-1 overflow-auto p-4">
        {loading && <div className="text-[13px] text-zinc-400">加载中…</div>}
        {error && <div className="text-[13px] text-red-500">{error}</div>}
        {!loading && !error && (
          <>
            {/* markdown → Vditor 编辑器（渲染 + 编辑 + 保存 + 上传图片） */}
            {isMarkdown && (
              <MarkdownEditor
                key={filePath}
                initialValue={content}
                onChange={(md) => { setContent(md); setDirty(true); }}
                uploadUrl={uploadUrl}
                showExport
                onExportWord={(md) => void handleExportWord(md)}
                resolveImageUrl={resolveImageUrl}
                className="h-full"
              />
            )}
            {/* pdf → iframe 浏览器预览 */}
            {viewerType === "pdf" && (
              <iframe
                src={rawFileUrl(projectId, filePath, true)}
                title={filePath}
                className="h-full w-full rounded-md border border-zinc-200 bg-white"
              />
            )}
            {/* image → 浏览器预览 */}
            {viewerType === "image" && (
              <div className="flex h-full items-center justify-center">
                <img
                  src={rawFileUrl(projectId, filePath, true)}
                  alt={filePath}
                  className="max-h-full max-w-full rounded-md border border-zinc-200 object-contain shadow-sm"
                />
              </div>
            )}
            {/* office 兜底（正常双击已在 FileDrawer 分流外部打开） */}
            {isOffice && (
              <div className="mt-10 text-center text-[13px] text-zinc-400">
                该文件为 Office 文档，建议用本机程序打开
                <br />
                <span className="text-[12px]">（点击右上角「用系统打开」）</span>
              </div>
            )}
            {/* 其他二进制（不应出现） */}
            {viewerType !== "" && !isText && !isMarkdown && !isOffice && !isBinaryPreview && (
              <div className="mt-10 text-center text-[13px] text-zinc-400">
                该文件类型暂不支持预览
              </div>
            )}
            {/* text / code → textarea 编辑 */}
            {isText && (
              <textarea
                value={content}
                onChange={(e) => { setContent(e.target.value); setDirty(true); }}
                spellCheck={false}
                className="h-full w-full resize-none rounded-md border border-zinc-200 bg-white p-3 font-mono text-[13px] leading-relaxed text-zinc-800 outline-none focus:border-blue-400"
              />
            )}
          </>
        )}
      </div>
    </div>
  );
}
