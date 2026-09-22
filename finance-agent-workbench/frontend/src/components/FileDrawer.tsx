/** FileDrawer — 文件浏览器（阶段 4：完整文件操作）。
 *
 * 功能：
 * - 目录树递归展开
 * - 右键菜单：新建文件/目录、重命名、复制、剪切、粘贴、删除、导入数据库、刷新
 * - 顶部工具栏：新建、刷新
 * 对接：/api/files/*（routes/files.py）
 */

import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import {
  X, ChevronRight, ChevronDown, File, Folder, RefreshCw,
  FilePlus, FolderPlus, FileUp, FolderUp, Pencil, Copy, Scissors, Clipboard,
  Trash2, Database, Eye, Upload, Plus,
} from "lucide-react";
import {
  fetchFileTree, createFileItem, renameFileItem, copyFileItem,
  deleteFileItem, importDataFile, uploadFile,
  fileMeta, openExternalFile,
  type FileEntry,
} from "../lib/api";

interface CtxMenu {
  x: number;
  y: number;
  entry: FileEntry;
}

export default function FileDrawer({
  projectId,
  workDir,
  closing,
  onClose,
  onPick,
  onRefer,
  onImported,
}: {
  projectId: string;
  workDir: string;
  closing?: boolean; // 阶段 7.9.10.2：父级触发滑出动画中（渲染 drawer-anim-out）
  onClose: () => void;
  onPick: (path: string) => void;
  onRefer: (path: string) => void;
  onImported: () => void;
}) {
  const [tree, setTree] = useState<FileEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [ctx, setCtx] = useState<CtxMenu | null>(null);
  const [clipboard, setClipboard] = useState<{ op: "copy" | "cut"; path: string } | null>(null);
  const [prompt, setPrompt] = useState<{ title: string; placeholder: string; onSubmit: (val: string) => void } | null>(null);
  // 上传状态（阶段 7.9：上传文件/文件夹）
  const [uploading, setUploading] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const folderInputRef = useRef<HTMLInputElement>(null);
  // 顶栏新建的当前目录（最近选中/右键的目录）
  const [activeDir, setActiveDir] = useState("");
  // 阶段 7.9.2：顶栏下拉菜单（new=新建 二级菜单 / upload=上传 二级菜单）
  const [topMenu, setTopMenu] = useState<"new" | "upload" | null>(null);
  const topMenuRef = useRef<HTMLDivElement>(null);
  // 阶段 7.9.2：右键菜单动态定位（Windows 式向下/向上翻转）+ 实际高度测量
  const [ctxPos, setCtxPos] = useState<{ left: number; top: number } | null>(null);
  const ctxMenuRef = useRef<HTMLDivElement>(null);
  // 阶段 7.9.2：操作反馈 toast（复制/剪切/粘贴/删除成功提示）
  const [toast, setToast] = useState<string | null>(null);
  const toastTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const showToast = useCallback((msg: string) => {
    setToast(msg);
    if (toastTimer.current) clearTimeout(toastTimer.current);
    toastTimer.current = setTimeout(() => setToast(null), 2500);
  }, []);

  const load = useCallback(async (path = "") => {
    setLoading(true);
    setError("");
    try {
      const data = await fetchFileTree(projectId, path);
      setTree(data.entries || []);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  useEffect(() => { load(); }, [load]);

  // 点击空白处关闭右键菜单 / 顶栏下拉
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      setCtx(null);
      if (topMenuRef.current && !topMenuRef.current.contains(e.target as Node)) {
        setTopMenu(null);
      }
    };
    window.addEventListener("click", handler);
    return () => window.removeEventListener("click", handler);
  }, []);

  // 阶段 7.9.2：右键菜单动态定位（Windows 式翻转）——测量菜单实际高度，
  // 下方放不下则向上弹出；同时做左右钳制。菜单渲染后执行。
  useLayoutEffect(() => {
    if (!ctx || !ctxMenuRef.current) {
      setCtxPos(null);
      return;
    }
    const h = ctxMenuRef.current.offsetHeight || 380;
    const w = ctxMenuRef.current.offsetWidth || 176;
    const vw = window.innerWidth;
    const vh = window.innerHeight;
    const MARGIN = 8;
    // 左：钳制在视口内
    const left = Math.max(MARGIN, Math.min(ctx.x, vw - w - MARGIN));
    // 上：下方放不下且上方够 → 向上弹；否则向下（钳制）
    const spaceBelow = vh - ctx.y;
    let top: number;
    if (spaceBelow < h + MARGIN && ctx.y > h + MARGIN) {
      top = Math.max(MARGIN, ctx.y - h); // 向上弹
    } else {
      top = Math.min(ctx.y, vh - h - MARGIN); // 向下弹（钳制）
    }
    setCtxPos({ left, top });
  }, [ctx]);

  const toggle = (path: string) => {
    setExpanded((s) => {
      const next = new Set(s);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      return next;
    });
  };

  // ---------- 操作 ----------

  async function handleCreate(type: "file" | "directory", parentPath: string) {
    setPrompt({
      title: type === "file" ? "新建文件" : "新建文件夹",
      placeholder: type === "file" ? "文件名（如 readme.md）" : "文件夹名",
      onSubmit: async (name) => {
        const full = parentPath ? `${parentPath}/${name}` : name;
        try {
          await createFileItem(projectId, full, type);
          await load(); // 自动刷新
          showToast(`已创建${type === "file" ? "文件" : "文件夹"}「${name}」`);
        } catch (e) {
          alert(`创建失败: ${(e as Error).message}`);
        }
      },
    });
  }

  // 阶段 7.9.5：启动内联重命名
  function startRename(entry: FileEntry) {
    setRenamingEntry(entry);
    setCtx(null);
  }

  // 阶段 7.9.5：确认重命名（Enter/失焦）
  async function commitRename(entry: FileEntry, name: string) {
    setRenamingEntry(null);
    if (!name || name === entry.name) return;
    const newPath = entry.path.split("/").slice(0, -1).concat(name).join("/");
    try {
      await renameFileItem(projectId, entry.path, newPath);
      await load(); // 自动刷新
      showToast(`已重命名「${entry.name}」→「${name}」`);
    } catch (e) {
      alert(`重命名失败: ${(e as Error).message}`);
    }
  }

  // 阶段 7.9.5：内联重命名状态（Windows 式，同一时间仅一个条目在编辑）
  const [renamingEntry, setRenamingEntry] = useState<FileEntry | null>(null);

  async function handlePaste(targetPath: string) {
    if (!clipboard) return;
    const dest = targetPath ? `${targetPath}/${clipboard.path.split("/").pop()}` : clipboard.path.split("/").pop() || "";
    try {
      if (clipboard.op === "copy") {
        await copyFileItem(projectId, clipboard.path, dest);
      } else {
        // cut → copy + delete（后端无 move，用 copy+delete 模拟）
        await copyFileItem(projectId, clipboard.path, dest);
        await deleteFileItem(projectId, clipboard.path);
      }
      setClipboard(null);
      await load(); // 自动刷新（阶段 7.9.2：缓存禁用后必拿最新数据）
      showToast(`粘贴成功：已${clipboard.op === "copy" ? "复制" : "剪切"}「${clipboard.path.split("/").pop()}」到 ${dest || "根目录"}`);
    } catch (e) {
      alert(`粘贴失败: ${(e as Error).message}`);
    }
  }

  async function handleDelete(entry: FileEntry) {
    // 阶段 7.9.2：明确提示删除系统真实文件（不可撤销）
    if (!confirm(`确定删除「${entry.name}」？\n\n此操作将删除系统磁盘上的真实文件${entry.type === "directory" ? "/文件夹及其全部内容" : ""}，且不可恢复。`)) return;
    try {
      await deleteFileItem(projectId, entry.path);
      await load(); // 自动刷新
      showToast(`已删除「${entry.name}」`);
    } catch (e) {
      alert(`删除失败: ${(e as Error).message}`);
    }
  }

  async function handleImport(entry: FileEntry) {
    try {
      await importDataFile(projectId, entry.path);
      onImported();
      alert("已开始导入到项目数据库");
    } catch (e) {
      alert(`导入失败: ${(e as Error).message}`);
    }
  }

  // 阶段 7.9：上传文件/文件夹到指定目录
  async function handleUploadFiles(files: FileList | null, targetDir: string) {
    if (!files || files.length === 0) return;
    setUploading(true);
    let ok = 0;
    let failed = 0;
    try {
      for (const f of Array.from(files)) {
        try {
          await uploadFile(projectId, targetDir, f);
          ok++;
        } catch (e) {
          failed++;
          console.warn(`上传 ${f.name} 失败`, e);
        }
      }
      await load();
      if (failed === 0) {
        alert(`已上传 ${ok} 个文件`);
      } else {
        alert(`上传完成：成功 ${ok} 个，失败 ${failed} 个`);
      }
    } finally {
      setUploading(false);
    }
  }

  async function handleUploadFolder(files: FileList | null, targetDir: string) {
    if (!files || files.length === 0) return;
    setUploading(true);
    let ok = 0;
    let failed = 0;
    try {
      for (const f of Array.from(files)) {
        // webkitdirectory 返回带相对路径的文件（如 sub/file.txt），取相对路径保层级
        const rel = (f as File & { webkitRelativePath?: string }).webkitRelativePath || "";
        try {
          await uploadFile(projectId, targetDir, f, rel || undefined);
          ok++;
        } catch (e) {
          failed++;
          console.warn(`上传 ${rel || f.name} 失败`, e);
        }
      }
      await load();
      if (failed === 0) {
        alert(`已上传文件夹（${ok} 个文件）`);
      } else {
        alert(`文件夹上传完成：成功 ${ok} 个，失败 ${failed} 个`);
      }
    } finally {
      setUploading(false);
    }
  }

  async function handleOpen(entry: FileEntry) {
    if (entry.type === "directory") return;
    try {
      // D3：按 viewer_type 分发（设计文档 §2.1 双击行为矩阵）
      const meta = await fileMeta(projectId, entry.path);
      const vt = meta.file.viewer_type;
      // office 双击直接调用本机程序打开（不进预览容器）
      if (vt === "docx" || vt === "xlsx" || vt === "xls" || vt === "ppt" || vt === "pptx") {
        await openExternalFile(projectId, entry.path);
        return;
      }
      // D7：pdf / 图片 / md / 文本类 → 新标签页预览（独立浏览器 tab，可自由切换）
      // 不再占用当前应用页（防止关闭预览误关应用主页）
      const url = `/?preview=1&project_id=${encodeURIComponent(projectId)}&path=${encodeURIComponent(entry.path)}`;
      window.open(url, "_blank");
    } catch (e) {
      alert(`无法打开: ${(e as Error).message}`);
    }
  }

  // ---------- 渲染 ----------

  const renderRow = (entry: FileEntry, depth: number) => (
    <FileRow
      key={entry.path}
      entry={entry}
      depth={depth}
      expanded={expanded}
      onToggle={toggle}
      onPick={onPick}
      onContext={(e, entry) => { e.preventDefault(); setCtx({ x: e.clientX, y: e.clientY, entry }); if (entry.type === "directory") setActiveDir(entry.path); }}
      onDoubleClick={handleOpen}
      onDragRef={(e, entry) => {
        // 阶段 7.9.2：拖拽引用——拖出文件路径到输入框
        e.dataTransfer.setData("text/plain", `@${entry.type === "directory" ? "folder" : "file"}:${entry.path}`);
        e.dataTransfer.effectAllowed = "copy";
      }}
      renamingEntry={renamingEntry}
      onRenameCommit={commitRename}
      onRenameCancel={() => setRenamingEntry(null)}
      onRenameRequest={startRename}
      projectId={projectId}
      loadChildren={async (path) => (await fetchFileTree(projectId, path)).entries || []}
    />
  );

  return (
    <div className={`drawer-anim absolute inset-y-0 right-0 z-20 flex w-80 flex-col border-l border-zinc-200 bg-white shadow-2xl ${closing ? "drawer-anim-out" : ""}`}>
      {/* 头部（阶段 7.9.9.1：两行布局——标题/按钮固定一行，路径独立一行，
          无论路径多长都不挤兑标题；此前路径与标题同行，长路径挤压导致换行） */}
      <div className="border-b border-zinc-200 px-3 py-2">
        <div className="flex items-center gap-2">
          <Folder size={14} className="text-blue-600" />
          <span className="text-sm font-medium text-zinc-700">项目目录</span>
          <div className="ml-auto flex items-center gap-0.5">
          {/* 阶段 7.9.2：集成「新建」「上传」两个纯图标下拉按钮（与刷新/关闭同尺寸） */}
          <div className="relative" ref={topMenuRef}>
            <button
              className="rounded p-1 text-zinc-400 hover:bg-zinc-100 hover:text-zinc-600"
              onClick={(e) => { e.stopPropagation(); setTopMenu(topMenu === "new" ? null : "new"); }}
              title="新建"
            >
              <Plus size={13} />
            </button>
            {topMenu === "new" && (
              <div className="absolute right-0 top-full z-50 mt-1 w-40 rounded-md border border-zinc-200 bg-white py-1 shadow-xl">
                <button
                  className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-[12px] text-zinc-700 hover:bg-zinc-100"
                  onClick={(e) => { e.stopPropagation(); setTopMenu(null); handleCreate("file", activeDir); }}
                >
                  <FilePlus size={12} className="text-zinc-400" /> 新建文件
                </button>
                <button
                  className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-[12px] text-zinc-700 hover:bg-zinc-100"
                  onClick={(e) => { e.stopPropagation(); setTopMenu(null); handleCreate("directory", activeDir); }}
                >
                  <FolderPlus size={12} className="text-zinc-400" /> 新建文件夹
                </button>
              </div>
            )}
          </div>
          <div className="relative">
            <button
              className="rounded p-1 text-zinc-400 hover:bg-zinc-100 hover:text-zinc-600 disabled:opacity-40"
              onClick={(e) => { e.stopPropagation(); setTopMenu(topMenu === "upload" ? null : "upload"); }}
              disabled={uploading}
              title="上传"
            >
              <Upload size={13} />
            </button>
            {topMenu === "upload" && (
              <div className="absolute right-0 top-full z-50 mt-1 w-40 rounded-md border border-zinc-200 bg-white py-1 shadow-xl">
                <button
                  className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-[12px] text-zinc-700 hover:bg-zinc-100"
                  onClick={(e) => { e.stopPropagation(); setTopMenu(null); fileInputRef.current?.click(); }}
                >
                  <FileUp size={12} className="text-zinc-400" /> 上传文件
                </button>
                <button
                  className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-[12px] text-zinc-700 hover:bg-zinc-100"
                  onClick={(e) => { e.stopPropagation(); setTopMenu(null); folderInputRef.current?.click(); }}
                >
                  <FolderUp size={12} className="text-zinc-400" /> 上传文件夹
                </button>
              </div>
            )}
          </div>
          <button className="rounded p-1 text-zinc-400 hover:bg-zinc-100 hover:text-zinc-600" onClick={() => load()} title="刷新">
            <RefreshCw size={13} />
          </button>
          <button className="rounded p-1 text-zinc-400 hover:bg-zinc-100 hover:text-zinc-600" onClick={onClose} title="关闭">
            <X size={14} />
          </button>
        </div>
        </div>
        {/* 第二行：工作目录路径（独立一行，min-w-0 保证 truncate 生效，不挤兑标题） */}
        <div className="mt-0.5 truncate pl-6 text-[11px] text-zinc-400" title={workDir}>
          {workDir}
        </div>
      </div>

      {/* 隐藏的文件/文件夹选择 input */}
      <input
        ref={fileInputRef}
        type="file"
        multiple
        className="hidden"
        onChange={(e) => { handleUploadFiles(e.target.files, activeDir); e.target.value = ""; }}
      />
      <input
        ref={folderInputRef}
        type="file"
        multiple
        className="hidden"
        /* @ts-expect-error webkitdirectory 非标准属性 */
        webkitdirectory=""
        directory=""
        onChange={(e) => { handleUploadFolder(e.target.files, activeDir); e.target.value = ""; }}
      />

      {/* 列表 */}
      <div className="flex-1 overflow-y-auto p-2">
        {loading && <div className="p-3 text-[12px] text-zinc-400">加载中…</div>}
        {error && <div className="p-3 text-[12px] text-red-500">{error}</div>}
        {!loading && !error && tree.length === 0 && (
          <div className="p-3 text-[12px] text-zinc-400">目录为空（右键或顶部 + 新建）</div>
        )}
        <div className="space-y-0.5">{tree.map((e) => renderRow(e, 0))}</div>
      </div>

      {/* 右键菜单（阶段 7.9.2：动态翻转 + max-h 兜底） */}
      {ctx && (
        <div
          ref={ctxMenuRef}
          className="fixed z-50 max-h-[75vh] w-44 overflow-y-auto rounded-md border border-zinc-200 bg-white py-1 shadow-xl"
          style={ctxPos ? { left: ctxPos.left, top: ctxPos.top } : { left: 8, top: 8 }}
        >
          <CtxItem icon={<Eye size={13} />} label="打开" onClick={() => { handleOpen(ctx.entry); setCtx(null); }} disabled={ctx.entry.type !== "file"} />
          <CtxItem icon={<Database size={13} />} label="添加到项目数据库" onClick={() => { handleImport(ctx.entry); setCtx(null); }} disabled={ctx.entry.type !== "file"} />
          {/* 阶段 7.9.2：引用——把文件/文件夹路径插入输入框（@file/@folder 语法，AI 可识别） */}
          <CtxItem icon={<LinkIcon />} label="引用" onClick={() => { onRefer(ctx.entry.type === "directory" ? `@folder:${ctx.entry.path}` : `@file:${ctx.entry.path}`); setCtx(null); showToast(`已引用「${ctx.entry.path}」`); }} />
          <CtxItem icon={<Pencil size={13} />} label="重命名" onClick={() => { startRename(ctx.entry); }} />
          <div className="my-1 border-t border-zinc-100" />
          <CtxItem icon={<FilePlus size={13} />} label="新建文件" onClick={() => { handleCreate("file", ctx.entry.type === "directory" ? ctx.entry.path : ""); setCtx(null); }} />
          <CtxItem icon={<FolderPlus size={13} />} label="新建文件夹" onClick={() => { handleCreate("directory", ctx.entry.type === "directory" ? ctx.entry.path : ""); setCtx(null); }} />
          <div className="my-1 border-t border-zinc-100" />
          {/* 阶段 7.9：上传文件/文件夹到当前目录 */}
          <CtxItem icon={<Upload size={13} />} label="上传文件到此" onClick={() => { setActiveDir(ctx.entry.type === "directory" ? ctx.entry.path : ""); setCtx(null); setTimeout(() => fileInputRef.current?.click(), 0); }} disabled={ctx.entry.type !== "directory"} />
          <CtxItem icon={<FolderPlus size={13} />} label="上传文件夹到此" onClick={() => { setActiveDir(ctx.entry.type === "directory" ? ctx.entry.path : ""); setCtx(null); setTimeout(() => folderInputRef.current?.click(), 0); }} disabled={ctx.entry.type !== "directory"} />
          <div className="my-1 border-t border-zinc-100" />
          <CtxItem icon={<Copy size={13} />} label="复制" onClick={() => { setClipboard({ op: "copy", path: ctx.entry.path }); setCtx(null); showToast(`已复制「${ctx.entry.name}」，到目标位置右键「粘贴到此处」`); }} />
          <CtxItem icon={<Scissors size={13} />} label="剪切" onClick={() => { setClipboard({ op: "cut", path: ctx.entry.path }); setCtx(null); showToast(`已剪切「${ctx.entry.name}」，到目标位置右键「粘贴到此处」`); }} />
          <CtxItem icon={<Clipboard size={13} />} label="粘贴到此处" onClick={() => { handlePaste(ctx.entry.type === "directory" ? ctx.entry.path : ""); setCtx(null); }} disabled={!clipboard} />
          <div className="my-1 border-t border-zinc-100" />
          <CtxItem icon={<Trash2 size={13} />} label="删除" danger onClick={() => { handleDelete(ctx.entry); setCtx(null); }} />
        </div>
      )}

      {/* 操作反馈 toast（阶段 7.9.2） */}
      {toast && (
        <div className="fixed bottom-20 right-2 z-[60] max-w-64 rounded-md border border-zinc-200 bg-zinc-800 px-3 py-2 text-[11.5px] text-white shadow-xl fade-in-up">
          {toast}
        </div>
      )}

      {/* 输入弹窗 */}
      {prompt && (
        <PromptDialog
          title={prompt.title}
          placeholder={prompt.placeholder}
          onSubmit={(v) => { prompt.onSubmit(v); setPrompt(null); }}
          onCancel={() => setPrompt(null)}
        />
      )}
    </div>
  );
}

