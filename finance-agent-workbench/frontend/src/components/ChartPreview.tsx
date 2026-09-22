/** ChartPreview — 财务建模「图表预览」（P4 图表配置，2026-08-21）。

 * 与需求文档 §5.2「ChartPreview 图表预览」对齐：小尺寸 ChartRenderer
 * （复用 chart-templates 模板函数 + 示例数据），所见即所得（R6——
 * 预览与最终图同一渲染器 buildChartOption）。
 *
 * 实现：按模板类型生成最小示例数据 → buildChartOption 组装 → 独立小
 * ECharts 实例渲染（h-28，无标题/下载/数据表，仅图形预览）。
 */

import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import * as echarts from "echarts";
import "echarts-gl";
import { buildChartOption, resolveTemplate } from "./chart-templates";
import { finmodPyChart } from "../lib/api";
import PythonImageLightbox from "./PythonImageLightbox";

/** 示例数据生成（按模板类型，官方级大数据量演示数据集 v5.3-3）。
 * 数据量对齐 ECharts 官方示例（12-30 点），让预览图"内容丰富、看起来专业"：
 *  - 24 个月份 / 20+ 项占比 / 60 点散点 / 8×6 热力 / 8 因素龙卷风…
 */
export function sampleDataFor(template: string): Record<string, unknown> {
  // v6.8-2：取真正类型名（resolveTemplate 完整解析）——不能 split("-")[0]，
  // 否则 dual-axis→dual、error-bar→error、histogram-4grid→histogram 匹配不到 case
  const base = resolveTemplate(template)?.tpl.name ?? template;
  // 24 个月份类别（财务语境：月度趋势，大数据量官方观感——折线/柱状越密越好看）
  const months = Array.from({ length: 24 }, (_, i) => `${i + 1}月`);
  // 24 个月平滑增长趋势（带季节波动，折线图丰富）
  const trend = [820, 890, 855, 930, 1010, 975, 1080, 1160, 1120, 1210, 1290, 1245,
                 1330, 1410, 1370, 1450, 1530, 1490, 1580, 1660, 1620, 1710, 1790, 1860];
  const forecast = Array.from({ length: 24 }, (_, i) => (i < 18 ? null : trend[i] + 40 + (i - 18) * 35));
  switch (base) {
    case "line": {
      // 折线图（2026-08-23 重构）：默认=多维分组对比 / simple=单系列 / multi-x=双x轴
      const vk = resolveTemplate(template)?.variant?.key ?? "";
      if (vk === "multi-x") {
        // 多x轴：两组时段折线（2015/2016 各 12 月）
        const m15 = Array.from({ length: 12 }, (_, i) => `2015-${i + 1}`);
        const m16 = Array.from({ length: 12 }, (_, i) => `2016-${i + 1}`);
        return {
          xCategories: m16,
          xCategories2: m15,
          series: [
            { name: "2016年回款", xAxisIndex: 0, data: [430, 520, 611, 187, 483, 692, 2316, 466, 554, 184, 103, 700] },
            { name: "2015年回款", xAxisIndex: 1, data: [260, 590, 900, 264, 287, 707, 1756, 1822, 487, 188, 60, 230] },
          ],
        };
      }
      if (vk === "simple") {
        return {
          categories: months,
          series: [{ name: "收入", data: trend }],
        };
      }
      // 默认：多维分组对比（最高/最低双系列 + 极值/平均线）
      return {
        categories: ["1月", "2月", "3月", "4月", "5月", "6月", "7月"],
        series: [
          { name: "最高", data: [100, 110, 130, 110, 120, 120, 90] },
          { name: "最低", data: [10, -20, 20, 50, 30, 20, 0] },
        ],
      };
    }
    case "bar": {
      // 柱状图（2026-08-23 重构）：默认=分组柱状 / simple=单系列 / negative=正负条 / line=折线柱 / fancy=分组折线柱
      const vk = resolveTemplate(template)?.variant?.key ?? "";
      const cats4 = ["产品A", "产品B", "产品C", "产品D"];
      if (vk === "simple") {
        return { categories: cats4, series: [{ name: "销售额", data: [920, 830, 760, 610] }] };
      }
      if (vk === "negative") {
        return {
          categories: ["周一", "周二", "周三", "周四", "周五", "周六", "周日"],
          series: [
            { name: "利润", data: [200, 170, 240, 244, 200, 220, 210] },
            { name: "费用", data: [-120, -132, -101, -134, -190, -230, -210] },
          ],
        };
      }
      if (vk === "line") {
        return {
          categories: ["1月", "2月", "3月", "4月", "5月", "6月", "7月", "8月", "9月", "10月", "11月", "12月"],
          yAxis0Name: "销售额",
          yAxis1Name: "毛利率%",
          series: [
            { name: "销售额", type: "bar", data: [200, 490, 700, 2320, 2560, 7670, 13560, 16220, 3260, 2000, 640, 330] },
            { name: "毛利率", type: "line", data: [20, 22, 33, 45, 63, 102, 203, 234, 230, 165, 120, 62] },
          ],
        };
      }
      if (vk === "fancy") {
        // 分组折线柱：30 类目 × 3 年柱 + custom trend
        const cats30 = Array.from({ length: 30 }, (_, i) => `类别${i}`);
        const cData = (seed: number): number[] =>
          Array.from({ length: 30 }, (_, i) => Number((Math.abs(Math.sin(i * seed) * 1000) + 100).toFixed(0)));
        const y1 = cData(1.3), y2 = cData(2.7), y3 = cData(3.9);
        return {
          categories: cats30,
          series: [
            { type: "custom", name: "trend", data: cats30.map((_, i) => [i, y1[i], y2[i], y3[i]]) },
            { name: "2023", data: y1 },
            { name: "2024", data: y2 },
            { name: "2025", data: y3 },
          ],
        };
      }
      // 默认：分组柱状图（多系列并排）
      return {
        categories: cats4,
        series: [
          { name: "2023", data: [433, 831, 864, 724] },
          { name: "2024", data: [858, 734, 652, 539] },
          { name: "2025", data: [937, 551, 825, 391] },
        ],
      };
    }
    case "dual-axis":
    case "waterfall":
      return {
        categories: months,
        series: [
          { name: "实际", data: trend },
          { name: "预测", data: forecast },
        ],
      };
    case "pie":
    case "funnel":
      // pie/funnel 的 build 读取 categories + 数值数组
      return {
        categories: ["华东", "华北", "华南", "西南", "华中", "东北", "西北", "出口"],
        series: [{ name: "占比", data: [45.2, 36.8, 28.5, 22.1, 18.7, 12.4, 9.3, 6.8] }],
      };
    case "sunburst":
    case "treemap":
      // sunburst/treemap 的 build 读取 series[0].data 树结构（对象数组）
      return {
        series: [{
          name: "占比",
          data: [
            { name: "华东", value: 45.2 }, { name: "华北", value: 36.8 }, { name: "华南", value: 28.5 },
            { name: "西南", value: 22.1 }, { name: "华中", value: 18.7 }, { name: "东北", value: 12.4 },
            { name: "西北", value: 9.3 }, { name: "出口", value: 6.8 },
          ],
        }],
      };
    case "scatter":
      // v6.9.2：仿 ECharts 官网 scatter-linear-regression——150 点围绕回归线
      // y = 0.7x + 5 收敛 + 确定性高斯噪声（±2.4），数据量大且真实分散
      return {
        series: [{
          name: "样本",
          data: (() => {
            const pts: number[][] = [];
            for (let i = 0; i < 150; i++) {
              const x = ((i * 0.2) % 30) + ((i * 37) % 10) * 0.11;
              // 确定性伪随机噪声（sin 哈希，渲染稳定不随机）
              const h1 = Math.abs(Math.sin(i * 12.9898) * 43758.5453) % 1;
              const h2 = Math.abs(Math.sin(i * 78.233) * 12543.123) % 1;
              const noise = (h1 + h2 - 1) * 2.4;
              const y = 0.7 * x + 5 + noise;
              pts.push([+x.toFixed(1), +y.toFixed(1)]);
            }
            return pts;
          })(),
        }],
      };
    case "radar":
      return {
        indicators: [
          { name: "盈利", max: 100 }, { name: "营运", max: 100 }, { name: "杠杆", max: 100 },
          { name: "成长", max: 100 }, { name: "偿债", max: 100 }, { name: "效率", max: 100 },
        ],
        series: [
          { name: "本年", data: [{ value: [82, 68, 55, 74, 88, 61] }] },
          { name: "上年", data: [{ value: [70, 60, 62, 58, 80, 55] }] },
        ],
      };
    case "heatmap":
      return {
        xCategories: ["1月", "2月", "3月", "4月", "5月", "6月", "7月", "8月"],
        yCategories: ["产品A", "产品B", "产品C", "产品D", "产品E", "产品F"],
        series: [{
          name: "相关",
          // 8×6 = 48 格（官方 heatmap 风格）
          data: [
            [0, 0, 0.82], [1, 0, 0.75], [2, 0, 0.68], [3, 0, 0.61], [4, 0, 0.55], [5, 0, 0.48], [6, 0, 0.42], [7, 0, 0.35],
            [0, 1, 0.78], [1, 1, 0.71], [2, 1, 0.64], [3, 1, 0.57], [4, 1, 0.51], [5, 1, 0.44], [6, 1, 0.38], [7, 1, 0.31],
            [0, 2, 0.74], [1, 2, 0.67], [2, 2, 0.60], [3, 2, 0.53], [4, 2, 0.47], [5, 2, 0.40], [6, 2, 0.34], [7, 2, 0.27],
            [0, 3, 0.70], [1, 3, 0.63], [2, 3, 0.56], [3, 3, 0.49], [4, 3, 0.43], [5, 3, 0.36], [6, 3, 0.30], [7, 3, 0.23],
            [0, 4, 0.66], [1, 4, 0.59], [2, 4, 0.52], [3, 4, 0.45], [4, 4, 0.39], [5, 4, 0.32], [6, 4, 0.26], [7, 4, 0.19],
            [0, 5, 0.62], [1, 5, 0.55], [2, 5, 0.48], [3, 5, 0.41], [4, 5, 0.35], [5, 5, 0.28], [6, 5, 0.22], [7, 5, 0.15],
          ],
        }],
      };
    case "boxplot":
      return {
        categories: ["产品A", "产品B", "产品C", "产品D", "产品E"],
        series: [{
          name: "分布",
          data: [
            [12, 35, 42, 58, 85], [18, 40, 52, 68, 95], [10, 30, 45, 60, 88],
            [15, 38, 48, 65, 92], [8, 28, 38, 55, 78],
          ],
        }],
      };
    case "histogram":
      return {
        categories: ["0-10", "10-20", "20-30", "30-40", "40-50", "50-60", "60-70", "70-80"],
        series: [{ name: "频数", data: [5, 12, 18, 24, 20, 14, 7, 3] }],
      };
    case "histogram-4grid":
      // 复刻 ECharts 官网 scatter-histogram：原始双变量 [[x,y],...]（散点+双向分箱联动）
      return {
        xAxisName: "X 值",
        yAxisName: "Y 值",
        series: [{ name: "样本", data: [
          [8.3, 143], [8.6, 214], [8.8, 251], [10.5, 26], [10.7, 86], [10.8, 93],
          [11.0, 176], [11.0, 39], [11.1, 221], [11.2, 188], [11.3, 57], [11.4, 91],
          [11.4, 191], [11.7, 8], [12.0, 196], [12.9, 177], [12.9, 153], [13.3, 201],
          [13.7, 199], [13.8, 47], [14.0, 81], [14.2, 98], [14.5, 121], [16.0, 37],
          [16.3, 12], [17.3, 105], [17.5, 168], [17.9, 84], [18.0, 197], [18.0, 155],
          [20.6, 125],
        ] }],
      };
    case "tornado":
      return {
        categories: ["销售单价", "销量", "单位成本", "固定成本", "税率", "回款周期", "坏账率", "汇率"],
        series: [{ name: "影响", data: [32, 24, -18, -12, -9, 7, -5, 3] }],
      };
    case "gauge":
      return { series: [{ name: "达成率", data: [{ value: 82, name: "达成率" }], max: 100 }] };
    case "sankey":
      // sankey 的 build 读取顶层 nodes/links（非 series）
      return {
        nodes: [
          { name: "营业收入" }, { name: "主营成本" }, { name: "毛利" },
          { name: "销售费用" }, { name: "管理费用" }, { name: "研发费用" },
          { name: "期间费用" }, { name: "经营利润" }, { name: "营业外" }, { name: "净利润" },
        ],
        links: [
          { source: "营业收入", target: "主营成本", value: 62 },
          { source: "营业收入", target: "毛利", value: 38 },
          { source: "毛利", target: "销售费用", value: 12 },
          { source: "毛利", target: "管理费用", value: 8 },
          { source: "毛利", target: "研发费用", value: 6 },
          { source: "毛利", target: "经营利润", value: 12 },
          { source: "经营利润", target: "期间费用", value: 20 },
          { source: "经营利润", target: "净利润", value: 15 },
          { source: "净利润", target: "营业外", value: 3 },
        ],
      };
    case "graph":
      // graph 的 build 读取顶层 nodes/links（同 sankey，非 series）
      return {
        nodes: [
          { name: "总部", category: 0 }, { name: "华东", category: 1 }, { name: "华北", category: 1 },
          { name: "华南", category: 1 }, { name: "西南", category: 1 }, { name: "海外", category: 2 },
        ],
        categories: ["总部", "区域", "海外"],
        links: [
          { source: "总部", target: "华东" }, { source: "总部", target: "华北" },
          { source: "总部", target: "华南" }, { source: "总部", target: "西南" },
          { source: "华东", target: "海外" }, { source: "华南", target: "海外" },
        ],
      };
    case "parallel":
      // parallel 的 build 读取 data.dimensions（维度）+ series[0].data（每行一条线）
      return {
        dimensions: [
          { name: "收入", max: 10 }, { name: "成本", max: 10 }, { name: "费用", max: 10 },
          { name: "利润", max: 10 }, { name: "毛利率%", max: 10 },
        ],
        series: [{
          name: "多维",
          data: [
            [1, 2, 3, 4, 5], [2, 1, 4, 3, 6], [3, 3, 2, 5, 4], [4, 2, 5, 3, 7],
            [5, 4, 1, 6, 3], [6, 3, 4, 2, 8], [7, 5, 2, 4, 5], [8, 4, 3, 6, 6],
          ],
        }],
      };
    case "error-bar":
      return {
        categories: months,
        series: [{
          name: "区间",
          data: [
            [810, 820, 830], [920, 932, 945], [890, 901, 915], [920, 934, 950],
            [1280, 1290, 1310], [1320, 1330, 1345], [1305, 1320, 1338], [1265, 1280, 1298],
            [1435, 1450, 1470], [1500, 1520, 1542], [1660, 1680, 1702], [1798, 1820, 1845],
          ],
        }],
      };
    case "calendar":
      return {
        series: [{
          name: "热力",
          // 2025 年 1 月多点（官方日历热力风格）
          data: [
            ["2025-01-01", 3], ["2025-01-03", 7], ["2025-01-06", 5], ["2025-01-08", 9],
            ["2025-01-10", 4], ["2025-01-13", 8], ["2025-01-15", 6], ["2025-01-17", 2],
            ["2025-01-20", 7], ["2025-01-22", 9], ["2025-01-24", 5], ["2025-01-27", 3],
            ["2025-01-29", 6], ["2025-01-31", 8],
          ],
        }],
      };
    case "scatter3d": {
      // v6.12：≥1000 点体现趋势（正态相关簇：z = 2x + 3y + 噪声），散点魅力 + 相关性
      const pts: [number, number, number][] = [];
      // 确定性伪随机（避免每次刷新变化）：用固定 seed 的 LCG
      let s = 1234567;
      const rnd = () => { s = (s * 1103515245 + 12345) % 2147483648; return s / 2147483648; };
      const gauss = () => {
        // Box-Muller（近似正态）
        const u = Math.max(rnd(), 1e-9), v = rnd();
        return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v);
      };
      const n = 1200;
      for (let i = 0; i < n; i++) {
        const x = gauss(); const y = gauss();
        const z = x * 2 + y * 3 + gauss() * 0.5;
        pts.push([Number(x.toFixed(2)), Number(y.toFixed(2)), Number(z.toFixed(2))]);
      }
      return { xAxisName: "收入", yAxisName: "利润率", zAxisName: "周转率", series: [{ name: "样本", data: pts }] };
    }
    case "bar3d": {
      // v6.12：重构为「二维数据直方图」——输入为原始二维点集 [[x,y],...]，柱高=频数
      const pts: [number, number][] = [];
      let s = 987654321;
      const rnd = () => { s = (s * 1103515245 + 12345) % 2147483648; return s / 2147483648; };
      const gauss = () => {
        const u = Math.max(rnd(), 1e-9), v = rnd();
        return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v);
      };
      for (let i = 0; i < 400; i++) {
        const x = gauss() * 2 + 2; const y = gauss() * 2 + 2;
        pts.push([Number(x.toFixed(2)), Number(y.toFixed(2))]);
      }
      return { xAxisName: "X 轴", yAxisName: "Y 轴", zAxisName: "频数", series: [{ name: "二维分布", data: pts }] };
    }
    case "waterfall3d":
      // 复刻「财务指标对比.py」：x=年份、y=指标、z=数值；3年 × 5指标 = 15 个 [xIdx,yIdx,zVal]
      return {
        xCategories: ["2021年", "2022年", "2023年"],
        xAxisName: "时间（年）",
        yAxisName: "财务指标",
        zAxisName: "数值（%）",
        color_scheme: "blues",
        // Python 案例真实数据（y 从前到后：照明→IoT→周转率→加权ROE→总资产报酬率）
        yCategories: ["照明业务利润贡献率", "IoT业务利润贡献率", "总资产周转率", "加权净资产收益率", "总资产报酬率"],
        series: [{ name: "指标对比", data: [
          [0, 0, 74.44], [1, 0, 68.97], [2, 0, 67.83],
          [0, 1, 22.37], [1, 1, 27.30], [2, 1, 25.37],
          [0, 2, 33.25], [1, 2, 33.25], [2, 2, 28.50],
          [0, 3, 13.13], [1, 3, 15.91], [2, 3, 9.33],
          [0, 4, 6.19],  [1, 4, 8.71],  [2, 4, 5.35],
        ] }],
      };
    default:
      return { categories: months, series: [{ name: "值", data: [820, 932, 901, 934, 1290, 1330, 1320, 1280, 1450, 1520, 1680, 1820] }] };
  }
}

