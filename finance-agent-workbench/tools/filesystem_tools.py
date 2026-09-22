"""Filesystem Tools — read/write/list/search/delete files in project workspace.

Phase 8: Real filesystem operations with workspace boundary enforcement,
encoding detection, hash recording for overwrite tracking, and
structured error reporting.

Design references:
  - PRD §4.1 (Tool list)
  - PRD §3.5.1 (Permission matrix: read=auto, write=confirm, delete=per-item)
  - PRD §3.5.2 (Sandbox + overwrite tracking)
"""

from __future__ import annotations

import hashlib
import os
import shutil
import time
from pathlib import Path
from typing import Any

from tools.file_lock import ensure_file_writable


# ------------------------------------------------------------------
# Read operations (🟢 auto-allowed)
# ------------------------------------------------------------------

def read_file(
    path: str,
    work_dir: str = "",
    encoding: str = "utf-8",
    start_line: int = 0,
    end_line: int = 0,
    allow_outside: bool = False,
) -> dict[str, Any]:
    """Read a file from the project workspace.

    Phase 8 TODO:
      - Resolve path within work_dir boundary
      - Detect encoding (UTF-8 → GBK → auto-detect)
      - Support line-range slicing for large files
      - Return structured content with metadata

    Args:
        path: Relative path within work_dir.
        work_dir: Project root directory (for boundary enforcement).
        encoding: Expected file encoding. Auto-detected if empty.
        start_line: 0-based start line (inclusive). 0 = from beginning.
        end_line: 0-based end line (exclusive). 0 = to end.

    Returns:
        {success, content, path, encoding, line_count, truncated, size_bytes}
    """
    try:
        if not work_dir:
            return {"success": False, "error": "未指定工作目录"}
        full_path = _resolve_path(path, work_dir, allow_outside=allow_outside)

        if not os.path.isfile(full_path):
            return {"success": False, "error": f"文件不存在: {path}"}

        size_bytes = os.path.getsize(full_path)

        # Encoding fallback chain
        encodings = [encoding] if encoding else ["utf-8", "gbk", "gb2312", "latin-1"]
        last_error = None
        for enc in encodings:
            try:
                with open(full_path, "r", encoding=enc) as f:
                    # Phase 17 P1: 大文件仅当未指定行范围时截断；指定了
                    # start_line/end_line 则全读后切片，支持大文件分块读入。
                    if size_bytes > MAX_TEXT_READ_SIZE and start_line <= 0 and end_line <= 0:
                        content = f.read(MAX_TEXT_READ_SIZE)
                        lines = content.split("\n")
                        return {
                            "success": True, "content": content, "path": path,
                            "encoding": enc, "line_count": len(lines),
                            "truncated": True, "size_bytes": size_bytes,
                            "total_lines": len(lines),
                            "chunk_hint": (
                                "文件过大（>10MB），已截断读取前 10MB。"
                                "如需继续请用 start_line/end_line 分块读取。"
                            ),
                        }
                    lines_raw = f.readlines()
                break
            except (UnicodeDecodeError, LookupError) as e:
                last_error = str(e)
                lines_raw = None
        else:
            return {"success": False, "error": f"编码错误: {last_error}", "path": path}

        total_lines = len(lines_raw)
        if start_line > 0 or end_line > 0:
            sl = max(0, start_line - 1) if start_line > 0 else 0
            el = end_line if end_line > 0 else total_lines
            lines = lines_raw[sl:el]
        else:
            lines = lines_raw

        content = "".join(lines)

        # Phase 17 P1: 续读提示 —— 让 LLM 知道文件多大、从哪续读（Copilot 式分块）
        read_from = (max(0, start_line - 1) if start_line > 0 else 0) + 1
        read_to = read_from + len(lines) - 1
        chunk_hint = ""
        if total_lines > 400 and start_line <= 0 and end_line <= 0:
            chunk_hint = (
                f"文件共 {total_lines} 行，建议按 300-400 行/块分块读取"
                "（用 start_line/end_line 指定行范围）。"
            )
        elif start_line > 0 or end_line > 0:
            chunk_hint = (
                f"已读取 {read_from}-{read_to}/{total_lines} 行；"
                f"如需继续请用 start_line={read_to + 1}。"
            )

        return {
            "success": True, "content": content, "path": path,
            "encoding": encoding or "utf-8", "line_count": len(lines),
            "truncated": False, "size_bytes": size_bytes,
            "total_lines": total_lines,
            "chunk_hint": chunk_hint,
        }
    except ValueError as e:
        return {"success": False, "error": str(e), "path": path}
    except Exception as e:
        return {"success": False, "error": f"读取失败: {e}", "path": path}


