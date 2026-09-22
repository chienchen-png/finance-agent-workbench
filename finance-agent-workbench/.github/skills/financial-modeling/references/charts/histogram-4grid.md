# 图表模板：histogram-4grid（联动直方图）

> **复杂度档位：L3 复杂**（P6-②：多表联动）

## 用途
双变量分布联动：4 宫格展示**原始散点 + 按 x 分箱直方图 + 按 y 分箱直方图**，一眼看清单变量分布与双变量关系。

## 典型场景
- 双变量分布形态（G1 描述统计）
- 变量关系 + 各维分布（G2 相关性预检）
- 成本/收入分布联动观察

## 数据结构
```json
{
  "xAxisName": "单价(元)",
  "yAxisName": "销量(件)",
  "bins": { "x": 8, "y": 8 },
  "series": [
    { "name": "样本", "data": [
      [8.3, 143], [8.6, 214], [10.5, 26]
    ]}
  ]
}
```
- series[0].data：每行 `[x, y]` 原始双变量
- xAxisName/yAxisName：两轴名（可选）
- bins：分箱数（可选，默认 sturges 公式 ceil(log2(n))+1）

## 选型建议
- 双变量分布 + 单维分布联动 → histogram-4grid
- 只需相关关系 → scatter
- 只需单维分布 → histogram

## 注意事项
- 数据 ≤ 500 点
- 分箱数默认 sturges（可覆盖）
- **实现**：自研 sturges 分箱（echarts-stat npm 版有 bug，等价实现已验证）
