"""文件锁检测工具 — 写操作前置保护（Phase 17 P9）。

背景
----
Windows 上 Excel / Word 打开文件时会**独占锁定**（并生成 `~$` 前缀的
隐藏锁文件），此时任何程序写入都会抛 `PermissionError`。当前系统的
write_file / write_excel / export_project_data 均无检测，报错是英文
`[Errno 13] Permission denied`，用户看不懂、智能体也无法理解。

本模块提供两层检测：
  1. Office 锁文件探测（`~$xxx.xlsx` / `~$xxx.docx`）——最可靠，Excel/
     Word 打开即生成；
  2. 独占打开测试（Windows 语义）——`open(path, "r+b")` 被锁定时抛
     PermissionError，对 txt/xlsx/docx 等全部类型通用。

工作流（方案 A：提示后终止，简单可靠）：
  写操作前调用 is_file_locked()；若锁定，返回结构化
  {"error_type": "file_locked", "error": "「xxx」正被 Excel 打开，请关闭后重试"}，
  智能体读到后立即告知用户关闭文件并结束本轮，不重试。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

# Office 锁文件前缀（Excel/Word/WPS 打开时在同目录生成 ~$ 开头隐藏文件）
_LOCK_PREFIX = "~$"
# 常见 Office 扩展名（这些文件打开即独占锁定）
_OFFICE_EXTS = {".xls", ".xlsx", ".xlsm", ".xltx", ".xltm", ".doc", ".docx",
                ".docm", ".dotx", ".dotm", ".ppt", ".pptx", ".pptm"}
# 排除：锁文件本身、常见系统/临时文件
_SKIP_NAMES = {"desktop.ini", "thumbs.db", ".gitignore"}


def is_file_locked(path: str) -> tuple[bool, str]:
    """检测文件是否被占用。

    Returns:
        (locked, reason)：locked=True 时 reason 为人类可读的占用原因。
    """
    try:
        p = Path(path)
    except (TypeError, ValueError):
        return True, "路径无效"
    if not p.exists() and not p.is_file():
        return False, ""  # 文件不存在无需检测

    basename = p.name
    if basename in _SKIP_NAMES:
        return False, ""

    # 层 1：Office 锁文件探测（Excel/Word 打开时必有 ~$ 文件）
    lock_file = p.parent / (f"{_LOCK_PREFIX}{basename.lstrip(_LOCK_PREFIX)}")
    # 兼容 WPS 锁文件：~$ 后跟完整文件名（WPS 有时用 ~$文件名）
    if lock_file.exists():
        return True, f"「{basename}」正被 Office 程序打开（检测到锁文件）"

    # 层 2：独占重命名测试（Windows 语义，最可靠）
    # open("r+b") 同进程二次打开不报错，但 os.rename 在文件被占用时
    # 抛 PermissionError [WinError 32]——Excel/Word 打开的文件必然被独占。
    try:
        # 先尝试以读写模式打开（轻量，能覆盖大多数写锁场景）
        try:
            with open(path, "r+b"):
                pass
        except PermissionError:
            return True, f"「{basename}」正被其他程序占用，请关闭后重试"
        except OSError:
            return True, f"「{basename}」无法访问，可能被占用或权限不足"
        # 再尝试 rename 到自己（占用检测金标准：被锁定时必然 WinError 32）
        tmp = str(p) + f"._lock_{os.getpid()}_{id(p)}"
        try:
            os.rename(str(p), tmp)
            os.rename(tmp, str(p))
        except OSError:
            # 清理可能残留的临时文件
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
            except OSError:
                pass
            return True, f"「{basename}」正被其他程序占用，请关闭后重试"
        return False, ""
    except Exception:
        return False, ""


def locked_error(path: str, reason: str = "") -> dict[str, Any]:
    """构造结构化 file_locked 错误（智能体可识别，用户可读）。"""
    basename = os.path.basename(path)
    return {
        "success": False,
        "error_type": "file_locked",
        "error": reason or f"「{basename}」正被其他程序打开，请关闭文件后重试",
        "path": path,
        "hint": "请让用户关闭正在打开该文件的 Excel/Word 等程序，然后再执行一次。",
    }


def ensure_file_writable(path: str) -> dict[str, Any] | None:
    """写操作前置检查：锁定则返回错误 dict，可用则返回 None。

    Usage:
        err = ensure_file_writable(full_path)
        if err:
            return err
    """
    locked, reason = is_file_locked(path)
    if locked:
        return locked_error(path, reason)
    return None
