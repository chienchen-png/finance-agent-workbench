# 图表模板：pie（饼图/环形图）

> **复杂度档位：L1 简单**（P6-①：单/双变量平面图，直观快速）

## 用途
展示整体中各部分占比。

## 典型场景
- 收入结构占比（D4）
- 成本费用构成
- 产品线收入占比（C4）

## 数据结构
```json
{
  "categories": ["产品A", "产品B", "产品C", "其他"],
  "series": [
    { "name": "收入占比", "data": [45, 30, 18, 7] }
  ]
}
```
- categories 为扇区名；data 为数值（自动算百分比）

## 选型建议
- 占比展示 → pie（环形更美观，radius 内圈可显示合计）
- 扇区 > 7 个 → 合并"其他"或改用 bar
- 想看趋势中的构成变化 → bar-stacked

## 变体清单（P5-②，template 传 `类型-变体` 名）

| 变体 | 图表 | 选型 |
|------|------|------|
| `pie` / `pie-donut` | 环形图（默认） | 占比 + 中空放合计 |
| `pie-simple` | 基础饼图 | 实心扇形 |
| `pie-half-donut` | 半环形 | KPI 达成率（上半环） |
| `pie-rounded` | 圆角环形 | 大圆角 + 扇区间隙 |
| `pie-nested` | 嵌套环形 | 内外两层（series 2 组）|

> 借鉴官方示例：pie-simple / pie-doughnut / pie-half-donut / pie-borderRadius / pie-nest。

## 注意事项
- 数据 ≤ 200 点；扇区名过长时标签截断
- 金额为 0 的扇区自动隐藏