/** 由模板名取显示名（类型中文名，v6.8-2 用 resolveTemplate 完整解析） */
export function templateDisplayName(template: string): string {
  const resolved = resolveTemplate(template);
  if (!resolved) return template;
  return `${resolved.tpl.zh}${template.includes("-") && !resolved.tpl.name.includes("-")
    ? `-${template.split("-").slice(1).join("-")}` : ""}`;
}

/** 示例数据 → 表格行（面向用户：图表库展开时展示「示例数据表」）。
 * 覆盖 sampleDataFor 全部形态：radar / {name,value} 占比 / 流向(links) /
 * heatmap 名称映射 / 数值对(散点·3D·日历·平行) / 类别-数值系列 / 兜底 JSON。 */
export interface SampleTable {
  columns: string[];
  rows: (string | number)[][];
}

export function sampleDataToRows(template: string): SampleTable {
  const data = sampleDataFor(template) as Record<string, unknown>;
  const series = (Array.isArray(data.series) ? data.series : []) as Record<string, unknown>[];
  const fmt = (v: unknown): string | number => {
    if (v === null || v === undefined || v === "") return "";
    if (typeof v === "number") return Number.isFinite(v) ? v : "";
    return String(v);
  };

  // 1) radar：指标行 × 系列列
  if (Array.isArray(data.indicators) && (data.indicators as unknown[]).length) {
    const cols = ["指标", ...series.map((s) => String(s?.name ?? "值"))];
    const rows = (data.indicators as Record<string, unknown>[]).map((ind, i) => {
      const cell: (string | number)[] = [String(ind?.name ?? "")];
      for (const s of series) {
        const d0 = (s?.data as unknown[] | undefined)?.[0];
        const v = d0 && typeof d0 === "object" ? (d0 as Record<string, unknown>).value : undefined;
        cell.push(fmt(Array.isArray(v) ? v[i] : v));
      }
      return cell;
    });
    return { columns: cols, rows };
  }

  // 2) {name, value} 对象数组（pie/funnel/sunburst/treemap/gauge）
  const first = (series[0]?.data as unknown[] | undefined)?.[0];
  if (first && typeof first === "object" && first !== null && "name" in (first as Record<string, unknown>)) {
    const cols = ["项目", ...series.map((s) => String(s?.name ?? "值"))];
    const items = series[0]?.data as Record<string, unknown>[];
    const rows = items.map((d, i) => {
      const cell: (string | number)[] = [String(d?.name ?? "")];
      for (const s of series) {
        const sd = (s?.data as Record<string, unknown>[] | undefined)?.[i];
        cell.push(fmt(sd && typeof sd === "object" && "value" in sd ? sd.value : sd));
      }
      return cell;
    });
    return { columns: cols, rows };
  }

  // 2.5) heatmap / waterfall3d：xCategories/yCategories 名称映射
  if (Array.isArray(data.xCategories) && Array.isArray(data.yCategories)) {
    const xs = data.xCategories as string[];
    const ys = data.yCategories as string[];
    const isWf3d = resolveTemplate(template)?.tpl.name === "waterfall3d";
    const cols = isWf3d ? ["年度", "财务指标", "数值(%)"] : ["X", "Y", "数值"];
    const rows = ((series[0]?.data as unknown[] | undefined) ?? []).map((d) => {
      const arr = d as unknown[];
      return [xs[arr[0] as number] ?? arr[0], ys[arr[1] as number] ?? arr[1], fmt(arr[2])];
    });
    return { columns: cols, rows };
  }

  // 3) 流向表（sankey：顶层 nodes/links；graph：series[0].links）
  const links =
    (data.links as Record<string, unknown>[] | undefined) ||
    ((series[0] as Record<string, unknown> | undefined)?.links as Record<string, unknown>[] | undefined);
  if (Array.isArray(links)) {
    return {
      columns: ["来源", "去向", "数值"],
      rows: links.map((l) => [String(l?.source ?? ""), String(l?.target ?? ""), fmt(l?.value ?? "")]),
    };
  }

  // 4) 数值对数组（scatter/calendar/parallel/3D）
  const pairFirst = (series[0]?.data as unknown[] | undefined)?.[0];
  if (Array.isArray(pairFirst)) {
    const width = (pairFirst as unknown[]).length;
    // parallel：用 dimensions 名作列标签（若提供）
    const dims = (data.dimensions as { name?: string }[] | undefined);
    const cols =
      width === 2
        ? ["X", "Y"]
        : width === 3
          ? ["X", "Y", "Z"]
          : (dims && dims.length >= width
              ? dims.slice(0, width).map((d) => d.name || `维度${dims.indexOf(d) + 1}`)
              : Array.from({ length: width }, (_, i) => `维度${i + 1}`));
    const rows = ((series[0]?.data as unknown[] | undefined) ?? []).map((row) =>
      (row as unknown[]).map(fmt),
    );
    return { columns: cols, rows };
  }

  // 5) categories + 数值系列（bar/line/waterfall/boxplot/histogram/error-bar/tornado…）
  const cats = Array.isArray(data.categories) ? (data.categories as string[]) : [];
  if (cats.length) {
    const cols = ["类别", ...series.map((s) => String(s?.name ?? "值"))];
    const rows = cats.map((c, i) => {
      const cell: (string | number)[] = [c];
      for (const s of series) {
        const v = (s?.data as unknown[] | undefined)?.[i];
        cell.push(fmt(v && typeof v === "object" ? (v as Record<string, unknown>).value : v));
      }
      return cell;
    });
    return { columns: cols, rows };
  }

  // 6) 兜底：JSON 简介（极少发生）
  return { columns: ["数据"], rows: [[JSON.stringify(data)]] };
}

