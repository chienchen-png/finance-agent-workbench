"""公式兜底重算 — 导入时对"无缓存值的公式单元格"用 formulas 库重算（Phase 17 P11）。

背景
----
openpyxl 读 Excel 用 `data_only=True` 取公式的**缓存值**。但财务系统的 Excel
若由第三方导出、从未用 Excel 保存打开过，公式单元格**没有缓存值** →
data_only 读到 None → 导入数据平面变空值，核对/写回全错。

本模块：导入器检测到公式单元格（data_only 读为 None 但原始单元格是公式）时，
用 formulas 库重算整个工作簿，把结果回填，确保数据平面公式列有值。

用法（项目数据导入器内）：
    from tools.formula_fallback import formula_fallback_rows
    rows = formula_fallback_rows(full_path, rows, sheet_name)

性能：formulas 全簿重算约 1-3 秒（2031 行级文件），仅在检测到 None 公式时触发；
正常文件（Excel 保存过、缓存值齐全）零开销。
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# V2 防卡死（2026-08-21）：超过此行数×列数（单元格数）的 sheet 跳过 formulas
# 全簿重算。formulas 库全簿重算对公式密集的大工作簿极慢（实测 7965 单元格 ×
# 9 sheet 刷屏卡死、前端导入停在 0%），大 sheet 导入优先保障速度——公式列值
# 缺失可接受（数据平面仍可用，仅公式单元格为 None）。
FORMULA_RECALC_MAX_CELLS = 5_000

# 允许的重算结果类型（numpy 标量 → Python 原生）
import numpy as np  # noqa: E402


def _to_py(value: Any) -> Any:
    """numpy 标量 / 数组 → Python 原生（None 保留）。"""
    if value is None:
        return None
    if isinstance(value, np.ndarray):
        # 单元素数组取标量
        flat = value.reshape(-1)
        if flat.size == 1:
            return _to_py(flat[0])
        return [float(x) if isinstance(x, (np.floating, float)) else _to_py(x)
                for x in flat]
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def _sheet_has_none_formula(full_path: str, rows: list[list]) -> bool:
    """快速判断：data_only 行里是否有 None，且原单元格是公式。

    用 openpyxl 非 data_only 读原始公式串，若某列既有 None 又有 "=..." 串
    说明存在"无缓存值的公式" → 需要重算。
    """
    try:
        import openpyxl
        wb = openpyxl.load_workbook(full_path, read_only=True, data_only=False)
        ws = wb.active
        n_formula = 0
        for raw in ws.iter_rows(values_only=True):
            for v in raw:
                if isinstance(v, str) and v.startswith("="):
                    n_formula += 1
                    if n_formula >= 3:
                        wb.close()
                        return True
        wb.close()
    except Exception:  # noqa: BLE001
        pass
    return False


def formula_fallback_rows(full_path: str, sheet_rows: list[list],
                          sheet_name: str) -> list[list]:
    """对 sheet 行数据做公式兜底：返回可能被回填后的行。

    仅当该 sheet 存在公式且 data_only 值缺失时才触发 formulas 全簿重算。
    重算结果按单元格引用映射回填（结果与 sheet_name 匹配的行）。

    V2 防卡死（2026-08-21）：formulas 全簿重算对大文件（数千行 × 多 sheet）
    极慢（曾实测 7965 单元格 × 9 sheet 刷屏卡死，前端导入停在 0%）。
    新增**单元格数上限门**：超过 FORMULA_RECALC_MAX_CELLS 的 sheet 跳过重算
    （公式列值缺失，数据平面仍可用——仅公式单元格为 None）。

    V3 默认禁用（2026-08-21）：formulas 库对含跨 sheet 引用的工作簿（如
    `='[3]郭洋'!N19`）加载时刷屏大量 "openpyxl does not support" 错误且极慢，
    跨 sheet 检测不可靠（openpyxl 读到的公式串格式不统一）。**默认跳过重算**
    （数据平面公式列保持 None，核对/建模仍可用）；需要时设环境变量
    `FINMOD_FORMULA_RECALC=1` 显式启用（仅小文件）。
    """
    import os as _os
    if _os.environ.get("FINMOD_FORMULA_RECALC") != "1":
        return sheet_rows

    # 快速门：sheet 里根本没有 None 值 → 无需重算
    has_none = any(
        cell is None or cell == "" for row in sheet_rows for cell in row
    )
    if not has_none:
        return sheet_rows

    # V2 单元格数上限门：大 sheet 跳过全簿重算（防导入卡死）
    # 行数 × 列数（单元格数）超阈值 → formulas 全簿重算太慢，直接跳过
    n_rows = len(sheet_rows)
    n_cols = max((len(r) for r in sheet_rows), default=0)
    if n_rows * n_cols > FORMULA_RECALC_MAX_CELLS:
        logger.info("公式重算跳过（%s：%d 行 × %d 列 > 上限 %d）——公式列值保持缺失",
                    sheet_name, n_rows, n_cols, FORMULA_RECALC_MAX_CELLS)
        return sheet_rows

    # 快速门：工作簿是否有公式（非 data_only 探测，3 个公式即触发）
    try:
        import openpyxl
        wb = openpyxl.load_workbook(full_path, read_only=True, data_only=False)
        n_formula = 0
        has_cross_sheet = False
        for ws in wb.worksheets:
            for raw in ws.iter_rows(values_only=True):
                for v in raw:
                    if isinstance(v, str) and v.startswith("="):
                        n_formula += 1
                        # 跨 sheet 引用（含 '!' 或 '[' 文件名）→ formulas 全簿重算
                        # 依赖其他 sheet，极慢且常刷屏失败 → 直接跳过重算
                        if "!" in v or "[" in v:
                            has_cross_sheet = True
                            break
                        if n_formula >= 3:
                            break
                if n_formula >= 3 or has_cross_sheet:
                    break
            if n_formula >= 3 or has_cross_sheet:
                break
        wb.close()
        if n_formula < 3:
            return sheet_rows
        # V2 跨 sheet 引用 → 跳过（formulas 全簿重算跨 sheet 依赖极慢/刷屏）
        if has_cross_sheet:
            logger.info("公式重算跳过（%s：含跨 sheet 公式引用）——公式列值保持缺失", sheet_name)
            return sheet_rows
    except Exception:  # noqa: BLE001
        return sheet_rows

    # 触发 formulas 全簿重算
    try:
        import formulas
        model = formulas.ExcelModel().loads(full_path).finish()
        sol = model.calculate()
    except Exception as exc:  # noqa: BLE001
        logger.warning("公式重算失败(%s): %s", sheet_name, exc)
        return sheet_rows

    # 构建 {大写列字母+行号: 值} 映射（仅本 sheet）
    cell_map: dict[str, Any] = {}
    target = sheet_name.upper()
    for key, ranges in sol.items():
        if not isinstance(key, str):
            continue
        # key 形如 "'[file.xlsx]SHEET1'!C1" 或 "[file.xlsx]SHEET1'!C1"
        try:
            ref_part = key.split("!")[-1]
            sheet_part = key.split("!")[0].strip("'[]").strip()
        except Exception:  # noqa: BLE001
            continue
        # 规范化 sheet 名（去文件名前缀、引号、大小写）
        if "." in sheet_part and "]" in sheet_part:
            sheet_part = sheet_part.split("]")[-1]
        if sheet_part.upper() != target:
            continue
        try:
            values = ranges.value
        except Exception:  # noqa: BLE001
            continue
        if values is None:
            continue
        arr = values if isinstance(values, np.ndarray) else np.asarray(values)
        cell_map[ref_part.upper()] = _to_py(arr)

    if not cell_map:
        return sheet_rows

    # 回填：把 sheet_rows 中为 None/空 且命中公式映射的单元格替换
    # 列字母 → 索引（A→0, B→1…）
    def col_index(letter: str) -> int:
        idx = 0
        for ch in letter:
            idx = idx * 26 + (ord(ch.upper()) - 64)
        return idx - 1

    out = []
    changed = 0
    for r, row in enumerate(sheet_rows, start=1):
        new_row = list(row)
        for c, cell in enumerate(new_row):
            if cell is None or cell == "":
                letter = ""
                n = c + 1
                while n:
                    n, rem = divmod(n - 1, 26)
                    letter = chr(65 + rem) + letter
                key = f"{letter}{r}".upper()
                if key in cell_map:
                    new_row[c] = cell_map[key]
                    changed += 1
        out.append(new_row)
    if changed:
        logger.info("公式兜底回填 %d 个单元格（%s）", changed, sheet_name)
    return out
