"""路径越界检测 — 纯函数，与策略解耦。

判断工具参数中的路径类字段是否越出工作目录。被 router 在人工审批模式下
调用：沙箱工具越界 → 需要用户确认。
"""
from __future__ import annotations

import os

# 工具参数中的路径类字段（与旧 approval.py 对齐）
PATH_KEYS = ("path", "file_path", "target", "source", "destination",
             "file1", "file2", "input", "output")


def path_escapes_workspace(params: dict, work_dir: str) -> bool:
    """若任一路径参数越出 work_dir，返回 True。

    Args:
        params: 工具调用参数。
        work_dir: 项目工作目录（空则不做边界检查）。

    Returns:
        True = 存在越界路径；False = 全部在界内（或无路径参数）。
    """
    if not work_dir:
        return False
    abs_work = os.path.abspath(work_dir)
    for key in PATH_KEYS:
        p = params.get(key) or ""
        if not p:
            continue
        try:
            abs_path = os.path.abspath(os.path.join(abs_work, p))
            if not abs_path.startswith(abs_work + os.sep) and abs_path != abs_work:
                return True
        except (ValueError, OSError):
            return True
    return False