/** v6.9-1：需要走 Python(mplot3d) 生成 PNG 的 3D 模板。
 * echarts-gl 无法复刻「每行折线围成的填充平面」瀑布样式，改用 Python。 */
const PY3D_TEMPLATES = new Set(["waterfall3d", "bar3d", "scatter3d"]);

/** Python 3D 图预览组件：异步调 /api/apps/finmod/py-chart 生成 base64 PNG（静态图）。
 * v6.13：放弃 plotly 在线交互（拖拽/缩放），前端只显示 matplotlib 静态 <img>（图片样例），
 * 点开可放大/下载（PythonImageLightbox）；后端 Python 代码与提示词模板保留供对照。 */
function PythonChartPreview({
  template,
  data,
  title,
  height,
}: {
  template: string;
  data: Record<string, unknown>;
  title?: string;
  height: number;
}) {
  const [b64, setB64] = useState("");
  const [err, setErr] = useState("");

  useEffect(() => {
    let alive = true;
    setB64("");
    setErr("");
    finmodPyChart(template, data)
      .then((r) => {
        if (!alive) return;
        if (r.success && r.b64) setB64(r.b64);
        else if (!r.success) setErr(r.note || "生成失败");
      })
      .catch((e) => {
        if (alive) setErr((e as Error).message);
      });
    return () => {
      alive = false;
    };
  }, [template, data]);

  if (err) {
    return (
      <div className="flex h-24 items-center justify-center rounded-md bg-zinc-50 px-2 text-center text-[10.5px] text-zinc-400">
        Python 3D 预览失败：{err}
      </div>
    );
  }

  if (!b64) {
    return (
      <div
        className="flex items-center justify-center rounded-md bg-zinc-50 text-[10.5px] text-zinc-400"
        style={{ height }}
      >
        Python 3D 图生成中…
      </div>
    );
  }
  // 静态 PNG + 点击放大
  return (
    <div className="relative overflow-hidden rounded-md border border-zinc-100 bg-white">
      <PythonImageLightbox
        b64={b64}
        filename={`${title || template}.png`}
        alt={title || template}
        bodyClassName="flex items-center justify-center"
      >
        <img
          src={`data:image/png;base64,${b64}`}
          alt={title || template}
          className="w-full object-contain"
          style={{ height, maxHeight: height }}
          onError={() => setErr(`图片加载失败 ${title || ""}`)}
        />
      </PythonImageLightbox>
    </div>
  );
}