def list_directory(
    path: str = ".",
    work_dir: str = "",
    recursive: bool = False,
    allow_outside: bool = False,
) -> dict[str, Any]:
    """List contents of a directory within the project workspace.

    Phase 8 TODO:
      - Resolve path within work_dir boundary
      - Return list of FileInfo entries sorted (dirs first, then files)
      - Support recursive listing up to a depth limit
      - Handle permission errors gracefully

    Args:
        path: Relative path within work_dir. Default "." = project root.
        work_dir: Project root directory.
        recursive: If True, recursively list subdirectories.

    Returns:
        {success, entries: [{name, path, size, is_dir, modified_at}, ...], path}
    """
    try:
        if not work_dir:
            return {"success": False, "error": "未指定工作目录"}
        full_path = _resolve_path(path, work_dir, allow_outside=allow_outside)

        if not os.path.isdir(full_path):
            return {"success": False, "error": f"目录不存在: {path}"}

        entries: list[dict] = []

        if recursive:
            for root, dirs, files in os.walk(full_path):
                rel_root = os.path.relpath(root, full_path)
                rel_root = "" if rel_root == "." else rel_root
                for name in dirs:
                    p = os.path.join(root, name)
                    st = os.stat(p)
                    entries.append({
                        "name": name,
                        "path": (os.path.join(rel_root, name).replace("\\", "/")) if rel_root else name,
                        "size": 0, "is_dir": True,
                        "modified_at": _format_time(st.st_mtime),
                    })
                for name in files:
                    p = os.path.join(root, name)
                    st = os.stat(p)
                    entries.append({
                        "name": name,
                        "path": (os.path.join(rel_root, name).replace("\\", "/")) if rel_root else name,
                        "size": st.st_size, "is_dir": False,
                        "modified_at": _format_time(st.st_mtime),
                    })
        else:
            for entry in os.scandir(full_path):
                st = entry.stat()
                entries.append({
                    "name": entry.name, "path": entry.name,
                    "size": st.st_size if entry.is_file() else 0,
                    "is_dir": entry.is_dir(),
                    "modified_at": _format_time(st.st_mtime),
                })

        entries.sort(key=lambda x: (not x["is_dir"], x["name"].lower()))

        return {"success": True, "entries": entries, "path": path, "count": len(entries)}
    except ValueError as e:
        return {"success": False, "error": str(e), "path": path}
    except Exception as e:
        return {"success": False, "error": f"列目录失败: {e}", "path": path}


def search_files(
    pattern: str,
    path: str = ".",
    work_dir: str = "",
    search_content: str = "",
    case_sensitive: bool = False,
    allow_outside: bool = False,
) -> dict[str, Any]:
    """Search for files by name pattern and/or content.

    Phase 8 TODO:
      - Glob-based filename matching within work_dir
      - Content search with regex and literal modes
      - Limit results to prevent excessive output

    Args:
        pattern: File name glob pattern (e.g. "*.xlsx", "**/*.csv").
        path: Search root directory within work_dir.
        work_dir: Project root directory.
        search_content: Optional text/regex to search within file contents.
        case_sensitive: Whether content search is case-sensitive.

    Returns:
        {success, files: [{path, name, size, matches: [line, ...]}, ...], pattern}
    """
    try:
        if not work_dir:
            return {"success": False, "error": "未指定工作目录"}
        full_path = _resolve_path(path, work_dir, allow_outside=allow_outside)

        import fnmatch
        results: list[dict] = []
        max_results = 50
        content_lower = search_content.lower() if search_content and not case_sensitive else search_content

        for root, dirs, files in os.walk(full_path):
            for name in files:
                if fnmatch.fnmatch(name, pattern) or fnmatch.fnmatch(name.lower(), pattern.lower()):
                    fp = os.path.join(root, name)
                    rel = os.path.relpath(fp, full_path).replace("\\", "/")
                    st = os.stat(fp)
                    entry = {"name": name, "path": rel, "size": st.st_size, "matches": []}

                    if search_content and st.st_size < MAX_TEXT_READ_SIZE:
                        try:
                            with open(fp, "r", encoding="utf-8", errors="replace") as f:
                                for i, line in enumerate(f, 1):
                                    text = line if case_sensitive else line.lower()
                                    if content_lower in text:
                                        entry["matches"].append({"line": i, "content": line.strip()[:200]})
                                        if len(entry["matches"]) >= 20:
                                            break
                        except Exception:
                            pass
                        if search_content and not entry["matches"]:
                            continue

                    results.append(entry)
                    if len(results) >= max_results:
                        break
            if len(results) >= max_results:
                break

        return {"success": True, "files": results, "pattern": pattern, "count": len(results)}
    except ValueError as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        return {"success": False, "error": f"搜索失败: {e}"}


