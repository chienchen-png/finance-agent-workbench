/** ModelIcon — AI 模型官方 logo（阶段 7.9.2 / 方案 A）。
 *
 * 图标来源优先级（数据库驱动，AI 配置页 = 唯一源头）：
 *   1. 模型.icon 字段（数据库存储，用户可在 AI 配置页个性化指定）
 *   2. 按名称匹配内置官方 logo（/static/img/models/*.png）
 *   3. 回退 generic.svg
 * 尺寸小（默认 12px，与周边图标一致），避免视觉冗杂。
 */

const ICON_BASE = "/static/img/models";

// 名称关键字 → logo 文件（顺序即优先级）
const ICON_MAP: [string, string][] = [
  ["deepseek", "deepseek.png"],
  ["glm", "glm.png"],
  ["qwen", "qwen.png"],
  ["claude", "claude.png"],
  ["gemini", "gemini.png"],
  ["gpt", "openai.png"],
  ["openai", "openai.png"],
];

/** 内置图标库（供选择器展示）：文件名 → 显示名 */
export const MODEL_ICON_LIBRARY: { file: string; label: string }[] = [
  { file: "deepseek.png", label: "DeepSeek" },
  { file: "glm.png", label: "GLM" },
  { file: "qwen.png", label: "通义千问" },
  { file: "claude.png", label: "Claude" },
  { file: "gemini.png", label: "Gemini" },
  { file: "openai.png", label: "OpenAI" },
  { file: "generic.svg", label: "通用" },
];

/** 名称 → 自动匹配的内置图标文件名（无匹配返回 generic.svg） */
export function matchModelIcon(name: string): string {
  const lower = String(name || "").toLowerCase();
  for (const [key, file] of ICON_MAP) {
    if (lower.includes(key)) return file;
  }
  return "generic.svg";
}

/** 解析最终图标 URL：优先 icon 字段（数据库），其次名称匹配，最后 generic。 */
export function resolveModelIcon(name: string, icon?: string | null): string {
  // 1. 数据库 icon（可能是文件名或完整 URL）
  if (icon) {
    if (icon.startsWith("http://") || icon.startsWith("https://") || icon.startsWith("/")) {
      return icon; // 完整 URL 或绝对路径直接用
    }
    return `${ICON_BASE}/${icon}`; // 纯文件名 → 拼到图标目录
  }
  // 2. 名称匹配内置 logo
  const lower = String(name || "").toLowerCase();
  for (const [key, file] of ICON_MAP) {
    if (lower.includes(key)) return `${ICON_BASE}/${file}`;
  }
  // 3. 回退通用图标
  return `${ICON_BASE}/generic.svg`;
}

export default function ModelIcon({
  name,
  icon,
  size = 12,
  className = "",
}: {
  name: string;
  icon?: string | null;
  size?: number;
  className?: string;
}) {
  return (
    <img
      src={resolveModelIcon(name, icon)}
      width={size}
      height={size}
      alt=""
      loading="lazy"
      className={`shrink-0 rounded-sm object-contain ${className}`}
    />
  );
}
