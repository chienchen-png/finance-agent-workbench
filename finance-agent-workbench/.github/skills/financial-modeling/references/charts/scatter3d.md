# 图表模板：scatter3d（三维散点图）

> **复杂度档位：L3 复杂**（P6-②；v6.9 起**由 Python(mplot3d) 生成 PNG**）
> **AI 无需介入绘图**：正常 `generate_chart("scatter3d", {...})` 提交数据，前端识别该模板后自动调
> `/api/apps/finmod/py-chart` 由 Python 渲染 PNG（不再走 echarts-gl/WebGL，无拖拽旋转/缩放交互）。

## 用途
展示三变量之间的关系（三维空间中的点）。气泡颜色深浅编码第 3 维。

## 典型场景
- 收入 × 利润率 × 周转率三维关系（G2/G3）
- 三个财务指标的聚类/离群观察
- 双变量敏感性 + 目标值（3D 视角）

## 数据结构
```json
{
  "xCategories": [],
  "yCategories": [],
  "axisNames": ["收入(百万)", "利润率(%)", "周转率(次)"],
  "color_scheme": "blacks",
  "series": [
    { "name": "样本", "data": [
      [50, 8.2, 1.2],
      [120, 15.5, 0.8],
      [80, 12.1, 2.1]
    ]}
  ]
}
```
- series[0].data：每行 `[x, y, z]` 三元组（Python `_norm_3d` 读取）
- axisNames / xAxisName·yAxisName·zAxisName：三轴名（可选）
- color_scheme：配色方案（auto/blues/greens/reds/oranges/purples/blacks）

## 选型建议
- 三变量关系 → scatter3d（三维直观）
- 只需两变量 → scatter（平面更简洁）
- 需要 3D 柱状结构 → bar3d

## 注意事项
- 数据 ≤ 200 点
- **由 Python(mplot3d) 渲染 PNG**：不支持矢量导出（仅 PNG）、不支持拖拽旋转/缩放交互
- **图内不含数据大标题**（容器标题栏已展示表名）；三轴名保留
- 数据格式与 echarts-gl 版一致，AI 侧无需感知底层渲染差异
