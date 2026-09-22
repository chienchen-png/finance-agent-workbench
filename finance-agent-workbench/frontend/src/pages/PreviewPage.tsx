/** PreviewPage — 文件预览新标签页（D7，2026-08-24）。
 *
 * 由双击文件通过 window.open('/?preview=1&project_id=&path=') 打开。
 * 独立 SPA 标签页（无侧栏），复用 FileEditor 组件，实现：
 *   - 浏览器 tab 自由切换预览与主应用，不因关闭预览误关应用
 *   - 每次双击新开预览 tab，可同时预览多个文件
 *
 * URL 参数：
 *   preview=1        标记本页为预览模式（App 据此不显示主布局）
 *   project_id       项目 ID
 *   path             文件相对路径
 */
import { useEffect, useState } from "react";
import { ArrowLeft, FolderOpen } from "lucide-react";
import FileEditor from "../components/FileEditor";
import LoadingState from "../components/LoadingState";
import { listProjects, type Project } from "../lib/api";

export default function PreviewPage({
  projectId,
  filePath,
}: {
  projectId: string;
  filePath: string;
}) {
  const [project, setProject] = useState<Project | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    (async () => {
      try {
        // 校验项目存在并取名称（标题显示用）；失败不阻塞预览
        const list = await listProjects();
        if (cancelled) return;
        const p = list.find((x) => x.id === projectId) || null;
        setProject(p);
      } catch {
        setProject(null);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [projectId]);

  return (
    <div className="flex h-full flex-col bg-zinc-50">
      {/* 顶部条：返回主应用 + 标题（与 FileDrawer 风格一致） */}
      <div className="flex items-center gap-2 border-b border-zinc-200 bg-white px-3 py-2">
        {/* 返回主应用（新标签页跳转主 SPA） */}
        <a
          href="/"
          className="flex items-center gap-1.5 rounded-md px-2 py-1.5 text-[12px] text-zinc-500 transition-colors hover:bg-zinc-100 hover:text-zinc-800"
          title="返回主应用"
        >
          <ArrowLeft size={13} />
          返回主应用
        </a>
        <FolderOpen size={14} className="text-blue-600" />
        <span className="truncate text-[13px] font-medium text-zinc-700">
          {project ? `${project.name} / ` : ""}
          {filePath}
        </span>
        <span className="ml-auto text-[11px] text-zinc-400">预览标签页 · 可自由切换</span>
      </div>

      {/* 预览主体：全屏 FileEditor（无侧栏） */}
      <div className="min-h-0 flex-1">
        {loading ? (
          <div className="flex h-full items-center justify-center">
            <LoadingState label="正在加载预览…" />
          </div>
        ) : (
          <FileEditor
            projectId={projectId}
            filePath={filePath}
            onClose={() => { /* 预览标签页关闭由浏览器 tab 处理 */ }}
            onSaved={() => { /* 保存后不自动关闭，用户可继续编辑/导出 */ }}
          />
        )}
      </div>
    </div>
  );
}
