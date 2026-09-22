/** MarkdownEditor — Vditor 封装的 Markdown 编辑器（文件预览 D2，2026-08-24）。
 *
 * 供两处共用：
 *  - 项目目录 md 文件双击预览（FilePreview）
 *  - 应用二「财务建模与分析」报告容器（FinModAppPage）
 *
 * 能力：
 *  - 渲染 + 编辑：Vditor 即时渲染（ir 模式，Typora 风格），工具栏可切换
 *    wysiwyg / 分屏预览；内置 Mermaid/ECharts/Graphviz/KaTeX 公式等按需渲染
 *  - 内网化：cdn 指向本地资源（BASE_URL + "vditor/"），零外网请求
 *  - 导出 PDF：Vditor 内置「导出」（浏览器打印窗口 → 另存为 PDF）
 *  - 导出 Word：自定义工具栏按钮 → onExportWord(md)（由调用方走后端 Pandoc）
 *  - 图片上传：传 uploadUrl 才显示「上传」按钮（对接 /api/files/upload）
 *
 * 注意：
 *  - initialValue 仅在挂载时生效；内容变化场景由调用方用 key 强制重挂载
 *    （FileEditor 按 filePath、报告容器按 run_id），保持组件简单。
 *  - 编辑内容通过 onChange 上抛，保存/导出由调用方决策。
 */

import { useEffect, useRef } from "react";
import Vditor from "vditor";
import "vditor/dist/index.css";

export interface MarkdownEditorProps {
  /** 初始 Markdown 内容（挂载时一次性生效） */
  initialValue: string;
  /** 输入回调（实时上抛编辑内容） */
  onChange?: (md: string) => void;
  /** 编辑器高度（默认 "auto" 自适应；数字=px） */
  height?: number | string;
  /** 只读预览模式（禁用输入，保留工具栏/导出） */
  readOnly?: boolean;
  /** 显示 Vditor 内置「导出 PDF」按钮 */
  showExport?: boolean;
  /** 导出 Word 回调（vditor 实例初始化后可用） */
  onExportWord?: (md: string) => void;
  /** 图片上传端点（含 query，如 /api/files/upload?project_id=x&path=dir）；
   *  提供才显示工具栏「上传」按钮 */
  uploadUrl?: string;
  /** 图片相对路径解析：把 md 中相对图片（如 assets/x.svg / 财务分析报告/x.svg）
   *  转为可在浏览器加载的完整 URL（如 /api/files/raw?project_id=&path=）。
   *  用于报告/文件预览时图片能被渲染；Word 导出走 Pandoc 用相对路径另处理。 */
  resolveImageUrl?: (path: string) => string;
  className?: string;
}

/** 工具栏：headings | bold italic strike | quote list ordered-list check |
 *  code inline-code | table link (upload?) | edit-mode both preview fullscreen
 *  outline | (export?) (exportWord?) —— 对齐财务场景，不含多余项。 */
const BASE_TOOLBAR: string[] = [
  "headings", "|",
  "bold", "italic", "strike", "|",
  "quote", "list", "ordered-list", "check", "|",
  "code", "inline-code", "|",
  "table", "link",
];

const TAIL_TOOLBAR: string[] = [
  "|", "edit-mode", "both", "preview", "fullscreen", "outline",
];

/** 导出 Word 自定义按钮图标（文档 + W） */
const EXPORT_WORD_ICON =
  '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/><path d="M8 15.5h8M8 18.5h8M8 12.5h3"/></svg>';

export default function MarkdownEditor({
  initialValue,
  onChange,
  height,
  readOnly = false,
  showExport = true,
  onExportWord,
  uploadUrl,
  resolveImageUrl,
  className,
}: MarkdownEditorProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const vditorRef = useRef<Vditor | null>(null);
  const resolveRef = useRef(resolveImageUrl);
  resolveRef.current = resolveImageUrl;
  // ref 转发回调，避免 Vditor 实例捕获过期闭包
  const onChangeRef = useRef(onChange);
  const onExportWordRef = useRef(onExportWord);
  onChangeRef.current = onChange;
  onExportWordRef.current = onExportWord;

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    // 内网化：BASE_URL 生产为 /static/app/（Flask 托管 dist），dev 为 /（vite public）
    const cdn = `${import.meta.env.BASE_URL}vditor/`;

    const toolbar: (string | { name: string; icon?: string; tip?: string; tipPosition?: string; click?: (event: Event, vditor: unknown) => void })[] = [
      ...BASE_TOOLBAR,
      ...(uploadUrl ? ["upload"] : []),
      ...TAIL_TOOLBAR,
      ...(showExport ? ["export"] : []),
      ...(onExportWord
        ? [{
            name: "exportWord",
            tip: "导出 Word",
            tipPosition: "s",
            icon: EXPORT_WORD_ICON,
            click: () => {
              // Vditor 回调第二参为内部 IVditor，不可直接 getValue——
              // 改用组件持有的 vditorRef（after 回调赋值）
              const md = vditorRef.current?.getValue() ?? "";
              onExportWordRef.current?.(md);
            },
          }]
        : []),
    ];

    // 渲染时把 md 中相对图片路径转为完整 URL（resolveImageUrl 回调），
    // 否则相对路径被浏览器解析为站点根下路径 → 404 → 图片裂图。
    const renderValue = (resolveRef.current && initialValue)
      ? initialValue.replace(
          /!\[([^\]]*)\]\(([^)"]+)\)/g,
          (full, alt: string, imgPath: string) => {
            // 跳过绝对 URL 与锚点
            if (/^(https?:|#|\/|mailto:|data:)/i.test(imgPath)) return full;
            return `![${alt}](${resolveRef.current!(imgPath.trim())})`;
          },
        )
      : initialValue;

    const vditor = new Vditor(el, {
      cdn,
      mode: "ir",
      value: renderValue,
      height: height ?? "auto",
      lang: "zh_CN",
      theme: "classic",
      icon: "ant",
      cache: { enable: false },
      toolbar,
      toolbarConfig: { hide: false, pin: false },
      preview: {
        delay: 300,
        hljs: { style: "github", lineNumber: false },
        markdown: {
          sanitize: true, // XSS 过滤（默认开，显式声明）
          toc: true,
          gfmAutoLink: true,
          footnotes: true,
        },
        theme: { current: "light" },
      },
      upload: uploadUrl
        ? (() => {
            // query（project_id/path）拆入 extraData 随 FormData 提交——
            // 后端 /api/files/upload 从 request.form 读取 project_id/path
            const qIdx = uploadUrl.indexOf("?");
            const url = qIdx >= 0 ? uploadUrl.slice(0, qIdx) : uploadUrl;
            const extraData: Record<string, string> = {};
            if (qIdx >= 0) {
              for (const [k, v] of new URLSearchParams(uploadUrl.slice(qIdx + 1))) {
                extraData[k] = v;
              }
            }
            return {
              url,
              extraData,
              fieldName: "file",
              max: 10 * 1024 * 1024,
              multiple: true,
            };
          })()
        : undefined,
      input: (value: string) => onChangeRef.current?.(value),
      after: () => {
        vditorRef.current = vditor;
        if (readOnly) vditor.disabled();
      },
    });

    return () => {
      vditor.destroy();
      vditorRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return <div ref={containerRef} className={className} />;
}
