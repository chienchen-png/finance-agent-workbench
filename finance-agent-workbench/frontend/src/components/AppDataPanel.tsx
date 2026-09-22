/** AppDataPanel — 数据核对应用专属「项目数据库」抽屉（2026-08-21）。
 *
 * 与通用 DataPanel 的区别（应用场景）：
 *  - 数据管理：上传 Excel / 删除数据文件 / 刷新列表
 *  - 索引核对：每文件可「查看索引」（复用 dataIndex 接口 + DataPanel 的 IndexView），
 *    展示表头识别/字段清单/未识别列，供用户确认识别是否正确；
 *    识别有误可删除后重新上传。
 *  - 不支持：引用、写回、修改日志（后续核对/写回流程已被向导固化）
 *  - 上传支持多文件：上传成功后自动触发导入（import_excel_to_db），
 *    进度实时显示；needs_anchor 时提示需要人工确认表头。
 *  - 每次「开始校验」用独立临时库快照，这里删除/重导不影响主库数据平面。
 *
 * 复用现有 API：listDataFiles / uploadFile / importDataFile / importStatus / deleteDataFile / dataIndex
 * 抽屉样式：drawer-anim（右侧滑入），与 FileDrawer/DataPanel 一致。
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { X, Database, RefreshCw, Upload, Loader2, FileSpreadsheet, Trash2, AlertTriangle, CheckCircle2, Eye, Table2 } from "lucide-react";
import {
  listDataFiles, uploadFile, importDataFile, importStatus, importAnchor, deleteDataFile, dataIndex,
  type DataFileRecord, type DataSheet,
} from "../lib/api";
import { IndexView } from "./DataPanel";

interface ImportTask {
  importId: string;
  fileName: string;
  progress: number;
  status: "running" | "done" | "failed" | "needs_anchor";
  message: string;
}

/** 待确认表头行的 sheet（来自 import/status 的 anchor.sheets） */
interface AnchorSheetInfo {
  name: string;
  /** 引擎建议表头行（0-based） */
  header_row: number;
  confidence: number;
  columns: string[];
}

/** 表头锚定确认任务（needs_anchor → 弹窗固定表单确认变量行/数据行） */
interface AnchorTask {
  importId: string;
  fileName: string;
  sheets: AnchorSheetInfo[];
  /** sheet → 预览行数组（每行 cell 值数组） */
  previews: Record<string, string[][]>;
}