export default function ChartPreview({
  template,
  title,
  height = 28,
}: {
  template: string;
  title?: string;
  height?: number;
}) {
  const elRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<echarts.ECharts | null>(null);
  const [error, setError] = useState("");
  // v6.9-1：Python 3D 模板的示例数据用 useMemo 稳定引用，避免 useEffect 重复请求
  const pyData = useMemo(
    () => sampleDataFor(template) as Record<string, unknown>,
    [template],
  );

  // v6.9-1：3D 模板改用 Python(mplot3d) 生成 PNG——echarts-gl 无法复刻
  // 「每行折线围成的填充平面」瀑布样式。Python 图走独立异步组件渲染 <img>。
  const pyResolved = resolveTemplate(template);
  if (pyResolved && PY3D_TEMPLATES.has(pyResolved.tpl.name)) {
    return (
      <PythonChartPreview
        template={pyResolved.tpl.name}
        data={pyData}
        title={title}
        height={height}
      />
    );
  }

  const option = (() => {
    // v6.8-2：用 resolveTemplate 完整解析模板名——不能 split("-")[0]，
    // 否则 dual-axis→dual、error-bar→error、histogram-4grid→histogram 找不到类型
    const resolved = resolveTemplate(template);
    if (!resolved) return null;
    return buildChartOption(template, sampleDataFor(template) as never, title);
  })();

  useLayoutEffect(() => {
    if (!elRef.current || !option) return;
    let disposed = false;
    const tryInit = () => {
      if (disposed || !elRef.current || chartRef.current) return;
      const w = elRef.current.clientWidth;
      if (w < 20) return;
      try {
        const inst = echarts.init(elRef.current, null, { preserveDrawingBuffer: true } as never);
        chartRef.current = inst;
        inst.setOption(option as echarts.EChartsOption, true);
        inst.resize();
        setError("");
      } catch (e) {
        setError((e as Error).message);
      }
    };
    tryInit();
    const ro = new ResizeObserver(() => tryInit());
    ro.observe(elRef.current);
    return () => {
      disposed = true;
      ro.disconnect();
      chartRef.current?.dispose();
      chartRef.current = null;
    };
  }, [option]);

  if (!option) {
    return (
      <div className="flex h-24 items-center justify-center rounded-md bg-zinc-50 text-[10.5px] text-zinc-400">
        未知模板「{template}」
      </div>
    );
  }
  return (
    <div className="relative overflow-hidden rounded-md border border-zinc-100 bg-white">
      <div ref={elRef} style={{ height }} className="w-full" />
      {error && (
        <div className="px-2 pb-1 text-[9.5px] text-red-400">预览失败：{error}</div>
      )}
    </div>
  );
}