# ------------------------------------------------------------------
# Write/modify operations (🟡 requires user confirmation)
# ------------------------------------------------------------------

def write_file(
    path: str,
    content: str,
    work_dir: str = "",
    encoding: str = "utf-8",
    allow_outside: bool = False,
) -> dict[str, Any]:
    """Write content to a file.

    Phase 8 TODO:
      - Resolve path within work_dir boundary
      - Write with specified encoding
      - Verify written content hash matches

    Args:
        path: Relative path within work_dir.
        content: Text content to write.
        work_dir: Project root directory.
        encoding: Target file encoding.

    Returns:
        {success, path, bytes_written, original_hash, new_hash}
    """
    try:
        if not work_dir:
            return {"success": False, "error": "未指定工作目录"}
        full_path = _resolve_path(path, work_dir, allow_outside=allow_outside)

        # Phase 17 P9：文件锁前置检测（被 Excel/Word 占用时给出中文提示）
        if os.path.isfile(full_path):
            lock_err = ensure_file_writable(full_path)
            if lock_err:
                lock_err["path"] = path
                return lock_err

        original_hash = ""

        os.makedirs(os.path.dirname(full_path), exist_ok=True)

        if os.path.isfile(full_path):
            original_hash = _file_hash(full_path)

        with open(full_path, "w", encoding=encoding) as f:
            f.write(content)

        new_hash = _file_hash(full_path)
        bytes_written = os.path.getsize(full_path)

        return {
            "success": True, "path": path, "bytes_written": bytes_written,
            "original_hash": original_hash, "new_hash": new_hash,
        }
    except ValueError as e:
        return {"success": False, "error": str(e), "path": path}
    except Exception as e:
        return {"success": False, "error": f"写入失败: {e}", "path": path}


def create_directory(
    path: str,
    work_dir: str = "",
    exist_ok: bool = True,
    allow_outside: bool = False,
) -> dict[str, Any]:
    """Create a new directory within the project workspace.

    Args:
        path: Relative path within work_dir.
        work_dir: Project root directory.
        exist_ok: If True, don't error if directory already exists.

    Returns:
        {success, path, created, note}
    """
    try:
        if not work_dir:
            return {"success": False, "error": "未指定工作目录"}
        full_path = _resolve_path(path, work_dir, allow_outside=allow_outside)

        if os.path.isdir(full_path):
            return {"success": True, "path": path, "created": False, "note": "目录已存在"}

        os.makedirs(full_path, exist_ok=exist_ok)
        return {"success": True, "path": path, "created": True, "note": "目录创建成功"}
    except ValueError as e:
        return {"success": False, "error": str(e), "path": path}
    except Exception as e:
        return {"success": False, "error": f"创建目录失败: {e}", "path": path}


def delete_path(
    path: str,
    work_dir: str = "",
    allow_outside: bool = False,
) -> dict[str, Any]:
    """Delete a file or directory. **Requires per-item user confirmation.**

    Phase 8 TODO:
      - Resolve path within work_dir boundary
      - For files: record hash before deletion for audit trail
      - For directories: calculate total size and file count
      - Return impact report before actual deletion
      - Support moving to recycle bin instead of permanent delete

    Args:
        path: Relative path within work_dir.
        work_dir: Project root directory.

    Returns:
        {success, path, deleted_type, size_freed, hash_before_delete, note}
    """
    try:
        if not work_dir:
            return {"success": False, "error": "未指定工作目录"}
        full_path = _resolve_path(path, work_dir, allow_outside=allow_outside)

        if not os.path.exists(full_path):
            return {"success": False, "error": f"路径不存在: {path}"}

        deleted_type = "file" if os.path.isfile(full_path) else "directory"
        hash_before = _file_hash(full_path) if deleted_type == "file" else ""

        size_freed = os.path.getsize(full_path)
        if deleted_type == "directory":
            for root, dirs, files in os.walk(full_path):
                for f in files:
                    try:
                        size_freed += os.path.getsize(os.path.join(root, f))
                    except OSError:
                        pass

        if deleted_type == "file":
            os.unlink(full_path)
        else:
            shutil.rmtree(full_path)

        return {
            "success": True, "path": path, "deleted_type": deleted_type,
            "size_freed": size_freed, "hash_before_delete": hash_before, "note": "已删除",
        }
    except ValueError as e:
        return {"success": False, "error": str(e), "path": path}
    except Exception as e:
        return {"success": False, "error": f"删除失败: {e}", "path": path}


