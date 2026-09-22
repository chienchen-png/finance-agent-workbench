/** chart-templates — ECharts 图表模板注册表（financial-modeling skill 图表层，P3 + P5 变体）。
 *
 * 模板即约束：AI 通过 generate_chart 选模板 + 提交数据，模板函数组装合法 ECharts option。
 * 前端 ChartRenderer 只信任本注册表产出的 option，防止非法配置。
 *
 * 每个类型：name（与后端 generate_chart 的 template 参数一致）/ zh / category /
 * description / build(默认变体) / variants（变体清单，P5-① 变体底座）。
 * 变体：template 名 = `类型-变体key`（如 "line-smooth"）；纯类型名（如 "line"）= 默认变体。
 * 注：模板不含 title——容器标题栏已展示表名（防元素堆叠）。
 */

import type { EChartsOption } from "echarts";

// ---------- 基础主题 ----------
export const CHART_COLORS = [
  "#2563eb", "#f97316", "#0d9488", "#db2777", "#7c3aed",
  "#059669", "#d97706", "#4f46e5",
];

export interface ChartSeries {
  name?: string;
  data: unknown[];
  type?: string;
  [k: string]: unknown;
}

export interface ChartData {
  categories?: string[];
  xCategories?: string[];
  yCategories?: string[];
  series?: ChartSeries[];
  indicators?: { name: string; max?: number }[];
  [k: string]: unknown;
}

export type ChartBuild = (data: ChartData, title?: string, overrides?: Record<string, unknown>) => EChartsOption;

export interface ChartVariant {
  key: string;            // 变体 key（template 全名 = `${name}-${key}`）；"" = 默认变体
  zh: string;             // 变体中文名
  description?: string;   // 变体用途（进 SKILL.md 选型表）
  build: ChartBuild;
}

export interface ChartTemplate {
  name: string;
  zh: string;
  category: "基础" | "对比" | "分布" | "关系" | "进阶";
  description: string;
  build: ChartBuild;              // 默认变体（= variants 中 key="" 或首个）
  variants: ChartVariant[];       // P5-①：变体清单（至少含默认变体）
}

// ---------- 各模板 ----------
import { buildLine, buildLineGroup, buildLineMultiX } from "./line";
import { buildBar, buildBarGroup, buildBarLine, buildBarNegative, buildBarFancy } from "./bar";
import { buildPie, buildPieSimple, buildPieHalfDonut, buildPieRounded, buildPieNested } from "./pie";
import { buildScatter, buildScatterEffect, buildScatterRegression } from "./scatter";
import { buildHeatmap, buildHeatmapDiscrete, buildHeatmapCalendar } from "./heatmap";
import { buildWaterfall, buildWaterfallBar } from "./waterfall";
import { buildRadar, buildRadarMulti } from "./radar";
import { buildBoxplot, buildBoxplotMulti } from "./boxplot";
import { buildHistogram } from "./histogram";
import { buildTornado } from "./tornado";
import { buildFunnel, buildFunnelCompare } from "./funnel";
import { buildDualAxis } from "./dual-axis";
import { buildSunburst } from "./sunburst";
import { buildSankey, buildSankeyVertical } from "./sankey";
import { buildGauge, buildGaugeProgress, buildGaugeStage } from "./gauge";
import { buildTreemap, buildTreemapDrilldown } from "./treemap";
import { buildGraph, buildGraphForce, buildGraphCircle } from "./graph";
import { buildParallel } from "./parallel";
import { buildErrorBar, buildErrorRange } from "./error-bar";
import { buildCalendar, buildCalendarYear } from "./calendar";
import { buildScatter3d } from "./scatter3d";
import { buildBar3d } from "./bar3d";
import { buildHistogram4Grid } from "./histogram-4grid";
import { buildWaterfall3d } from "./waterfall3d";

/** 辅助：构造单默认变体（P5-① 各类型至少注册默认变体，行为不变） */
function defaultVariant(zh: string, build: ChartBuild): ChartVariant[] {
  return [{ key: "", zh, description: "默认样式", build }];
}

