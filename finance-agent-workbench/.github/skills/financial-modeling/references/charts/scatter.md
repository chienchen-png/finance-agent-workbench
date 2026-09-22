# 图表模板：scatter（散点图 + 回归线）

## 用途

> **复杂度档位：L2 中等**（P6-①：多维变量 + 色彩/大小编码，财务最常用）

展示两个变量之间的关系，验证相关性/回归（G2/G3）。

## 典型场景
- 促销费 ↔ 收入 散点 + 回归线
- 销量 ↔ 成本 关系
- 相关性可视化（配合 correlation_matrix）

## 数据结构
```json
{
  "xAxisName": "促销费用(万元)",
  "yAxisName": "收入(万元)",
  "series": [
    { "name": "观测点", "data": [[10, 120], [15, 140], [12, 130], "..."] },
    { "name": "回归线", "type": "line", "data": [[10, 121], [15, 138], "..."] }
  ]
}
```
- 观测点：[[x, y], ...] 数组
- 回归线：拟合线两端点（或等间距点）作为 line 叠加

## 选型建议
- 两连续变量关系 → scatter
- 相关矩阵整体 → heatmap
- 单变量分布 → histogram/boxplot

## 变体清单（P5-②，template 传 `类型-变体` 名）

| 变体 | 图表 | 选型 |
|------|------|------|
| `scatter` | 基础散点（默认） | 变量关系（series 含 line 类型自动画回归线） |
| `scatter-effect` | 涟漪散点 | 重点点放大涟漪（Top-3 或 data.effectIndices） |
| `scatter-regression` | 回归散点 | 散点 + 红色趋势线（series[1] 为回归线）|

> 借鉴官方示例：scatter-simple / scatter-effect / scatter-linear-regression（v6.9.2 删除重复的 scatter-simple 变体，仅 3 变体）。

## 注意事项
- 散点密度高时开 dataZoom
- 回归线用 option_overrides 传 `series[].lineStyle` 虚线
- 报告中注明"相关 ≠ 因果"
