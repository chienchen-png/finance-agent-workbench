# -*- coding: utf-8 -*-
"""tools/finmod_prep.py — 应用二数据预处理引擎（V3，2026-08-21）。

Stata/SPSS 式「分析就绪」：清洗 / 类型修正 / 多 sheet 合并 / 透视面板化。
纯 pandas 确定性执行（0 LLM），供 `POST /api/apps/finmod/prep-data` 调用。

四类操作（steps 数组，按序叠加，可回滚/重排）：
  clean:  清洗（占位符已由 load_dataframe 处理；此处去重行/过滤异常值/替换值）
          {"op":"clean","action":"dedup"|"filter"|"replace","col":...,"keep":...,"where":...}
  cast:   类型修正 {"op":"cast","col":"...","to":"numeric"|"date"|"category"|"text"}
  merge:  多 sheet 拼接 {"op":"merge","sheets":["汇总表","符雅峰"],"how":"concat"|"join",
           "on":["业务员"],"suffixes":["","_明细"]}
  pivot:  透视/面板化 {"op":"pivot","mode":"long"|"wide","id_vars":[...],"var_name":...,"value_name":...}

所有操作作用在「加载的 DataFrame 栈」上：merge 拉取多 sheet 拼接，其余单表变换。
返回：最终 DataFrame + 每步日志 + 变换后列信息 + 前 5 行预览。
"""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)


def load_sheet(store: Any, project_id: str, file_name: str, sheet_name: str) -> pd.DataFrame:
    """加载指定 sheet 为 DataFrame（复用 finmod_eval.load_dataframe 清洗语义）。"""
    from tools.finmod_eval import load_dataframe
    return load_dataframe(store, project_id, file_name, sheet_name)


def _apply_clean(df: pd.DataFrame, step: dict) -> tuple[pd.DataFrame, str]:
    action = str(step.get("action") or "dedup")
    col = str(step.get("col") or "")
    if action == "dedup":
        subset = step.get("subset") or None
        before = len(df)
        df = df.drop_duplicates(subset=subset if subset else None)
        return df, f"去重行：{before} → {len(df)} 行"
    if action == "filter":
        # where: {"col": ..., "op": "lt"|"lte"|"gt"|"gte"|"eq"|"ne"|"in"|"notnull", "value": ...}
        w = step.get("where") or {}
        wcol = str(w.get("col") or "")
        op = str(w.get("op") or "gt")
        val = w.get("value")
        if not wcol or wcol not in df.columns:
            return df, f"过滤跳过：列「{wcol}」不存在"
        s = df[wcol]
        ops = {
            "lt": s < val, "lte": s <= val, "gt": s > val, "gte": s >= val,
            "eq": s == val, "ne": s != val,
            "in": s.isin(val) if isinstance(val, (list, tuple)) else (s == val),
            "notnull": s.notna(),
            "isnull": s.isna(),
        }
        mask = ops.get(op)
        if mask is None:
            return df, f"过滤跳过：未知操作「{op}」"
        before = len(df)
        df = df[mask]
        return df, f"过滤 {wcol} {op}：{before} → {len(df)} 行"
    if action == "replace":
        # where 定位 + value 替换（如 异常值→NaN）
        w = step.get("where") or {}
        wcol = str(w.get("col") or "")
        op = str(w.get("op") or "eq")
        val = w.get("value")
        replace_with = step.get("with")
        if not wcol or wcol not in df.columns:
            return df, f"替换跳过：列「{wcol}」不存在"
        s = df[wcol]
        ops = {"lt": s < val, "lte": s <= val, "gt": s > val, "gte": s >= val,
               "eq": s == val, "ne": s != val}
        mask = ops.get(op)
        if mask is None:
            return df, f"替换跳过：未知操作「{op}」"
        n = int(mask.sum())
        df.loc[mask, wcol] = replace_with
        return df, f"替换 {wcol} 中 {n} 个值 → {replace_with}"
    return df, f"未知清洗动作「{action}」（跳过）"