def move_path(
    source: str,
    destination: str,
    work_dir: str = "",
    allow_outside: bool = False,
) -> dict[str, Any]:
    """Move or rename a file/directory within the project workspace.

    Args:
        source: Source path within work_dir.
        destination: Destination path within work_dir.
        work_dir: Project root directory.

    Returns:
        {success, source, destination, moved_type, size_bytes, note}
    """
    try:
        if not work_dir:
            return {"success": False, "error": "未指定工作目录"}
        src_full = _resolve_path(source, work_dir, allow_outside=allow_outside)
        dst_full = _resolve_path(destination, work_dir, allow_outside=allow_outside)

        if not os.path.exists(src_full):
            return {"success": False, "error": f"源路径不存在: {source}"}

        os.makedirs(os.path.dirname(dst_full), exist_ok=True)
        moved_type = "file" if os.path.isfile(src_full) else "directory"
        size_bytes = os.path.getsize(src_full)
        shutil.move(src_full, dst_full)

        return {
            "success": True, "source": source, "destination": destination,
            "moved_type": moved_type, "size_bytes": size_bytes, "note": "移动成功",
        }
    except ValueError as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        return {"success": False, "error": f"移动失败: {e}"}


def copy_path(
    source: str,
    destination: str,
    work_dir: str = "",
    allow_outside: bool = False,
) -> dict[str, Any]:
    """Copy a file or directory within the project workspace.

    Args:
        source: Source path within work_dir.
        destination: Destination path within work_dir.
        work_dir: Project root directory.

    Returns:
        {success, source, destination, copied_type, size_bytes, note}
    """
    try:
        if not work_dir:
            return {"success": False, "error": "未指定工作目录"}
        src_full = _resolve_path(source, work_dir, allow_outside=allow_outside)
        dst_full = _resolve_path(destination, work_dir, allow_outside=allow_outside)

        if not os.path.exists(src_full):
            return {"success": False, "error": f"源路径不存在: {source}"}

        os.makedirs(os.path.dirname(dst_full), exist_ok=True)
        copied_type = "file" if os.path.isfile(src_full) else "directory"

        if os.path.isfile(src_full):
            shutil.copy2(src_full, dst_full)
            size_bytes = os.path.getsize(src_full)
        else:
            shutil.copytree(src_full, dst_full)
            size_bytes = 0
            for root, dirs, files in os.walk(src_full):
                for f in files:
                    try:
                        size_bytes += os.path.getsize(os.path.join(root, f))
                    except OSError:
                        pass

        return {
            "success": True, "source": source, "destination": destination,
            "copied_type": copied_type, "size_bytes": size_bytes, "note": "复制成功",
        }
    except ValueError as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        return {"success": False, "error": f"复制失败: {e}"}


# Maximum file size for text reading (bytes)
MAX_TEXT_READ_SIZE = 10 * 1024 * 1024  # 10MB


def _resolve_path(path: str, work_dir: str, allow_outside: bool = False) -> str:
    """Resolve a path within work_dir, enforcing sandbox.

    allow_outside=True（全自动模式）：跳过边界检查，支持绝对路径。
    由引擎按工作模式注入：manual 保持沙箱，auto 解除。
    """
    if allow_outside:
        return os.path.abspath(path)
    work = Path(work_dir).resolve()
    full = (work / path).resolve()
    if not str(full).startswith(str(work) + os.sep) and str(full) != str(work):
        raise ValueError(f"路径超出工作目录范围: {path}")
    return str(full)


def _file_hash(filepath: str) -> str:
    """Compute SHA-256 hash of a file for audit trail."""
    try:
        h = hashlib.sha256()
        with open(filepath, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return ""


def _format_time(timestamp: float) -> str:
    """Format a timestamp as ISO string."""
    from datetime import datetime, timezone
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()