export const CHART_TEMPLATES: ChartTemplate[] = [
  {
    name: "line",
    zh: "折线图",
    category: "基础",
    description: "时间序列趋势/多系列对比",
    build: buildLineGroup,
    // 2026-08-23 按用户附件重构：3 变体（simple/默认/line-multi-x）
    variants: [
      { key: "", zh: "多维折线图", description: "默认：多系列折线 + 极值/平均线对比", build: buildLineGroup },
      { key: "simple", zh: "简单折线图", description: "单系列基础折线", build: buildLine },
      { key: "multi-x", zh: "多x轴折线图", description: "双 x 轴，两时段同期对比", build: buildLineMultiX },
    ],
  },
  {
    name: "bar",
    zh: "柱状图",
    category: "对比",
    description: "类别对比/排名",
    build: buildBarGroup,
    // 2026-08-23 按用户附件重构：5 变体（simple/默认/negative/line/fancy）
    variants: [
      { key: "", zh: "分组柱状图", description: "默认：多系列并排对比", build: buildBarGroup },
      { key: "simple", zh: "简单柱状图", description: "单系列基础柱", build: buildBar },
      { key: "negative", zh: "正负条形图", description: "盈亏红绿区分（横向堆叠）", build: buildBarNegative },
      { key: "line", zh: "折线柱状图", description: "柱（量）+ 折线（率）双 y 轴", build: buildBarLine },
      { key: "fancy", zh: "分组折线柱状图", description: "多系列柱 + trend 折线串柱顶", build: buildBarFancy },
    ],
  },
  {
    name: "pie",
    zh: "饼图/环形图",
    category: "基础",
    description: "占比结构",
    build: buildPie,
    // P5-② 五变体
    variants: [
      { key: "", zh: "环形图", description: "默认：中空环形", build: buildPie },
      { key: "donut", zh: "环形图", description: "中空环形（= 默认）", build: buildPie },
      { key: "simple", zh: "基础饼图", description: "实心扇形", build: buildPieSimple },
      { key: "half-donut", zh: "半环形", description: "上半环，KPI 达成率", build: buildPieHalfDonut },
      { key: "rounded", zh: "圆角环形", description: "大圆角 + 扇区间隙", build: buildPieRounded },
      { key: "nested", zh: "嵌套环形", description: "内外两层（series 2 组）", build: buildPieNested },
    ],
  },
  {
    name: "scatter",
    zh: "散点图（+回归线）",
    category: "关系",
    description: "变量关系/回归可视化",
    build: buildScatter,
    // P5-② 三变体（v6.9.2：删 simple 消除重复——默认/effect/regression）
    variants: [
      { key: "", zh: "基础散点", description: "默认：散点 + 可选回归线系列", build: buildScatter },
      { key: "effect", zh: "涟漪散点", description: "重点点放大涟漪（Top-3 或 effectIndices）", build: buildScatterEffect },
      { key: "regression", zh: "回归散点", description: "散点 + 红色回归趋势线", build: buildScatterRegression },
    ],
  },
  {
    name: "heatmap",
    zh: "热力图",
    category: "关系",
    description: "相关矩阵/双变量敏感性",
    build: buildHeatmap,
    // P5-② 三变体
    variants: [
      { key: "", zh: "连续热力", description: "默认：连续色阶", build: buildHeatmap },
      { key: "simple", zh: "连续热力", description: "连续色阶（= 默认）", build: buildHeatmap },
      { key: "discrete", zh: "离散热力", description: "4 段离散色阶（等级/评分）", build: buildHeatmapDiscrete },
      { key: "calendar", zh: "日历热力", description: "按日期分布（calendarRange）", build: buildHeatmapCalendar },
    ],
  },
  {
    name: "waterfall",
    zh: "瀑布图",
    category: "对比",
    description: "差异桥接（期初→期末）",
    build: buildWaterfall,
    // P5-② 两变体
    variants: [
      { key: "", zh: "桥接瀑布", description: "默认：期初→调整→期末", build: buildWaterfall },
      { key: "simple", zh: "桥接瀑布", description: "桥接瀑布（= 默认）", build: buildWaterfall },
      { key: "bar", zh: "紧凑瀑布", description: "紧凑柱状瀑布，适合多增减项", build: buildWaterfallBar },
    ],
  },
  {
    name: "radar",
    zh: "雷达图",
    category: "对比",
    description: "多维指标对比（五维比率/杜邦）",
    build: buildRadar,
    // P5-② 两变体
    variants: [
      { key: "", zh: "基础雷达", description: "默认：单/多系列雷达", build: buildRadar },
      { key: "simple", zh: "基础雷达", description: "基础雷达（= 默认）", build: buildRadar },
      { key: "multi", zh: "多系列雷达", description: "杜邦/同业对比，面积分层", build: buildRadarMulti },
    ],
  },
  {
    name: "boxplot",
    zh: "箱线图",
    category: "分布",
    description: "分布对比（五数摘要）",
    build: buildBoxplot,
    // P5-② 两变体
    variants: [
      { key: "", zh: "单系列箱线", description: "默认：一组分布", build: buildBoxplot },
      { key: "simple", zh: "单系列箱线", description: "单系列箱线（= 默认）", build: buildBoxplot },
      { key: "multi", zh: "多系列箱线", description: "多系列分组对比", build: buildBoxplotMulti },
    ],
  },
  {
    name: "histogram",
    zh: "直方图",
    category: "分布",
    description: "分布形态（分箱频数）",
    build: buildHistogram,
    variants: defaultVariant("直方图", buildHistogram),
  },
  {
    name: "tornado",
    zh: "龙卷风图",
    category: "关系",
    description: "敏感性排序",
    build: buildTornado,
    variants: defaultVariant("龙卷风图", buildTornado),
  },
  {
    name: "funnel",
    zh: "漏斗图",
    category: "进阶",
    description: "阶段转化/流失",
    build: buildFunnel,
    // P5-② 两变体
    variants: [
      { key: "", zh: "转化漏斗", description: "默认：阶段转化", build: buildFunnel },
      { key: "simple", zh: "转化漏斗", description: "阶段转化（= 默认）", build: buildFunnel },
      { key: "compare", zh: "对比漏斗", description: "两个漏斗并列对比", build: buildFunnelCompare },
    ],
  },
  {
    name: "dual-axis",
    zh: "双轴组合图",
    category: "进阶",
    description: "两个量纲不同的系列对比",
    build: buildDualAxis,
    variants: defaultVariant("双轴组合图", buildDualAxis),
  },
  {
    name: "sunburst",
    zh: "旭日图",
    category: "进阶",
    description: "多层占比",
    build: buildSunburst,
    variants: defaultVariant("旭日图", buildSunburst),
  },
  {
    name: "sankey",
    zh: "桑基图",
    category: "进阶",
    description: "流量/资金流向",
    build: buildSankey,
    // P5-② 两变体
    variants: [
      { key: "", zh: "水平桑基", description: "默认：水平流向", build: buildSankey },
      { key: "simple", zh: "水平桑基", description: "水平流向（= 默认）", build: buildSankey },
      { key: "vertical", zh: "垂直桑基", description: "垂直分层（科目树）", build: buildSankeyVertical },
    ],
  },
  {
    name: "gauge",
    zh: "仪表盘",
    category: "进阶",
    description: "KPI 达成度",
    build: buildGauge,
    // P5-② 三变体
    variants: [
      { key: "", zh: "进度仪表", description: "默认：指针 + 进度弧", build: buildGauge },
      { key: "simple", zh: "进度仪表", description: "进度仪表（= 默认）", build: buildGauge },
      { key: "progress", zh: "大进度环", description: "环形进度，目标达成率", build: buildGaugeProgress },
      { key: "stage", zh: "阶段仪表", description: "红黄绿分段，KPI 预警", build: buildGaugeStage },
    ],
  },
  {
    name: "treemap",
    zh: "矩形树图",
    category: "进阶",
    description: "多层占比（科目/部门）",
    build: buildTreemap,
    // P5-③ 两变体
    variants: [
      { key: "", zh: "矩形树图", description: "默认：多层占比", build: buildTreemap },
      { key: "simple", zh: "矩形树图", description: "多层占比（= 默认）", build: buildTreemap },
      { key: "drilldown", zh: "下钻矩形树", description: "leafDepth=1 逐层下钻", build: buildTreemapDrilldown },
    ],
  },
  {
    name: "graph",
    zh: "关系图",
    category: "关系",
    description: "资金往来/科目关联网络",
    build: buildGraph,
    // P5-③ 两变体（v6.9：force 改无向网络——与默认有向网络差异化，消除重复）
    variants: [
      { key: "", zh: "有向网络", description: "默认：力导向 + 方向箭头（资金流向）", build: buildGraph },
      { key: "force", zh: "无向网络", description: "力导向无箭头（关联关系）", build: buildGraphForce },
      { key: "circle", zh: "环形关系图", description: "环形布局，层级环", build: buildGraphCircle },
    ],
  },
  {
    name: "parallel",
    zh: "平行坐标图",
    category: "关系",
    description: "多维实体对比",
    build: buildParallel,
    variants: [{ key: "", zh: "平行坐标", description: "默认：多维对比", build: buildParallel }],
  },
  {
    name: "error-bar",
    zh: "误差条/区间图",
    category: "分布",
    description: "预测区间/置信区间",
    build: buildErrorBar,
    // P5-③ 两变体
    variants: [
      { key: "", zh: "误差条", description: "默认：点 + 上下误差须", build: buildErrorBar },
      { key: "bar", zh: "误差条", description: "误差须（= 默认）", build: buildErrorBar },
      { key: "range", zh: "区间带", description: "上下界带状（置信区间）", build: buildErrorRange },
    ],
  },
  {
    name: "calendar",
    zh: "日历热力图",
    category: "进阶",
    description: "每日回款/支出热力",
    build: buildCalendar,
    // P5-③ 两变体
    variants: [
      { key: "", zh: "单年日历", description: "默认：单年日历热力", build: buildCalendar },
      { key: "simple", zh: "单年日历", description: "单年日历（= 默认）", build: buildCalendar },
      { key: "year", zh: "多年日历", description: "多年上下排列，跨年对比", build: buildCalendarYear },
    ],
  },
  {
    name: "scatter3d",
    zh: "三维散点图",
    category: "进阶",
    description: "三变量关系（可旋转/缩放）",
    build: buildScatter3d,
    // P6-②：L3 复杂档
    variants: [
      { key: "", zh: "三维散点", description: "气泡颜色深浅=第3维；拖拽旋转/缩放", build: buildScatter3d },
      { key: "simple", zh: "三维散点", description: "三维散点（= 默认）", build: buildScatter3d },
    ],
  },
  {
    name: "bar3d",
    zh: "三维柱状图",
    category: "进阶",
    description: "三维结构对比（可旋转/缩放）",
    build: buildBar3d,
    // P6-②：L3 复杂档
    variants: [
      { key: "", zh: "三维柱状", description: "柱高=值；柱色随高度深浅；拖拽旋转/缩放", build: buildBar3d },
      { key: "simple", zh: "三维柱状", description: "三维柱状（= 默认）", build: buildBar3d },
    ],
  },
  {
    name: "histogram-4grid",
    zh: "联动直方图",
    category: "分布",
    description: "散点 + 双向分箱联动（L3）",
    build: buildHistogram4Grid,
    // P6-②：L3 复杂档
    variants: [
      { key: "", zh: "联动直方图", description: "4 宫格：散点+双轴直方图（自研 sturges 分箱）", build: buildHistogram4Grid },
      { key: "simple", zh: "联动直方图", description: "联动直方图（= 默认）", build: buildHistogram4Grid },
    ],
  },
  {
    name: "waterfall3d",
    zh: "3D 瀑布图",
    category: "进阶",
    description: "多指标并排 3D 折线面（x=年份,y=指标,z=数值）",
    build: buildWaterfall3d,
    // L3 复杂档（2026-08-23：复刻财务指标对比.py）
    variants: [
      { key: "", zh: "3D 指标瀑布", description: "多指标并排 3D 折线+半透明面，蓝渐变（年份×指标×数值）", build: buildWaterfall3d },
    ],
  },
];

