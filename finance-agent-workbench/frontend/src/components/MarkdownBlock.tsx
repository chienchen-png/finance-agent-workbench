/** MarkdownBlock — 通用 markdown 渲染（KaTeX $$ 公式 + GFM 表格）。

 * 与应用一 ChatPage 的 MarkdownText 同源（remark-gfm + remark-math + rehype-katex，
 * 关闭单 $ 防货币冲突）。应用二（财务建模）的模型卡/图表库/报告预览共用：
 * references 详情中的 `$$...$$` LaTeX 公式在此渲染。
 */

import type { ReactElement } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import "katex/dist/katex.min.css";

/** 与应用一 PROSE_CLASS 对齐（表格/代码块/标题间距） */
export const PROSE_CLASS =
  "prose-sm max-w-none text-sm leading-relaxed text-zinc-800 " +
  "[&_table]:my-2 [&_table]:w-full [&_table]:border-collapse [&_table]:border [&_table]:border-zinc-300 " +
  "[&_th]:border [&_th]:border-zinc-300 [&_th]:bg-zinc-100 [&_th]:px-2 [&_th]:py-1 " +
  "[&_td]:border [&_td]:border-zinc-300 [&_td]:px-2 [&_td]:py-1 " +
  "[&_pre]:my-2 [&_pre]:overflow-auto [&_pre]:rounded-md [&_pre]:bg-zinc-100 [&_pre]:p-3 " +
  "[&_code]:rounded [&_code]:bg-zinc-100 [&_code]:px-1 " +
  "[&_h1]:my-3 [&_h1]:text-lg [&_h2]:my-2 [&_h2]:text-base [&_h3]:my-2 [&_h3]:text-sm " +
  "[&_ul]:my-1 [&_ul]:list-disc [&_ul]:pl-5 [&_ol]:my-1 [&_ol]:list-decimal [&_ol]:pl-5";

/** 渲染单段 markdown（含 $$ 公式；空串渲染空块） */
export default function MarkdownBlock({
  text,
  className,
}: {
  text: string;
  className?: string;
}) {
  if (!text || !text.trim()) return null;
  return (
    <div className={className}>
      <Markdown
        remarkPlugins={[remarkGfm, [remarkMath, { singleDollarTextMath: false }]]}
      rehypePlugins={[[rehypeKatex, { strict: false, throwOnError: false }]]}
      components={{
        table: (props) => (
          <table className="my-2 w-full border-collapse border border-zinc-300" {...props} />
        ),
        th: (props) => (
          <th className="border border-zinc-300 bg-zinc-100 px-2 py-1 text-left" {...props} />
        ),
        td: (props) => (
          <td className="border border-zinc-300 px-2 py-1" {...props} />
        ),
        pre: (props) => (
          <pre className="my-2 overflow-auto rounded-md bg-zinc-100 p-3" {...props} />
        ),
        code: (props) => (
          <code className="rounded bg-zinc-100 px-1" {...props} />
        ),
        a: (props) => <a className="text-blue-600 hover:underline" {...props} />,
        h1: (props) => <h1 className="my-3 text-lg font-semibold" {...props} />,
        h2: (props) => <h2 className="my-2 text-base font-semibold" {...props} />,
        h3: (props) => <h3 className="my-2 text-sm font-semibold" {...props} />,
        ul: (props) => <ul className="my-1 list-disc pl-5" {...props} />,
        ol: (props) => <ol className="my-1 list-decimal pl-5" {...props} />,
      }}
    >
      {text}
    </Markdown>
    </div>
  );
}

/** 渲染多个 $$ 公式块（KaTeX 块级），供模型卡「关键公式」用 */
export function FormulaList({ formulas }: { formulas: string[] }) {
  if (!formulas || formulas.length === 0) return null;
  return (
    <div className="space-y-3">
      {formulas.map((f, i) => (
        <div
          key={i}
          className="overflow-x-auto rounded-lg border border-zinc-200 bg-zinc-50 px-3 py-2"
        >
          <MarkdownBlock text={`$$\n${f}\n$$`} />
        </div>
      ))}
    </div>
  );
}

/** 渲染通用 markdown 节点（供组件内部复用，避免重复引包） */
export function renderMd(text: string): ReactElement | null {
  return <MarkdownBlock text={text} />;
}
