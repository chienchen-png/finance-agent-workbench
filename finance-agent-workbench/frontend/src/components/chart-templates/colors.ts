/** colors — 配色工具（P6-② 配色方案）
 *
 * 为财务图表提供「主色系 → 同色系深浅」渐变配色（等价 matplotlib colormap）。
 * SKILL.md 步骤 5 配色询问：不限制（auto）/ 渐变色（选主色系）/ 自定义主题色。
 *
 * 实现：HSL 线性插值——保持色相 hue 不变，亮度 l 从浅（~0.82）到深（~0.35），
 * 饱和度随亮度微调，生成 n 档同色系深浅色。等价
 *   matplotlib Blues: np.linspace(0.3, 0.9, n)  →  本工具 gradientShades(main, n)
 */

/** 主色 hex → {h, s, l}（0-360/0-100/0-100） */
function hexToHsl(hex: string): { h: number; s: number; l: number } {
  let hx = hex.replace("#", "");
  if (hx.length === 3) hx = hx.split("").map((c) => c + c).join("");
  const r = parseInt(hx.slice(0, 2), 16) / 255;
  const g = parseInt(hx.slice(2, 4), 16) / 255;
  const b = parseInt(hx.slice(4, 6), 16) / 255;
  const max = Math.max(r, g, b);
  const min = Math.min(r, g, b);
  let h = 0;
  let s = 0;
  const l = (max + min) / 2;
  if (max !== min) {
    const d = max - min;
    s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
    switch (max) {
      case r: h = (g - b) / d + (g < b ? 6 : 0); break;
      case g: h = (b - r) / d + 2; break;
      default: h = (r - g) / d + 4;
    }
    h *= 60;
  }
  return { h, s: s * 100, l: l * 100 };
}

/** hsl → hex */
function hslToHex(h: number, s: number, l: number): string {
  const sn = s / 100;
  const ln = l / 100;
  const c = (1 - Math.abs(2 * ln - 1)) * sn;
  const x = c * (1 - Math.abs(((h / 60) % 2) - 1));
  const m = ln - c / 2;
  let r = 0, g = 0, b = 0;
  if (h < 60) { r = c; g = x; }
  else if (h < 120) { r = x; g = c; }
  else if (h < 180) { g = c; b = x; }
  else if (h < 240) { g = x; b = c; }
  else if (h < 300) { r = x; b = c; }
  else { r = c; b = x; }
  const to = (v: number) => Math.round((v + m) * 255).toString(16).padStart(2, "0");
  return `#${to(r)}${to(g)}${to(b)}`;
}

/** 返回主色的 n 档同色系深浅色（浅→深），等价 matplotlib colormap */
export function gradientShades(mainColor: string, n: number): string[] {
  const { h, s } = hexToHsl(mainColor);
  const shades: string[] = [];
  for (let i = 0; i < n; i++) {
    // 亮度从 82（浅）线性到 30（深），hslToHex 期望 0-100；饱和度在浅处略低
    const t = n <= 1 ? 0 : i / (n - 1);
    const l = (0.82 - t * 0.52) * 100;
    const sat = s * (0.7 + t * 0.4);
    shades.push(hslToHex(h, Math.min(100, sat), l));
  }
  return shades;
}

/** 预置主色系（SKILL.md 渐变色询问的选项；青色→黑色系 per 用户） */
export const COLOR_SCHEMES: Record<string, { main: string; zh: string }> = {
  blues:   { main: "#2563eb", zh: "蓝色系" },
  greens:  { main: "#059669", zh: "绿色系" },
  reds:    { main: "#dc2626", zh: "红色系" },
  oranges: { main: "#f97316", zh: "橙色系" },
  purples: { main: "#7c3aed", zh: "紫色系" },
  blacks:  { main: "#18181b", zh: "黑灰色系" },  // 原 teal 青 换成 黑→灰
};

export type ColorSchemeKey = keyof typeof COLOR_SCHEMES | "auto";

/** 按 scheme 取 n 档色（auto → 默认蓝橙多系列主题） */
export function schemeColors(scheme: ColorSchemeKey, n: number): string[] {
  if (scheme === "auto") {
    return ["#2563eb", "#f97316", "#0d9488", "#db2777", "#7c3aed", "#059669", "#d97706", "#4f46e5"];
  }
  const c = COLOR_SCHEMES[scheme];
  if (!c) return gradientShades("#2563eb", n);
  return n <= 1 ? [c.main] : gradientShades(c.main, n);
}
