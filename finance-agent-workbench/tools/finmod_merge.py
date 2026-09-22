# -*- coding: utf-8 -*-
"""tools/finmod_merge.py — 应用二多文件合并引擎（R1，2026-08-23）。

需求：把「变量映射/执行只吃单一 file_name」升级为「多文件（多表）统一建模」。
用户可同时导入多张数据表（如「销售表.xlsx」+「成本表.xlsx」），引擎按变量
映射的语义，把各文件的所需列**自动合并**成一个统一 DataFrame，喂给模型。

合并策略（智能判定，纯 pandas 确定，0 LLM）：
  1. **共同键横向 join**：所有文件都含某「键列」（期间/id/类别，如 月份、客户、业务员）
     → 按键 outer join（保留全部记录，缺列 fillna），适合「销售表 × 成本表」不同列场景。
  2. **同构纵向 concat**：各文件列高度重叠（≥60% 列名相同）且无键列
     → 行堆叠（conact），适合「分支机构月度表」多表同构场景。
  3. **列并集横向拼**：既无键又不同构 → 直接横向 append（列并集，缺列 fillna）。

兼容性：本引擎**不改变单文件路径**（file_names 长度为 1 时直接返回该文件 df，
与旧 `load_dataframe` 行为一致），只在多文件时生效。
"""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)


def load_files_dataframe(store: Any, project_id: str, file_names: list[str],
                         sheet_name: str = "") -> pd.DataFrame:
    """加载单个文件为 DataFrame（复用 finmod_eval.load_dataframe 清洗语义）。"""
    from tools.finmod_eval import load_dataframe
    return load_dataframe(store, project_id, file_names[0], sheet_name)


def _detect_join_keys(frames: list[pd.DataFrame], file_names: list[str]) -> list[str]:
    """检测所有文件共有的键列（期间/类别/id 类，用于横向 join）。

    优先日期含期间关键词的列；否则取各文件都有的非数值类别列。
    """
    if not frames:
        return []
    common = set(frames[0].columns)
    for f in frames[1:]:
        common &= set(f.columns)
    if not common:
        return []
    common = list(common)
    # 优先期间/类别语义列（月份/日期/年度/季度/客户/业务员/编号 等）
    key_words = ("月", "日期", "日", "年", "季度", "期", "客户", "业务", "部门", "地区", "编号", "id", "名称", "类型")
    for c in common:
        if any(k in str(c) for k in key_words):
            # 排除纯数值列（数值列做键易错边）
            s = frames[0][c]
            if not pd.api.types.is_numeric_dtype(s):
                return [c]
    return []


def _columns_overlap_ratio(frames: list[pd.DataFrame]) -> float:
    """所有文件列名交集 / 最大列数——判断是否同构（≥0.6 视为同构）。"""
    if len(frames) < 2:
        return 1.0
    base = set(frames[0].columns)
    inter = set(frames[0].columns)
    max_cols = max(len(f.columns) for f in frames)
    for f in frames[1:]:
        inter &= set(f.columns)
    if max_cols == 0:
        return 0.0
    return len(inter) / max_cols