export const CHART_TEMPLATE_NAMES = CHART_TEMPLATES.map((t) => t.name);

/** 全部「类型-变体」名（供错误提示/SKILL.md 选型）：默认变体 = 类型名，其余 = `类型-key` */
export const CHART_VARIANT_NAMES: string[] = CHART_TEMPLATES.flatMap((t) => [
  t.name,
  ...t.variants.filter((v) => v.key && v.build !== t.build).map((v) => `${t.name}-${v.key}`),
]);

export interface ResolvedTemplate {
  tpl: ChartTemplate;
  variant: ChartVariant;
  /** 模板显示名（默认变体=类型名，否则=类型-变体） */
  display: string;
}

/**
 * 解析 template 名 → 类型 + 变体。
 * 规则：完整类型名（含连字符如 "bar-stacked"）→ 默认变体；
 *       否则按最长类型前缀匹配 `类型-变体key`（如 "line-smooth" → line/smooth）。
 */
export function resolveTemplate(name: string): ResolvedTemplate | undefined {
  if (!name) return undefined;
  // 1) 完整类型名（默认变体）
  const exact = CHART_TEMPLATES.find((t) => t.name === name);
  if (exact) {
    const def = exact.variants.find((v) => v.key === "") || exact.variants[0];
    return { tpl: exact, variant: def, display: exact.name };
  }
  // 2) 类型-变体（最长类型前缀优先，避免 "bar-stacked" 被 "bar" 抢）
  const sorted = [...CHART_TEMPLATES].sort((a, b) => b.name.length - a.name.length);
  for (const t of sorted) {
    if (name.startsWith(t.name + "-")) {
      const key = name.slice(t.name.length + 1);
      const v = t.variants.find((x) => x.key === key);
      if (v) return { tpl: t, variant: v, display: `${t.name}-${key}` };
    }
  }
  return undefined;
}