def _apply_cast(df: pd.DataFrame, step: dict) -> tuple[pd.DataFrame, str]:
    col = str(step.get("col") or "")
    to = str(step.get("to") or "numeric")
    if not col or col not in df.columns:
        return df, f"类型修正跳过：列「{col}」不存在"
    try:
        if to == "numeric":
            df[col] = pd.to_numeric(df[col], errors="coerce")
            return df, f"「{col}」→ 数值"
        if to == "date":
            df[col] = pd.to_datetime(df[col], errors="coerce")
            return df, f"「{col}」→ 日期"
        if to == "text":
            df[col] = df[col].astype(str)
            return df, f"「{col}」→ 文本"
        if to == "category":
            df[col] = df[col].astype("category")
            return df, f"「{col}」→ 分类"
    except Exception as e:  # noqa: BLE001
        return df, f"类型修正失败：{e}"
    return df, f"未知目标类型「{to}」（跳过）"


def _apply_merge(store: Any, project_id: str, file_name: str,
                 df: pd.DataFrame, step: dict, sheet_cache: dict) -> tuple[pd.DataFrame, str]:
    """多 sheet 拼接：how=concat 纵向堆叠 / how=join 按 key 横向合并。"""
    sheets = [str(s) for s in (step.get("sheets") or []) if s]
    how = str(step.get("how") or "concat")
    on = step.get("on") or None
    if not sheets:
        return df, "合并跳过：未指定 sheets"
    frames: list[pd.DataFrame] = [df]
    for sh in sheets:
        key = f"{file_name}:{sh}"
        if key not in sheet_cache:
            try:
                sheet_cache[key] = load_sheet(store, project_id, file_name, sh)
            except Exception as e:  # noqa: BLE001
                return df, f"合并失败：加载 sheet「{sh}」失败（{e}）"
        frames.append(sheet_cache[key])
    try:
        if how == "concat":
            # 纵向堆叠（列对齐；缺失列补 NaN）
            merged = pd.concat(frames, ignore_index=True, sort=False)
            return merged, f"纵向合并 {len(frames)} 个 sheet → {len(merged)} 行"
        # join：按 key 横向合并（左连接，依次合并）
        merged = df.copy()
        for sh in sheets:
            right = sheet_cache.get(f"{file_name}:{sh}")
            if right is None:
                continue
            suffix = step.get("suffixes") or ["", "_" + str(sh)]
            if isinstance(on, list) and on:
                merged = merged.merge(right, on=on, how="left",
                                      suffixes=(suffix[0], suffix[1] if len(suffix) > 1 else ""))
            else:
                merged = merged.merge(right, how="left", suffixes=(suffix[0], suffix[1] if len(suffix) > 1 else ""))
        return merged, f"按 {on or '索引'} 横向合并 {len(sheets) + 1} 个表 → {len(merged)} 行 × {len(merged.columns)} 列"
    except Exception as e:  # noqa: BLE001
        return df, f"合并失败：{e}"


def _apply_pivot(df: pd.DataFrame, step: dict) -> tuple[pd.DataFrame, str]:
    mode = str(step.get("mode") or "long")
    try:
        if mode == "long":
            # 宽→长（melt）：多个值列堆叠为「变量/值」两列
            id_vars = [str(c) for c in (step.get("id_vars") or []) if c in df.columns]
            var_name = str(step.get("var_name") or "变量")
            value_name = str(step.get("value_name") or "值")
            value_vars = [c for c in df.columns if c not in id_vars]
            if not value_vars:
                return df, "透视跳过：无可堆叠的值列"
            out = df.melt(id_vars=id_vars, value_vars=value_vars,
                          var_name=var_name, value_name=value_name)
            return out, f"宽转长：{len(df)} 行 → {len(out)} 行（{len(value_vars)} 个值列堆叠）"
        # wide：长→宽（pivot）
        index = str(step.get("index") or "")
        columns = str(step.get("columns") or "")
        values = str(step.get("values") or "")
        if not columns or not values:
            return df, "透视跳过：需指定 columns/values"
        idx = [index] if index and index in df.columns else None
        out = df.pivot(index=idx, columns=columns, values=values).reset_index()
        # 展平多级列名
        out.columns = [str(c) if not isinstance(c, tuple) else "_".join(str(x) for x in c if x != "")
                       for c in out.columns]
        return out, f"长转宽：按「{columns}」展开「{values}」→ {out.shape[0]} 行 × {out.shape[1]} 列"
    except Exception as e:  # noqa: BLE001
        return df, f"透视失败：{e}"


