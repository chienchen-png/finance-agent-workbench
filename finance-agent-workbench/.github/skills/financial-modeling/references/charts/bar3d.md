# 图表模板：bar3d（三维柱状图）

> **复杂度档位：L3 复杂**（P6-②；v6.9 起**由 Python(mplot3d) 生成 PNG**）
> **AI 无需介入绘图**：正常 `generate_chart("bar3d", {...})` 提交数据，前端识别该模板后自动调
> `/api/apps/finmod/py-chart` 由 Python 渲染 PNG（不再走 echarts-gl/WebGL，无拖拽旋转/缩放交互）。

## 用途
三维结构对比（柱高 = 值），柱色随高度深浅渐变（深→浅蓝）。由 Python 生成静态 PNG。

## 典型场景
- 部门 × 季度 × 金额三维对比（C4）
- 产品 × 区域 × 销量
- 3D 敏感性柱状（双变量 → 目标）

## 数据结构
```json
{
  "xCategories": ["销售部", "研发部", "生产部"],
  "yCategories": ["Q1", "Q2", "Q3", "Q4"],
  "xAxisName": "部门",
  "yAxisName": "季度",
  "zAxisName": "金额(万)",
  "color_scheme": "blues",
  "series": [
    { "name": "金额", "data": [
      [0, 0, 120], [0, 1, 135],
      [1, 0, 90],  [1, 1, 105]
    ]}
  ]
}
```
- xCategories/yCategories：两个维度类别（x/y 轴）
- series[0].data：每行 `[xIdx, yIdx, zVal]`（xIdx/yIdx 为类别下标，Python `_norm_3d` 读取）
- zAxisName：柱高（值）轴名
- color_scheme：配色（柱色随高度深浅）

## 选型建议
- 双类别 × 数值 → bar3d（立体感强）
- 只有单类别 × 数值 → bar（平面足够）
- 需要并排填充面 → waterfall3d

## 注意事项
- 类别 ≤ 10×10（过多柱子视觉混乱）
- **由 Python(mplot3d) 渲染 PNG**：不支持矢量导出（仅 PNG）、不支持拖拽旋转/缩放交互
- **图内不含数据大标题**（容器标题栏已展示表名）；三轴名保留
- 数据格式与 echarts-gl 版一致，AI 侧无需感知底层渲染差异