def merge_files_for_model(store: Any, project_id: str,
                          file_names: list[str],
                          sheet_name: str = "") -> dict:
    """把多个文件合并成一个统一 DataFrame（供模型取用）。

    Args:
        store: ProjectDataStore（读 TmpRun/主库）
        project_id: 项目 id
        file_names: 文件列表（≥1）
        sheet_name: 可选，多文件同 sheet 名（一般留空走各文件默认 sheet）

    Returns:
        {
          "df": pd.DataFrame,             # 合并后统一 DataFrame
          "strategy": "single"|"join"|"concat"|"union",
          "join_keys": [..],              # join 策略下的键列
          "file_of_col": {col: file_name},# 每列来源文件（同名冲突优先）
          "logs": [str],                  # 人类可读合并日志
        }
        任一文件加载失败 → str(exc) 记录在 logs，继续合并其余（不整体失败）。
    """
    if not file_names:
        raise ValueError("缺少 file_names")
    logs: list[str] = []

    # 加载每个文件（失败不阻塞整体）
    frames: list[pd.DataFrame] = []
    loaded_names: list[str] = []
    for fn in file_names:
        try:
            df = load_files_dataframe(store, project_id, [fn], sheet_name)
            frames.append(df)
            loaded_names.append(fn)
            logs.append(f"加载「{fn}」：{df.shape[0]} 行 × {df.shape[1]} 列")
        except Exception as e:  # noqa: BLE001
            logger.warning("merge 加载「%s」失败: %s", fn, e)
            logs.append(f"「{fn}」加载失败（{e}），已跳过")

    if not frames:
        raise ValueError("全部文件加载失败，无法合并")

    # 单文件：直接返回（与旧行为一致，不改变单文件路径）
    if len(frames) == 1:
        return {
            "df": frames[0],
            "strategy": "single",
            "join_keys": [],
            "file_of_col": {str(c): loaded_names[0] for c in frames[0].columns},
            "logs": logs,
        }

    # 多文件：策略判定
    join_keys = _detect_join_keys(frames, loaded_names)
    overlap = _columns_overlap_ratio(frames)

    # 策略 1：同构（列重叠≥0.6）→ 纵向 concat（行堆叠，保留每表完整记录）
    # 优先于 join：同构表通常是「多期/多分支」切片，行堆叠更合理。
    if overlap >= 0.6:
        try:
            merged = pd.concat(frames, ignore_index=True, sort=False)
            file_of_col = {}
            for fn, df in zip(loaded_names, frames):
                for c in df.columns:
                    file_of_col.setdefault(str(c), fn)
            logs.append(f"同构纵向拼接 {len(frames)} 文件（列重叠 {overlap:.0%}）→ "
                        f"{merged.shape[0]} 行 × {merged.shape[1]} 列")
            return {
                "df": merged, "strategy": "concat", "join_keys": [],
                "file_of_col": file_of_col, "logs": logs,
            }
        except Exception as e:  # noqa: BLE001
            logger.warning("merge concat 失败，回退 join: %s", e)
            logs.append(f"纵向拼接失败（{e}），尝试按键合并")

    # 策略 2：共同键 → 横向 join（不同列但有关联键，如 销售表×成本表 按月份）
    if join_keys:
        try:
            merged = frames[0]
            for i, right in enumerate(frames[1:], start=1):
                suffixes = ("", f"_{loaded_names[i]}")
                merged = merged.merge(right, on=join_keys, how="outer", suffixes=suffixes)
            file_of_col: dict[str, str] = {}
            for fn, df in zip(loaded_names, frames):
                for c in df.columns:
                    # 同名冲突时保留首个来源；join 已加后缀的列另计
                    key = str(c)
                    if key not in file_of_col or key in join_keys:
                        file_of_col[key] = fn
            logs.append(f"按键「{'、'.join(join_keys)}」横向合并 {len(frames)} 文件 → "
                        f"{merged.shape[0]} 行 × {merged.shape[1]} 列")
            return {
                "df": merged, "strategy": "join", "join_keys": join_keys,
                "file_of_col": file_of_col, "logs": logs,
            }
        except Exception as e:  # noqa: BLE001
            logger.warning("merge join 失败，尝试列并集: %s", e)
            logs.append(f"按键合并失败（{e}），回退列并集")

    # 策略 3：列并集横向拼（缺列 fillna）
    file_of_col = {}
    merged = frames[0].copy()
    for fn, df in zip(loaded_names, frames):
        for c in df.columns:
            file_of_col.setdefault(str(c), fn)
    for fn, df in zip(loaded_names[1:], frames[1:]):
        # 列对齐并集：右侧新增列补 NaN，左侧缺列补 NaN
        merged = pd.concat([merged, df], ignore_index=True, sort=True)
    logs.append(f"列并集拼接 {len(frames)} 文件 → {merged.shape[0]} 行 × {merged.shape[1]} 列")
    return {
        "df": merged, "strategy": "union", "join_keys": [],
        "file_of_col": file_of_col, "logs": logs,
    }


def collect_all_columns(store: Any, project_id: str,
                        file_names: list[str], sheet_name: str = "") -> dict:
    """多文件列名索引合并（供 varmap 预填/推荐），返回去重后的列信息。

    Returns:
        {
          "all_cols": [str],              # 所有文件列名并集（去重）
          "period_cols": [str],           # 期间列（任一文件命中）
          "cols_info": [{name, type, files}],  # 每列 + 来源文件列表 + 推断类型
        }
    """
    cols_info: dict[str, dict] = {}
    for fn in file_names:
        try:
            df = load_files_dataframe(store, project_id, [fn], sheet_name)
        except Exception as e:  # noqa: BLE001
            logger.warning("collect_all_columns 加载「%s」失败: %s", fn, e)
            continue
        for c in df.columns:
            name = str(c)
            s = df[c]
            t = _infer_type(s)
            if name not in cols_info:
                cols_info[name] = {"name": name, "type": t, "files": []}
            elif cols_info[name]["type"] != t:
                # 类型冲突 → 保留更宽的（numeric 优先）
                if t == "numeric":
                    cols_info[name]["type"] = "numeric"
            if fn not in cols_info[name]["files"]:
                cols_info[name]["files"].append(fn)
    all_cols = list(cols_info.keys())
    period_cols = [n for n, info in cols_info.items() if _looks_period(n, info["type"])]
    return {
        "all_cols": all_cols,
        "period_cols": period_cols,
        "cols_info": list(cols_info.values()),
    }


def _infer_type(s: pd.Series) -> str:
    """列类型推断（与 finmod_prep 一致口径）：numeric/date/category/text。"""
    try:
        if pd.api.types.is_datetime64_any_dtype(s):
            return "date"
        if pd.api.types.is_numeric_dtype(s) and s.notna().sum() > 0:
            return "numeric"
        if s.dtype.name in ("object", "str", "string", "category"):
            nunique = s.nunique() if s.notna().sum() > 0 else 0
            if s.notna().sum() > 0 and nunique <= max(10, int(len(s) * 0.5)):
                return "category"
            return "text"
        return "text"
    except Exception:  # noqa: BLE001
        return "text"


def _looks_period(name: str, typ: str) -> bool:
    """列名/类型是否像期间列（日期类型 or 列名含时间关键词）。"""
    if typ == "date":
        return True
    tm = ("月", "日期", "日期", "年度", "年份", "季度", "时间", "期间", "期", "年")
    return any(k in str(name) for k in tm) and not any(k in str(name) for k in ("名字", "名称"))