/** 按模板名取模板类型（向后兼容；未知变体名时仍可找到类型） */
export function getTemplate(name: string): ChartTemplate | undefined {
  return resolveTemplate(name)?.tpl;
}

/** 组装完整 option（模板+变体 build + 覆盖）。
 * v5.3-3：统一注入官方作品级动画（数据增长动画 + 缓动），
 * 所有模板输出"活"起来（对齐 ECharts 官方示例默认动画）。
 * 顶部/全局动画对全部 series 生效，series 内可覆盖。 */
export function buildChartOption(
  template: string,
  data: ChartData,
  title?: string,
  overrides?: Record<string, unknown>,
): EChartsOption | null {
  const resolved = resolveTemplate(template);
  if (!resolved) return null;
  const opt = resolved.variant.build(data, title) as Record<string, unknown>;
  // 官方级动画：数据增长 1500ms + 缓出（ECharts 官方示例默认观感）
  const withAnim = deepMerge(opt, { animationDuration: 1500, animationEasing: "cubicOut" });
  if (overrides && typeof overrides === "object") {
    return deepMerge(withAnim, overrides) as EChartsOption;
  }
  return withAnim as EChartsOption;
}

function deepMerge(base: Record<string, unknown>, override: Record<string, unknown>): Record<string, unknown> {
  const out: Record<string, unknown> = { ...base };
  for (const [k, v] of Object.entries(override)) {
    if (v && typeof v === "object" && !Array.isArray(v) && out[k] && typeof out[k] === "object" && !Array.isArray(out[k])) {
      out[k] = deepMerge(out[k] as Record<string, unknown>, v as Record<string, unknown>);
    } else {
      out[k] = v;
    }
  }
  return out;
}