def run_prep_steps(store: Any, project_id: str, file_name: str, sheet_name: str,
                   steps: list[dict], base_df: pd.DataFrame | None = None) -> dict:
    """执行数据预处理步骤链（确定性 pandas）。

    Args:
        store: ProjectDataStore（读主库/TmpRun）
        project_id/file_name/sheet_name: 源数据定位
        steps: [{op, ...}] 按序执行
        base_df: R1 可选，多文件已合并的初始 DataFrame；提供时跳过从文件加载
                 （单文件场景可由调用方用 load_sheet 预合并多表）

    Returns:
        {success, columns, rows, preview, logs, errors}
          columns: [{name, type}]（变换后）
          preview: 前 5 行记录
          logs: 每步执行日志（成功/跳过说明）
          errors: 失败步骤（不阻塞后续；每步独立 try）
    """
    errors: list[dict] = []
    logs: list[str] = []
    sheet_cache: dict[str, pd.DataFrame] = {}
    if base_df is not None:
        df = base_df.copy()
    else:
        try:
            df = load_sheet(store, project_id, file_name, sheet_name)
        except Exception as e:  # noqa: BLE001
            return {"success": False, "columns": [], "rows": 0, "preview": [],
                    "logs": [f"加载失败：{e}"], "errors": [{"step": 0, "message": str(e)}]}

    for i, step in enumerate(steps):
        op = str(step.get("op") or "")
        before_rows = len(df)
        before_cols = len(df.columns)
        try:
            if op == "clean":
                df, log = _apply_clean(df, step)
            elif op == "cast":
                df, log = _apply_cast(df, step)
            elif op == "merge":
                df, log = _apply_merge(store, project_id, file_name, df, step, sheet_cache)
            elif op == "pivot":
                df, log = _apply_pivot(df, step)
            else:
                log = f"未知操作「{op}」（跳过）"
            logs.append(f"步骤 {i + 1} [{op}]：{log}")
            if len(df) == 0 and before_rows > 0:
                errors.append({"step": i + 1, "op": op, "message": "变换后为空表（请检查条件）"})
        except Exception as e:  # noqa: BLE001
            logger.warning("prep 步骤 %d 失败: %s", i + 1, e)
            errors.append({"step": i + 1, "op": op, "message": str(e)})
            logs.append(f"步骤 {i + 1} [{op}]：失败（{e}）")

    # 输出：列信息 + 预览
    cols_out: list[dict] = []
    for c in df.columns:
        s = df[c]
        if pd.api.types.is_numeric_dtype(s) and s.notna().sum() > 0:
            t = "numeric"
        elif pd.api.types.is_datetime64_any_dtype(s):
            t = "date"
        elif s.dtype.name in ("category", "object", "str", "string"):
            # 唯一值少 → 分类，否则文本
            nunique = s.nunique() if s.notna().sum() > 0 else 0
            t = "category" if (s.notna().sum() > 0 and nunique <= max(10, len(s) * 0.5)) else "text"
        else:
            t = "text"
        cols_out.append({"name": str(c), "type": t})
    preview = df.head(5).where(pd.notnull(df), None).to_dict("records")
    return {
        "success": True,
        "df": df,  # 内存 DataFrame（run 直接使用；prep-data 端点响应序列化时忽略）
        "columns": cols_out,
        "rows": int(len(df)),
        "preview": preview,
        "logs": logs,
        "errors": errors,
    }