// ---------- 子组件 ----------

function CtxItem({ icon, label, onClick, danger, disabled }: {
  icon: React.ReactNode; label: string; onClick: () => void; danger?: boolean; disabled?: boolean;
}) {
  return (
    <button
      className={`flex w-full items-center gap-2 px-3 py-1.5 text-left text-[12.5px] ${
        disabled ? "cursor-not-allowed text-zinc-300" : danger ? "text-red-600 hover:bg-red-50" : "text-zinc-700 hover:bg-zinc-100"
      }`}
      onClick={disabled ? undefined : onClick}
      disabled={disabled}
    >
      {icon}
      <span className="truncate">{label}</span>
    </button>
  );
}

function PromptDialog({ title, placeholder, onSubmit, onCancel }: {
  title: string; placeholder: string; onSubmit: (v: string) => void; onCancel: () => void;
}) {
  const [val, setVal] = useState("");
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/20" onClick={onCancel}>
      <div className="w-80 rounded-lg border border-zinc-200 bg-white p-4 shadow-2xl" onClick={(e) => e.stopPropagation()}>
        <h3 className="mb-3 text-[13px] font-medium text-zinc-800">{title}</h3>
        <input
          autoFocus
          value={val}
          onChange={(e) => setVal(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") onSubmit(val); if (e.key === "Escape") onCancel(); }}
          placeholder={placeholder}
          className="w-full rounded-md border border-zinc-300 px-3 py-1.5 text-[13px] text-zinc-800 outline-none focus:border-blue-500"
        />
        <div className="mt-3 flex justify-end gap-2">
          <button className="rounded px-3 py-1 text-[12px] text-zinc-600 hover:bg-zinc-100" onClick={onCancel}>取消</button>
          <button className="rounded bg-blue-600 px-3 py-1 text-[12px] text-white hover:bg-blue-500" onClick={() => onSubmit(val)}>确定</button>
        </div>
      </div>
    </div>
  );
}

function FileRow({
  entry, depth, expanded, onToggle, onPick, onContext, onDoubleClick, onDragRef, projectId, loadChildren,
  renamingEntry, onRenameCommit, onRenameCancel, onRenameRequest,
}: {
  entry: FileEntry;
  depth: number;
  expanded: Set<string>;
  onToggle: (path: string) => void;
  onPick: (path: string) => void;
  onContext: (e: React.MouseEvent, entry: FileEntry) => void;
  onDoubleClick: (entry: FileEntry) => void;
  onDragRef: (e: React.DragEvent, entry: FileEntry) => void;
  projectId: string;
  loadChildren: (path: string) => Promise<FileEntry[]>;
  renamingEntry: FileEntry | null;
  onRenameCommit: (entry: FileEntry, name: string) => void;
  onRenameCancel: () => void;
  onRenameRequest: (entry: FileEntry) => void;
}) {
  const [children, setChildren] = useState<FileEntry[]>([]);
  const [loaded, setLoaded] = useState(false);
  // 阶段 7.9.5：内联重命名本地状态
  const [val, setVal] = useState(entry.name);
  const doneRef = useRef(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const isOpen = expanded.has(entry.path);
  const isDir = entry.type === "directory";
  const renaming = renamingEntry?.path === entry.path;

  // 进入重命名：重置输入并聚焦全选
  useEffect(() => {
    if (renaming) {
      setVal(entry.name);
      doneRef.current = false;
      inputRef.current?.focus();
      inputRef.current?.select();
    }
  }, [renaming, entry.name]);

  const commit = () => {
    if (doneRef.current) return;
    doneRef.current = true;
    onRenameCommit(entry, val.trim());
  };
  const cancel = () => {
    if (doneRef.current) return;
    doneRef.current = true;
    onRenameCancel();
  };

  const handleToggle = async () => {
    onToggle(entry.path);
    if (!loaded && isDir) {
      const kids = await loadChildren(entry.path);
      setChildren(kids);
      setLoaded(true);
    }
  };

  return (
    <>
      <button
        className="flex w-full items-center gap-1.5 rounded px-2 py-1 text-left text-[12.5px] text-zinc-700 hover:bg-zinc-100"
        style={{ paddingLeft: `${8 + depth * 14}px` }}
        onClick={() => (isDir ? handleToggle() : undefined)} // 阶段 7.9.2：取消单击引用（仅双击/右键/拖动）
        onKeyDown={(e) => { if (e.key === "F2") { e.preventDefault(); onRenameRequest(entry); } }} // 阶段 7.9.5：F2 内联重命名
        onContextMenu={(e) => onContext(e, entry)}
        onDoubleClick={() => onDoubleClick(entry)}
        draggable
        onDragStart={(e) => onDragRef(e, entry)}
        title={entry.path}
      >
        {isDir ? (
          isOpen ? <ChevronDown size={12} className="shrink-0 text-zinc-400" /> : <ChevronRight size={12} className="shrink-0 text-zinc-400" />
        ) : (
          <span className="w-3 shrink-0" />
        )}
        {isDir ? <Folder size={13} className="shrink-0 text-amber-500" /> : <File size={13} className="shrink-0 text-zinc-400" />}
        {renaming ? (
          /* 阶段 7.9.5：Windows 式内联编辑——名称原位变输入框（Enter/blur 确认、Esc 取消） */
          <input
            ref={inputRef}
            value={val}
            onChange={(e) => setVal(e.target.value)}
            onClick={(e) => e.stopPropagation()}
            onKeyDown={(e) => {
              e.stopPropagation();
              if (e.key === "Enter") commit();
              else if (e.key === "Escape") cancel();
            }}
            onBlur={commit}
            onDragStart={(e) => e.stopPropagation()}
            className="min-w-0 flex-1 rounded border border-blue-500 px-1 py-0.5 text-[12.5px] text-zinc-800 outline-none"
          />
        ) : (
          <span className="truncate">{entry.name}</span>
        )}
      </button>
      {isOpen && isDir && (
        <div className="space-y-0.5">
          {children.map((c) => (
            <FileRow
              key={c.path} entry={c} depth={depth + 1} expanded={expanded}
              onToggle={onToggle} onPick={onPick} onContext={onContext}
              onDoubleClick={onDoubleClick} onDragRef={onDragRef}
              projectId={projectId} loadChildren={loadChildren}
              renamingEntry={renamingEntry} onRenameCommit={onRenameCommit}
              onRenameCancel={onRenameCancel} onRenameRequest={onRenameRequest}
            />
          ))}
          {loaded && children.length === 0 && (
            <div className="px-3 py-1 text-[11px] text-zinc-400" style={{ paddingLeft: `${8 + (depth + 1) * 14}px` }}>
              空目录
            </div>
          )}
        </div>
      )}
    </>
  );
}

/** 引用图标（阶段 7.9.2） */
function LinkIcon() {
  return (
    <svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="shrink-0">
      <path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71" />
      <path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71" />
    </svg>
  );
}
