/** DataPanel — 项目数据面板（阶段 4：数据平面管理）。
 *
 * 功能：
 * - 已导入数据文件列表（文件/分表数/行数/状态/变更数角标）
 * - 操作按钮：引用 / 索引 / 写回 / 修改日志 / 删除（阶段 7.9 移除「重导」）
 * - 修改日志视图（Phase 17 P5）：字段级日志 + Excel 行列，写回剧本可视化
 * 对接：/api/project-data/*（routes/project_data.py）
 */

import { useEffect, useState } from "react";
import { X, Database, Table2, RefreshCw, FileSpreadsheet, Eye, RotateCw, History, Trash2, Link2, Pencil, Plus, Minus, ChevronDown, ChevronRight, AlertTriangle } from "lucide-react";
import {
  listDataFiles, dataIndex, exportData, deleteDataFile,
  dataChanges, exportStatus,
  type DataFileRecord, type DataSheet,
  type ChangeLogItem, type ChangeSummary,
} from "../lib/api";

export default function DataPanel({
  projectId,
  closing,
  onClose,
  onRefer,
}: {
  projectId: string;
  closing?: boolean; // 阶段 7.9.10.2：父级触发滑出动画中（渲染 drawer-anim-out）
  onClose: () => void;
  onRefer?: (ref: string) => void;
}) {
  const [files, setFiles] = useState<DataFileRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [detail, setDetail] = useState<{ file: DataFileRecord; sheets: DataSheet[] } | null>(null);
  // Phase 17 P5：修改日志视图（与 detail 互斥）
  const [logView, setLogView] = useState<{
    file: DataFileRecord; changes: ChangeLogItem[]; summary: ChangeSummary;
  } | null>(null);
  // Phase 17 P7：贴边框写回进度条（exportingId 当前写回的文件，progress 0-100）
  const [exportingId, setExportingId] = useState<string | null>(null);
  const [exportProgress, setExportProgress] = useState(0);
  const [exportFailed, setExportFailed] = useState(false);

  const load = async () => {
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
  };

  useEffect(() => { load(); }, [projectId]); // eslint-disable-line react-hooks/exhaustive-deps

  async function handleIndex(fileId: string) {
    try {
      const d = await dataIndex(fileId);
      setDetail({ file: d.file, sheets: d.sheets || [] });
    } catch (e) {
      alert(`查看索引失败: ${(e as Error).message}`);
    }
  }

  // Phase 17 P5：写回前联动日志摘要预览 + P7：异步任务 + 贴边框进度条轮询
  async function handleExport(file: DataFileRecord) {
    if (exportingId) {
      alert("已有文件正在写回，请等待完成。");
      return;
    }
    try {
      const { summary } = await dataChanges(file.id, { limit: 1 });
      if (!summary || summary.total === 0) {
        alert(`「${file.file_name}」暂无修改记录，无需写回。`);
        return;
      }
      const ok = confirm(
        `「${file.file_name}」将按修改日志写回 ${summary.total} 处：\n` +
        `更新 ${summary.update} · 插入 ${summary.insert} · 删除 ${summary.delete}\n\n` +
        `写回直接修改原文件，请确保文件未被 Excel 打开。\n\n确定写回？`,
      );
      if (!ok) return;

      // 异步任务：立即返回 export_id，轮询进度
      const { export_id } = await exportData(projectId, file.file_name, "precise");
      setExportingId(file.id);
      setExportProgress(0);
      setExportFailed(false);
      let lastErr = "";
      while (true) {
        await new Promise((r) => setTimeout(r, 500));
        const st = await exportStatus(export_id);
        setExportProgress(st.progress);
        if (st.status === "done") {
          setExportingId(null);
          alert(`写回完成：${st.message}`);
          await load();
          return;
        }
        if (st.status === "failed") {
          setExportFailed(true);
          lastErr = st.error || st.message;
          // Phase 17 P9：文件被占用 → 明确中文提示（关闭后重试）
          if (st.error_type === "file_locked" || /file_locked|被.*打开|占用/.test(lastErr)) {
            lastErr = `文件正被 Excel/Word 等程序打开，写入被锁定。\n请关闭该文件后重新写回。`;
          }
          break;
        }
      }
      await new Promise((r) => setTimeout(r, 1200)); // 失败条短暂停留
      setExportingId(null);
      alert(`写回失败: ${lastErr}`);
    } catch (e) {
      setExportingId(null);
      alert(`写回失败: ${(e as Error).message}`);
    }
  }

  // Phase 17 P5：查看字段级修改日志（写回剧本）
  async function handleLog(file: DataFileRecord) {
    try {
      const d = await dataChanges(file.id, { limit: 500 });
      setLogView({ file, changes: d.changes || [], summary: d.summary });
    } catch (e) {
      alert(`查看修改日志失败: ${(e as Error).message}`);
    }
  }

  async function handleDelete(file: DataFileRecord) {
    if (!confirm(`确定从数据库删除「${file.file_name}」？（不影响原始 Excel）`)) return;
    try {
      await deleteDataFile(file.id);
      await load();
    } catch (e) {
      alert(`删除失败: ${(e as Error).message}`);
    }
  }

  return (
    <div className={`drawer-anim absolute inset-y-0 right-0 z-20 flex w-80 flex-col border-l border-zinc-200 bg-white shadow-2xl ${closing ? "drawer-anim-out" : ""}`}>
      {/* 头部 */}
      <div className="flex items-center gap-2 border-b border-zinc-200 px-3 py-2">
        <Database size={14} className="text-blue-600" />
        <span className="text-sm font-medium text-zinc-700">项目数据库</span>
        <div className="ml-auto flex items-center gap-0.5">
          <button className="rounded p-1 text-zinc-400 hover:bg-zinc-100 hover:text-zinc-600" onClick={load} title="刷新">
            <RefreshCw size={13} />
          </button>
          <button className="rounded p-1 text-zinc-400 hover:bg-zinc-100 hover:text-zinc-600" onClick={onClose} title="关闭">
            <X size={14} />
          </button>
        </div>
      </div>

      {/* 修改日志视图（Phase 17 P5） */}
      {logView ? (
        <LogView
          file={logView.file}
          changes={logView.changes}
          summary={logView.summary}
          onBack={() => setLogView(null)}
          onWriteBack={() => {
            const f = logView.file;
            setLogView(null);
            void handleExport(f);
          }}
        />
      ) : detail ? (
        <IndexView
          file={detail.file}
          sheets={detail.sheets || []}
          onBack={() => setDetail(null)}
        />
      ) : (
        <div className="flex-1 overflow-y-auto p-2">
          {loading && <div className="p-3 text-[12px] text-zinc-400">加载中…</div>}
          {error && <div className="p-3 text-[12px] text-red-500">{error}</div>}
          {!loading && !error && files.length === 0 && (
            <div className="p-3 text-[12px] text-zinc-400">
              尚未导入数据文件。在项目目录中右键 Excel 文件，选择「添加到项目数据库」。
            </div>
          )}
          <div className="space-y-1">
            {files.map((f) => {
              const isExporting = exportingId === f.id;
              return (
              <div
                key={f.id}
                className={`group relative rounded-md border p-2 ${isExporting ? "border-blue-300" : "border-zinc-200 hover:border-blue-300"}`}
                draggable={!isExporting}
                onDragStart={(e) => {
                  // 阶段 7.9.2：数据库文件拖拽引用
                  e.dataTransfer.setData("text/plain", `@db:${f.file_name}`);
                  e.dataTransfer.effectAllowed = "copy";
                }}
              >
                {/* Phase 17 P7：贴边框细进度条（绝对定位，不占布局空间） */}
                {isExporting && (
                  <div className="absolute inset-x-0 top-0 h-0.5 overflow-hidden rounded-t-md bg-zinc-100">
                    <div
                      className={`h-full transition-[width] duration-300 ${exportFailed ? "bg-red-500" : "bg-blue-500"}`}
                      style={{ width: `${exportProgress}%` }}
                    />
                  </div>
                )}
                <div className="flex items-center gap-1.5">
                  <FileSpreadsheet size={13} className={f.status === "done" ? "text-green-600" : "text-zinc-400"} />
                  <span className="truncate text-[12px] text-zinc-700" title={f.file_name}>{f.file_name}</span>
                </div>
                <div className="mt-1 flex items-center gap-2 text-[10px] text-zinc-400">
                  <span>{f.total_rows} 行</span>
                  <span>{f.sheet_count} 分表</span>
                  <span className={f.status === "done" ? "text-green-600" : "text-amber-500"}>
                    {f.status === "done" ? "已导入" : f.status}
                  </span>
                  {/* Phase 17 P5：变更数角标（有待写回改动时显示） */}
                  {!!f.changes_count?.total && (
                    <span className="ml-auto flex items-center gap-0.5 rounded-full bg-blue-50 px-1.5 py-px text-[9px] font-medium text-blue-600">
                      <History size={9} />
                      {f.changes_count.total}
                    </span>
                  )}
                </div>
                {/* 操作按钮（hover 显示） */}
                <div className="mt-1 flex gap-1 opacity-0 transition-opacity group-hover:opacity-100">
                  <ActBtn icon={<Link2 size={11} />} label="引用" onClick={() => onRefer?.(`@db:${f.file_name}`)} />
                  <ActBtn icon={<Eye size={11} />} label="索引" onClick={() => handleIndex(f.id)} />
                  <ActBtn icon={<RotateCw size={11} />} label={isExporting ? `${Math.round(exportProgress)}%` : "写回"} disabled={isExporting} onClick={() => handleExport(f)} />
                  <ActBtn icon={<History size={11} />} label="日志" onClick={() => handleLog(f)} />
                  <ActBtn icon={<Trash2 size={11} />} label="删除" danger onClick={() => handleDelete(f)} />
                </div>
              </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}

function ActBtn({ icon, label, onClick, danger, disabled }: {
  icon: React.ReactNode; label: string; onClick: () => void; danger?: boolean; disabled?: boolean;
}) {
  return (
    <button
      className={`flex items-center gap-0.5 rounded px-1.5 py-0.5 text-[10px] ${
        disabled
          ? "cursor-not-allowed text-zinc-300"
          : danger ? "text-red-500 hover:bg-red-50" : "text-zinc-500 hover:bg-zinc-100"
      }`}
      onClick={onClick}
      disabled={disabled}
    >
      {icon}
      {label}
    </button>
  );
}

// ────────────────────────────────────────────────────────────────────
// Phase 17 P5：修改日志视图（字段级 + Excel 行列，写回剧本可视化）
// ────────────────────────────────────────────────────────────────────
const OP_META: Record<string, { icon: React.ReactNode; text: string; cls: string }> = {
  update: { icon: <Pencil size={10} className="text-blue-500" />, text: "更新", cls: "text-blue-600" },
  insert: { icon: <Plus size={10} className="text-green-500" />, text: "插入", cls: "text-green-600" },
  delete: { icon: <Minus size={10} className="text-red-500" />, text: "删除", cls: "text-red-600" },
};

function pretty(v: string | null): string {
  if (v === null || v === undefined) return "—";
  if (v === "") return "(空)";
  try {
    const p = JSON.parse(v);
    return p === null ? "(空)" : String(p);
  } catch {
    return v;
  }
}

function LogView({
  file, changes, summary, onBack, onWriteBack,
}: {
  file: DataFileRecord;
  changes: ChangeLogItem[];
  summary: ChangeSummary;
  onBack: () => void;
  onWriteBack: () => void;
}) {
  // 按 sheet 分组（保持日志顺序）
  const groups = new Map<string, ChangeLogItem[]>();
  for (const c of changes) {
    const list = groups.get(c.sheet_name) ?? [];
    list.push(c);
    groups.set(c.sheet_name, list);
  }
  const hasChanges = summary?.total > 0;

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex items-center gap-1 border-b border-zinc-200 px-3 py-2">
        <button className="rounded p-1 text-zinc-400 hover:bg-zinc-100 hover:text-zinc-600" onClick={onBack} title="返回列表">
          <X size={14} />
        </button>
        <span className="text-sm font-medium text-zinc-700">修改日志</span>
        {hasChanges && (
          <span className="ml-auto rounded-full bg-blue-50 px-1.5 py-px text-[9px] font-medium text-blue-600">
            共 {summary.total} 条
          </span>
        )}
      </div>

      <div className="border-b border-zinc-100 px-3 py-1">
        <p className="truncate text-[11px] text-zinc-500" title={file.file_name}>{file.file_name}</p>
      </div>

      <div className="flex-1 overflow-y-auto p-2">
        {hasChanges && (
          <div className="mb-2 flex items-center gap-2 rounded-md bg-zinc-50 px-2 py-1.5 text-[10px] text-zinc-500">
            <span className="font-medium text-zinc-600">{summary.total} 条修改</span>
            <span className="text-blue-600">更新 {summary.update}</span>
            <span className="text-green-600">插入 {summary.insert}</span>
            <span className="text-red-600">删除 {summary.delete}</span>
          </div>
        )}

        {!hasChanges && (
          <div className="p-3 text-[11px] leading-relaxed text-zinc-400">
            暂无修改记录。
            <br />
            AI 对数据的每一次增删改都会记录在这里，写回时按此清单执行。
          </div>
        )}

        {[...groups.entries()].map(([sheetName, items]) => (
          <div key={sheetName} className="mb-2">
            <div className="mb-1 flex items-center gap-1 px-0.5 text-[10px] font-medium text-zinc-500">
              <Table2 size={10} className="text-zinc-400" />
              {sheetName}
              <span className="text-zinc-300">({items.length})</span>
            </div>
            <div className="space-y-1">
              {items.map((c) => {
                const meta = OP_META[c.op_type] ?? OP_META.update;
                const loc =
                  c.excel_row != null
                    ? `第 ${c.excel_row} 行${c.excel_col ? ` · ${c.excel_col} 列` : ""}`
                    : "行已删除";
                return (
                  <div key={c.id} className="rounded-md border border-zinc-200 bg-white px-2 py-1.5">
                    <div className="flex items-center gap-1 text-[11px]">
                      {meta.icon}
                      <span className={`font-medium ${meta.cls}`}>{meta.text}</span>
                      <span className="truncate font-medium text-zinc-700">{c.col_name ?? "(整行)"}</span>
                      {c.key_value !== "" && c.key_value != null && (
                        <span className="truncate text-zinc-400">[{c.key_value}]</span>
                      )}
                      <span className="ml-auto shrink-0 text-[10px] text-zinc-400">{loc}</span>
                    </div>
                    <div className="mt-0.5 pl-4 text-[10px] text-zinc-500">
                      {c.op_type === "insert" ? (
                        <span className="text-green-700">+ {pretty(c.new_value)}</span>
                      ) : (
                        <>
                          <span className="text-zinc-400">{pretty(c.old_value)}</span>
                          <span className="mx-1 text-zinc-300">→</span>
                          <span className="font-medium text-zinc-700">{pretty(c.new_value)}</span>
                        </>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        ))}
      </div>

      {hasChanges && (
        <div className="border-t border-zinc-200 p-2">
          <button
            className="w-full rounded-md bg-blue-600 py-1.5 text-[12px] font-medium text-white hover:bg-blue-700"
            onClick={onWriteBack}
          >
            写回全部改动（{summary.total} 处）
          </button>
        </div>
      )}
    </div>
  );
}

// ────────────────────────────────────────────────────────────────────
// Phase 17 P6：数据索引视图（结构化表格化展示）
//   - 总览统计块：分表数 / 数据行 / 总列数 / 格式
//   - 分表卡片：表头位于 Excel 第 N 行 + 自动/用户确认徽标 + 置信度
//   - 字段清单表格：列字母 / 字段名 / 类型徽标 / 非空率 / 样例
//   - 未识别列警告：meta.uncorrected_cols（供用户核对识别是否完整）
// 注：导出供 AppDataPanel（应用项目数据库）复用。
// ────────────────────────────────────────────────────────────────────
const TYPE_META: Record<string, { label: string; cls: string }> = {
  text: { label: "文本", cls: "bg-zinc-100 text-zinc-600" },
  int: { label: "整数", cls: "bg-green-50 text-green-700" },
  float: { label: "小数", cls: "bg-blue-50 text-blue-700" },
  date: { label: "日期", cls: "bg-purple-50 text-purple-700" },
};

function colLetter(i: number): string {
  let n = i + 1;
  let s = "";
  while (n) {
    n--;
    s = String.fromCharCode(65 + (n % 26)) + s;
    n = Math.floor(n / 26);
  }
  return s;
}

function StatBox({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-zinc-200 bg-zinc-50 px-2 py-1.5 text-center">
      <div className="text-[11px] font-semibold text-zinc-700">{value}</div>
      <div className="text-[9px] text-zinc-400">{label}</div>
    </div>
  );
}

export function IndexView({
  file, sheets, onBack,
}: {
  file: DataFileRecord;
  sheets: DataSheet[];
  onBack: () => void;
}) {
  const layouts = file.meta?.layouts || {};
  const uncorrected = file.meta?.uncorrected_cols || {}; // sheet_name → 0-based 未识别列
  // 默认只展开第一个分表
  const [openSheets, setOpenSheets] = useState<Set<string>>(
    () => new Set(sheets.length ? [sheets[0].sheet_name] : []),
  );
  const totalCols = sheets.reduce((n, s) => n + (s.col_count || 0), 0);

  const toggle = (name: string) => {
    setOpenSheets((prev) => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });
  };

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex items-center gap-1 border-b border-zinc-200 px-3 py-2">
        <button className="rounded p-1 text-zinc-400 hover:bg-zinc-100 hover:text-zinc-600" onClick={onBack} title="返回列表">
          <X size={14} />
        </button>
        <span className="text-sm font-medium text-zinc-700">数据索引</span>
      </div>
      <div className="border-b border-zinc-100 px-3 py-1">
        <p className="truncate text-[11px] text-zinc-500" title={file.file_name}>{file.file_name}</p>
      </div>

      <div className="flex-1 overflow-y-auto p-2">
        {/* 总览统计块 */}
        <div className="mb-2 grid grid-cols-4 gap-1.5">
          <StatBox label="分表数" value={String(file.sheet_count ?? sheets.length)} />
          <StatBox label="数据行" value={String(file.total_rows ?? 0)} />
          <StatBox label="总列数" value={String(totalCols)} />
          <StatBox label="格式" value={file.format || "-"} />
        </div>

        {/* 分表卡片 */}
        <div className="space-y-1.5">
          {sheets.map((s) => {
            const lay = layouts[s.sheet_name] || {};
            const open = openSheets.has(s.sheet_name);
            return (
              <div key={s.sheet_name + s.sheet_index} className="rounded-md border border-zinc-200 bg-white">
                {/* 卡片头（点击折叠） */}
                <button
                  className="flex w-full items-center gap-1.5 px-2 py-1.5 text-left"
                  onClick={() => toggle(s.sheet_name)}
                >
                  {open ? (
                    <ChevronDown size={12} className="shrink-0 text-zinc-400" />
                  ) : (
                    <ChevronRight size={12} className="shrink-0 text-zinc-400" />
                  )}
                  <Table2 size={12} className="shrink-0 text-zinc-400" />
                  <span className="truncate text-[12px] font-medium text-zinc-700">{s.sheet_name}</span>
                  <span className="ml-auto shrink-0 text-[10px] text-zinc-400">{s.row_count}行×{s.col_count}列</span>
                </button>

                {/* 表头识别状态 */}
                <div className="flex items-center gap-1.5 px-2 pb-1.5">
                  <span className="text-[10px] text-zinc-500">
                    表头位于 Excel 第 <b className="text-zinc-700">{lay.excel_header_row ?? "-"}</b> 行
                  </span>
                  <span
                    className={`rounded-full px-1.5 py-px text-[9px] font-medium ${
                      lay.anchored_by === "user"
                        ? "bg-blue-50 text-blue-600"
                        : "bg-green-50 text-green-600"
                    }`}
                  >
                    {lay.anchored_by === "user" ? "用户确认" : "自动识别"}
                  </span>
                  {typeof lay.confidence === "number" && lay.confidence < 0.7 && (
                    <span className="rounded-full bg-amber-50 px-1.5 py-px text-[9px] font-medium text-amber-600">
                      低置信度
                    </span>
                  )}
                </div>

                {/* 未识别列警告（识别不完整时提示核对/重新上传） */}
                {(uncorrected[s.sheet_name] || []).length > 0 && (
                  <div className="mx-2 mb-1.5 flex items-start gap-1 rounded-md bg-amber-50 px-2 py-1 text-[10px] leading-relaxed text-amber-700">
                    <AlertTriangle size={11} className="mt-0.5 shrink-0" />
                    <span>
                      以下列未能自动识别为字段：
                      <b className="font-mono">{(uncorrected[s.sheet_name] || []).map((ci) => colLetter(ci)).join("、")}</b>
                      {lay.anchored_by === "user" ? "（已人工确认表头，可忽略）" : "（如确有表头，建议删除后重新上传）"}
                    </span>
                  </div>
                )}

                {/* 字段清单表格 */}
                {open && (
                  <div className="border-t border-zinc-100">
                    <div className="max-h-56 overflow-y-auto">
                      <table className="w-full border-collapse text-[10px]">
                        <thead>
                          <tr className="sticky top-0 bg-zinc-50 text-zinc-400">
                            <th className="px-2 py-1 text-left font-medium">列</th>
                            <th className="px-1 py-1 text-left font-medium">字段</th>
                            <th className="px-1 py-1 text-left font-medium">类型</th>
                            <th className="px-1 py-1 text-right font-medium">非空</th>
                            <th className="px-2 py-1 text-right font-medium">样例</th>
                          </tr>
                        </thead>
                        <tbody>
                          {(s.headers || []).map((h, i) => {
                            const tm = TYPE_META[h.type] || TYPE_META.text;
                            const samples = (h.samples || []).join(", ");
                            return (
                              <tr key={i} className="border-t border-zinc-100">
                                <td className="px-2 py-1 font-mono text-zinc-400">
                                  {h.excel_col ?? colLetter(i)}
                                </td>
                                <td className="max-w-[5.5rem] truncate px-1 py-1 font-medium text-zinc-700" title={h.name}>
                                  {h.name}
                                </td>
                                <td className="px-1 py-1">
                                  <span className={`rounded px-1 py-px text-[9px] font-medium ${tm.cls}`}>
                                    {tm.label}
                                  </span>
                                </td>
                                <td className="px-1 py-1 text-right text-zinc-500">
                                  {h.non_null_rate != null
                                    ? `${Math.round(h.non_null_rate * 100)}%`
                                    : "-"}
                                </td>
                                <td className="max-w-[4.5rem] truncate px-2 py-1 text-right text-zinc-400" title={samples}>
                                  {samples || "-"}
                                </td>
                              </tr>
                            );
                          })}
                        </tbody>
                      </table>
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