export default function AppDataPanel({
  projectId,
  closing,
  onClose,
  onImported,
}: {
  projectId: string;
  closing?: boolean;
  onClose: () => void;
  /** 导入完成回调（通知向导刷新文件下拉） */
  onImported?: () => void;
}) {
  const [files, setFiles] = useState<DataFileRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [tasks, setTasks] = useState<ImportTask[]>([]);
  const [uploading, setUploading] = useState(false);
  const [detail, setDetail] = useState<{ file: DataFileRecord; sheets: DataSheet[] } | null>(null);
  // 表头锚定确认（needs_anchor → 固定表单确认变量行/数据行，替代项目中的 AI 询问）
  const [anchorTask, setAnchorTask] = useState<AnchorTask | null>(null);
  const [anchorRows, setAnchorRows] = useState<Record<string, string>>({});
  const [anchorBusy, setAnchorBusy] = useState(false);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const data = await listDataFiles(projectId);
      setFiles(data.files || []);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  useEffect(() => { void load(); }, [load]);

  /** 轮询导入进度（含 needs_anchor 人工确认表头）——定义在 handleUpload 前供其依赖 */
  const pollImport = useCallback(async (task: ImportTask) => {
    // V2 防卡死：总轮询上限（默认 5 分钟），超时标记失败避免永久 0% 转圈
    const startedAt = Date.now();
    const POLL_TIMEOUT_MS = 300_000;
    while (true) {
      if (Date.now() - startedAt > POLL_TIMEOUT_MS) {
        setTasks((prev) => prev.map((t) => t.importId === task.importId
          ? { ...t, status: "failed", message: "导入超时（>5 分钟），文件可能过大或含复杂公式；请尝试删除后重新上传" } : t));
        return;
      }
      await new Promise((r) => setTimeout(r, 600));
      let st: Record<string, unknown>;
      try {
        st = await importStatus(task.importId);
      } catch (e) {
        // 404 = 任务过期/后端重启 → 终止轮询（否则死循环刷屏）；
        // 其余网络抖动 → 继续重试
        if ((e as { status?: number }).status === 404) {
          setTasks((prev) => prev.map((t) => t.importId === task.importId
            ? { ...t, status: "failed", message: "导入任务已过期（后端可能已重启），请重新上传" } : t));
          return;
        }
        continue;
      }
      const status = String(st.status || "running");
      if (status === "done") {
        setTasks((prev) => prev.map((t) => t.importId === task.importId
          ? { ...t, status: "done", progress: 100, message: "导入完成" } : t));
        await load();
        onImported?.();
        return;
      }
      if (status === "failed") {
        setTasks((prev) => prev.map((t) => t.importId === task.importId
          ? { ...t, status: "failed", message: String(st.error || st.message || "导入失败") } : t));
        return;
      }
      if (status === "needs_anchor") {
        setTasks((prev) => prev.map((t) => t.importId === task.importId
          ? { ...t, status: "needs_anchor", message: "需人工确认表头行" } : t));
        // 弹出固定确认表单（替代项目里的 AI ask_user 询问）
        const anchor = (st.anchor || {}) as {
          sheets?: AnchorSheetInfo[];
          previews?: Record<string, string[][]>;
        };
        if (anchor.sheets && anchor.sheets.length > 0) {
          setAnchorTask({
            importId: task.importId,
            fileName: task.fileName,
            sheets: anchor.sheets,
            previews: anchor.previews || {},
          });
          // 默认值 = 引擎建议表头行（1-based 显示）
          const init: Record<string, string> = {};
          for (const s of anchor.sheets) init[s.name] = String((s.header_row ?? 0) + 1);
          setAnchorRows(init);
        }
        return;
      }
      // running：更新进度
      const progress = Number(st.progress || 0);
      setTasks((prev) => prev.map((t) => t.importId === task.importId
        ? { ...t, progress, message: `导入中 ${Math.round(progress)}%…` } : t));
    }
  }, [load, onImported]);

  /** 上传并导入 Excel（多文件） */
  const handleUpload = useCallback(async (fileList: FileList | null) => {
    if (!fileList || fileList.length === 0) return;
    setUploading(true);
    const pending: File[] = Array.from(fileList);
    // 1) 上传文件到应用工作区
    for (const file of pending) {
      try {
        await uploadFile(projectId, "", file);
      } catch (e) {
        const msg = (e as Error).message;
        // 工作区已有同名文件（删除数据库记录时原始 Excel 保留）→
        // 不是错误：跳过上传，下面直接按文件名触发导入即可。
        if (/同名文件已存在/.test(msg)) continue;
        setTasks((prev) => [...prev, {
          importId: `up_${Date.now()}_${file.name}`,
          fileName: file.name,
          progress: 0,
          status: "failed",
          message: `上传失败: ${msg}`,
        }]);
      }
    }
    // 2) 触发导入（import_excel_to_db），逐个跟踪进度
    // alwaysAnchor=true：每次上传都弹出表头确认（变量行/数据行）——
    // 应用固定化流程，不依赖 AI 询问，识别更精准。
    // V2 防重复导入：同一文件名已有 running/needs_anchor 任务 → 跳过（避免并发导入同一文件卡死）
    for (const file of pending) {
      const dup = tasks.some((t) => t.fileName === file.name &&
        (t.status === "running" || t.status === "needs_anchor"));
      if (dup) continue;
      try {
        const { import_id: importId } = await importDataFile(projectId, file.name, { alwaysAnchor: true });
        const task: ImportTask = {
          importId,
          fileName: file.name,
          progress: 0,
          status: "running",
          message: "导入中…",
        };
        setTasks((prev) => [...prev, task]);
        void pollImport(task);
      } catch (e) {
        setTasks((prev) => [...prev, {
          importId: `imp_${Date.now()}_${file.name}`,
          fileName: file.name,
          progress: 0,
          status: "failed",
          message: `导入失败: ${(e as Error).message}`,
        }]);
      }
    }
    setUploading(false);
    if (fileInputRef.current) fileInputRef.current.value = "";
  }, [projectId, tasks, pollImport]);

  /** 删除数据文件（主库数据平面；应用核对用临时库快照，删除不影响已有核对） */
  const handleDelete = useCallback(async (file: DataFileRecord) => {
    const ok = window.confirm(
      `确定删除数据文件「${file.file_name}」？\n` +
      `将从项目数据库中移除（${file.sheet_count} 个工作表 · ${(file.total_rows || 0).toLocaleString()} 行）。\n` +
      `删除后向导下拉将不再显示该文件；原始 Excel 仍保留在工作区。`,
    );
    if (!ok) return;
    try {
      await deleteDataFile(file.id);
      if (detail?.file.id === file.id) setDetail(null); // 正在查看该文件索引 → 返回列表
      await load();
      onImported?.();
    } catch (e) {
      alert(`删除失败: ${(e as Error).message}`);
    }
  }, [load, onImported, detail]);

  /** 查看索引：复用 dataIndex 接口展示字段识别结果，供用户核对识别是否正确 */
  const handleIndex = useCallback(async (fileId: string) => {
    try {
      const d = await dataIndex(fileId);
      setDetail({ file: d.file, sheets: d.sheets || [] });
    } catch (e) {
      alert(`查看索引失败: ${(e as Error).message}`);
    }
  }, []);

  /** 提交表头锚点：1-based 输入 → 0-based 提交 → 继续导入（固定化确认） */
  const handleAnchorSubmit = useCallback(async () => {
    if (!anchorTask) return;
    const anchors: Record<string, number> = {};
    for (const s of anchorTask.sheets) {
      const v = Number(anchorRows[s.name]);
      if (Number.isNaN(v) || v < 1) {
        alert(`请为工作表「${s.name}」填写有效的表头行号（≥1）`);
        return;
      }
      anchors[s.name] = v - 1; // 1-based UI → 0-based 后端
    }
    setAnchorBusy(true);
    try {
      await importAnchor(anchorTask.importId, anchors);
      // 恢复轮询：找到对应任务继续
      setTasks((prev) => {
        const t = prev.find((x) => x.importId === anchorTask.importId);
        if (t) void pollImport({ ...t, status: "running", progress: 0, message: "导入中…" });
        return prev.map((x) => x.importId === anchorTask.importId
          ? { ...x, status: "running", progress: 0, message: "导入中…" } : x);
      });
      setAnchorTask(null);
    } catch (e) {
      alert(`提交表头行失败: ${(e as Error).message}`);
    } finally {
      setAnchorBusy(false);
    }
  }, [anchorTask, anchorRows, pollImport]);

  /** 应用到全部 sheet（多数财务文件共用同一表头行） */
  const applyAnchorAll = useCallback((val: string) => {
    if (!anchorTask) return;
    const next: Record<string, string> = {};
    for (const s of anchorTask.sheets) next[s.name] = val;
    setAnchorRows(next);
  }, [anchorTask]);

  return (
    <div className={`drawer-anim absolute inset-y-0 right-0 z-20 flex w-[340px] flex-col border-l border-zinc-200 bg-white shadow-2xl ${closing ? "drawer-anim-out" : ""}`}>
      {/* 头部：标题 + 关闭 */}
      <div className="flex items-center gap-2 border-b border-zinc-200 px-3.5 py-2.5">
        <Database size={15} className="text-zinc-500" />
        <span className="text-[13px] font-semibold text-zinc-800">项目数据库</span>
        <span className="rounded-full bg-zinc-100 px-1.5 py-px text-[10px] text-zinc-500">
          {files.length} 个文件
        </span>
        <button
          onClick={onClose}
          className="ml-auto rounded-md p-1 text-zinc-400 transition-colors hover:bg-zinc-100 hover:text-zinc-600"
          aria-label="关闭数据库"
        >
          <X size={15} />
        </button>
      </div>

      {/* 索引视图：查看某文件的字段识别结果（核对无误后再用于核对） */}
      {detail ? (
        <IndexView
          file={detail.file}
          sheets={detail.sheets || []}
          onBack={() => setDetail(null)}
        />
      ) : (
        <>
          {/* 操作区：上传 + 刷新 */}
          <div className="flex items-center gap-1.5 border-b border-zinc-100 px-3.5 py-2">
            <button
              onClick={() => fileInputRef.current?.click()}
              disabled={uploading}
              className="flex flex-1 items-center justify-center gap-1 rounded-md bg-zinc-900 px-2 py-1.5 text-[11.5px] font-medium text-white transition-colors hover:bg-zinc-700 disabled:opacity-50"
            >
              {uploading ? <Loader2 size={12} className="animate-spin" /> : <Upload size={12} />}
              {uploading ? "上传中…" : "上传 Excel…"}
            </button>
            <button
              onClick={() => void load()}
              disabled={loading}
              className="flex items-center gap-1 rounded-md border border-zinc-200 px-2 py-1.5 text-[11.5px] text-zinc-600 transition-colors hover:bg-zinc-100 disabled:opacity-50"
              title="刷新列表"
            >
              <RefreshCw size={12} className={loading ? "animate-spin" : ""} />
              刷新
            </button>
            <input
              ref={fileInputRef}
              type="file"
              accept=".xls,.xlsx"
              multiple
              className="hidden"
              onChange={(e) => { void handleUpload(e.target.files); }}
            />
          </div>

          {/* 导入任务进度 */}
          {tasks.length > 0 && (
            <div className="max-h-40 space-y-1 overflow-y-auto border-b border-zinc-100 px-3.5 py-2">
              {tasks.map((t) => (
                <div key={t.importId} className="flex items-center gap-1.5 text-[11px]">
                  {t.status === "running" ? (
                    <Loader2 size={11} className="shrink-0 animate-spin text-zinc-400" />
                  ) : t.status === "done" ? (
                    <CheckCircle2 size={11} className="shrink-0 text-emerald-500" />
                  ) : t.status === "needs_anchor" ? (
                    <AlertTriangle size={11} className="shrink-0 text-amber-500" />
                  ) : (
                    <AlertTriangle size={11} className="shrink-0 text-red-500" />
                  )}
                  <span className="min-w-0 flex-1 truncate text-zinc-600" title={t.fileName}>{t.fileName}</span>
                  <span className="shrink-0 text-zinc-400">
                    {t.status === "running" ? `${Math.round(t.progress)}%` : t.message}
                  </span>
                </div>
              ))}
            </div>
          )}

          {/* 文件列表 */}
          <div className="flex-1 overflow-y-auto p-2">
            {loading ? (
              <div className="flex items-center justify-center gap-2 py-8 text-[12px] text-zinc-400">
                <Loader2 size={13} className="animate-spin" /> 加载中…
              </div>
            ) : error ? (
              <p className="px-2 py-6 text-center text-[12px] text-red-500">{error}</p>
            ) : files.length === 0 ? (
              <div className="px-2 py-10 text-center">
                <FileSpreadsheet size={22} className="mx-auto mb-2 text-zinc-300" />
                <p className="text-[12px] text-zinc-400">暂无数据文件</p>
                <p className="mt-0.5 text-[11px] text-zinc-300">点「上传 Excel…」导入数据表</p>
              </div>
            ) : (
              <ul className="space-y-1">
                {files.map((f) => (
                  <li key={f.id} className="group flex items-center gap-2 rounded-lg px-2 py-1.5 transition-colors hover:bg-zinc-50">
                    <FileSpreadsheet size={14} className="shrink-0 text-zinc-400" />
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-[12px] text-zinc-700" title={f.file_name}>{f.file_name}</p>
                      <p className="text-[10.5px] text-zinc-400">
                        {f.sheet_count} 个 sheet · {(f.total_rows || 0).toLocaleString()} 行
                        {f.status === "failed" && <span className="ml-1 text-red-500">导入失败</span>}
                      </p>
                    </div>
                    <button
                      onClick={() => void handleIndex(f.id)}
                      className="shrink-0 rounded-md p-1 text-zinc-300 transition-colors hover:bg-zinc-100 hover:text-zinc-600"
                      title="查看索引（核对字段识别是否正确）"
                    >
                      <Eye size={13} />
                    </button>
                    <button
                      onClick={() => void handleDelete(f)}
                      className="shrink-0 rounded-md p-1 text-zinc-300 transition-colors hover:bg-red-50 hover:text-red-500"
                      title="删除该文件"
                    >
                      <Trash2 size={13} />
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </>
      )}

      {/* 底部说明 */}
      <div className="border-t border-zinc-100 px-3.5 py-2">
        <p className="text-[10.5px] leading-relaxed text-zinc-400">
          数据库用于向导选择核对文件。每次「开始校验」会在独立临时库执行，
          此处的删除/刷新不影响已完成的核对结果。上传 Excel 后自动导入入库，
          可点 <Eye size={9} className="inline text-zinc-400" /> 查看索引核对字段识别，识别有误可删除后重新上传。
        </p>
      </div>

      {/* 表头锚定确认（needs_anchor 固定表单：确认变量行/数据行，识别更精准） */}
      {anchorTask && (
        <div className="absolute inset-0 z-30 flex flex-col bg-white">
          {/* 头部 */}
          <div className="flex items-center gap-2 border-b border-zinc-200 px-3.5 py-2.5">
            <Table2 size={15} className="text-zinc-500" />
            <span className="text-[13px] font-semibold text-zinc-800">确认表头行</span>
            <button
              onClick={() => setAnchorTask(null)}
              disabled={anchorBusy}
              className="ml-auto rounded-md p-1 text-zinc-400 transition-colors hover:bg-zinc-100 hover:text-zinc-600"
              title="取消导入"
            >
              <X size={15} />
            </button>
          </div>

          {/* 说明 */}
          <div className="border-b border-zinc-100 px-3.5 py-2">
            <p className="text-[11px] leading-relaxed text-zinc-500">
              「{anchorTask.fileName}」已读取 {anchorTask.sheets.length} 个工作表。
              请对照下方预览，为每个工作表指定<b className="text-zinc-700">变量行（表头行）</b>，
              其下一行即数据行。确认后按此精确导入，字段识别更精准。
            </p>
          </div>

          {/* sheet 列表（可滚动） */}
          <div className="min-h-0 flex-1 space-y-2 overflow-y-auto p-3">
            {anchorTask.sheets.map((s) => {
              const preview = anchorTask.previews[s.name] || [];
              return (
                <div key={s.name} className="overflow-hidden rounded-lg border border-zinc-200">
                  <div className="flex items-center gap-1.5 border-b border-zinc-100 bg-zinc-50 px-2.5 py-1.5">
                    <Table2 size={11} className="shrink-0 text-zinc-400" />
                    <span className="truncate text-[11.5px] font-medium text-zinc-700">{s.name}</span>
                    <span className="ml-auto shrink-0 text-[10px] text-zinc-400">
                      引擎建议第 {(s.header_row ?? 0) + 1} 行
                    </span>
                  </div>
                  {/* 预览表（前 8 行） */}
                  <div className="max-h-40 overflow-auto">
                    <table className="w-full border-collapse text-[10px]">
                      <tbody>
                        {preview.map((row, ri) => (
                          <tr key={ri} className="border-b border-zinc-50">
                            <td className="w-7 shrink-0 bg-zinc-50 px-1 py-0.5 text-right font-mono text-zinc-300">
                              {ri + 1}
                            </td>
                            {row.slice(0, 8).map((cell, ci) => (
                              <td key={ci} className="max-w-[4.5rem] truncate px-1.5 py-0.5 text-zinc-600" title={cell}>
                                {cell || ""}
                              </td>
                            ))}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  {/* 表头行输入 */}
                  <div className="flex items-center gap-2 px-2.5 py-2">
                    <span className="text-[11px] text-zinc-500">表头行（第几行）</span>
                    <input
                      type="number"
                      min={1}
                      value={anchorRows[s.name] ?? ""}
                      disabled={anchorBusy}
                      onChange={(e) => setAnchorRows((prev) => ({ ...prev, [s.name]: e.target.value }))}
                      className="w-16 rounded-md border border-zinc-200 px-2 py-1 text-[12px] text-zinc-800 outline-none transition-colors focus:border-zinc-400"
                    />
                    {Number(anchorRows[s.name]) >= 1 && (
                      <span className="text-[10px] text-zinc-400">数据行 = 第 {Number(anchorRows[s.name]) + 1} 行</span>
                    )}
                  </div>
                </div>
              );
            })}
          </div>

          {/* 底部操作 */}
          <div className="border-t border-zinc-100 px-3.5 py-2">
            <div className="mb-2 flex items-center gap-1.5">
              <span className="text-[11px] text-zinc-500">全部 sheet 表头同在第</span>
              <input
                type="number"
                min={1}
                disabled={anchorBusy}
                onChange={(e) => applyAnchorAll(e.target.value)}
                className="w-14 rounded-md border border-zinc-200 px-2 py-1 text-[11.5px] text-zinc-700 outline-none transition-colors focus:border-zinc-400"
                placeholder="行"
              />
              <span className="text-[11px] text-zinc-500">行？</span>
              <button
                onClick={() => {
                  const first = anchorTask.sheets[0] ? anchorRows[anchorTask.sheets[0].name] : "";
                  applyAnchorAll(first);
                }}
                disabled={anchorBusy}
                className="ml-auto rounded-md border border-zinc-200 px-2 py-1 text-[10.5px] text-zinc-600 transition-colors hover:bg-zinc-100"
              >
                套用第一个
              </button>
            </div>
            <div className="flex items-center gap-2">
              <button
                onClick={() => setAnchorTask(null)}
                disabled={anchorBusy}
                className="rounded-md border border-zinc-200 px-3 py-1.5 text-[11.5px] text-zinc-600 transition-colors hover:bg-zinc-100"
              >
                取消导入
              </button>
              <button
                onClick={() => void handleAnchorSubmit()}
                disabled={anchorBusy}
                className="flex flex-1 items-center justify-center gap-1.5 rounded-md bg-zinc-900 px-3 py-1.5 text-[11.5px] font-medium text-white transition-colors hover:bg-zinc-700 disabled:opacity-50"
              >
                {anchorBusy ? <Loader2 size={12} className="animate-spin" /> : <CheckCircle2 size={12} />}
                {anchorBusy ? "提交中…" : "确认并继续导入"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
