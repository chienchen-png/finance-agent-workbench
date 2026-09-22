from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from flask import Blueprint, request, send_file

from routes._utils import error, payload, success
from storage.db import get_db
from storage.project_store import ProjectStore

files_bp = Blueprint("files_api", __name__, url_prefix="/api/files")

# D4：Pandoc 探测——PATH 优先，其次离线介质 offline_packages/pandoc/pandoc.exe
_BASE_DIR = Path(__file__).resolve().parent.parent
_PANDOC_CANDIDATES = (
    Path(_BASE_DIR) / "offline_packages" / "pandoc" / "pandoc.exe",
    Path(_BASE_DIR) / "offline_packages" / "pandoc" / "pandoc-3.10.2" / "pandoc.exe",
)


def _find_pandoc() -> str | None:
    found = shutil.which("pandoc")
    if found:
        return found
    for cand in _PANDOC_CANDIDATES:
        if cand.is_file():
            return str(cand)
    return None

TEXT_EXTENSIONS = {
    ".txt",
    ".csv",
    ".log",
    ".md",
    ".markdown",
    ".py",
    ".sql",
    ".json",
    ".yml",
    ".yaml",
    ".xml",
    ".html",
    ".css",
    ".js",
    ".ts",
    ".bat",
    ".ps1",
    ".ini",
}


def _svg_to_png(content: str, resource_root: str) -> str:
    """把 Markdown 内容里的 SVG 图片路径转换为 PNG（Word 不原生支持 SVG，Pandoc
    需 rsvg-convert/inkscape 才能转 SVG；离线环境缺失时图片会消失）。

    方案：用 cairosvg 把 .svg 转换成同目录的 .png，并把 markdown 引用改写为 .png。
    Pandoc 转 docx 时引用 .png 即可正常嵌入图片。

    Args:
        content: 原始 markdown 内容。
        resource_root: 项目 work_dir（用于解析相对图片路径）。
    Returns:
        改写后的 markdown（所有可转换的 .svg 引用改为 .png）。
    """
    try:
        import cairosvg
    except ImportError:
        return content  # 未安装 cairosvg，保持原样（Pandoc 可能仍能处理，或图片缺失）
    import re

    root = Path(resource_root).resolve() if resource_root else None

    def _conv(match: re.Match) -> str:
        alt = match.group(1)
        img_path = match.group(2).strip()
        lowered = img_path.lower()
        if not lowered.endswith(".svg"):
            return match.group(0)
        png_path = img_path[:-4] + ".png"
        # 解析源 SVG 绝对路径（相对 resource_root 或本就绝对）
        svg_rel = img_path.lstrip("/").replace("\\", "/")
        svg_abs = None
        if Path(img_path).is_absolute():
            svg_abs = Path(img_path)
        elif root:
            svg_abs = root / svg_rel
        if svg_abs is None or not svg_abs.is_file():
            return match.group(0)
        try:
            png_abs = svg_abs.with_suffix(".png")
            if not png_abs.is_file():
                cairosvg.svg2png(url=str(svg_abs), write_to=str(png_abs), scale=2)
            return f"![{alt}]({png_path})"
        except Exception:  # noqa: BLE001 转换失败保留原引用
            return match.group(0)

    return re.sub(r"!\[([^\]]*)\]\(([^) ]+)\)", _conv, content)
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".svg"}


def _viewer_type(target: Path) -> str:
    suffix = target.suffix.lower()
    if suffix in {".md", ".markdown"}:
        return "markdown"
    if suffix in {".py", ".sql", ".json", ".js", ".ts", ".css", ".html", ".xml", ".yml", ".yaml", ".bat", ".ps1"}:
        return "code"
    if suffix in TEXT_EXTENSIONS:
        return "text"
    if suffix == ".docx":
        return "docx"
    if suffix in {".xls", ".xlsx"}:
        return "xlsx"
    if suffix == ".ppt":
        return "ppt"
    if suffix == ".pptx":
        return "pptx"
    if suffix == ".pdf":
        return "pdf"
    if suffix in IMAGE_EXTENSIONS:
        return "image"
    return "unsupported"


def _is_text_readable(target: Path) -> bool:
    return _viewer_type(target) in {"text", "markdown", "code"}


def _meta_payload(root: Path, target: Path) -> dict:
    entry = _entry(root, target)
    viewer_type = _viewer_type(target)
    return {
        **entry,
        "viewer_type": viewer_type,
        "can_edit": viewer_type in {"text", "markdown", "code"},
        # D1（2026-08-24）：xls 归一化到 xlsx viewer_type；白名单补 xls（防御）。
        # pdf 保留 external 能力（右键场景），双击走浏览器预览由前端分发。
        "can_open_external": viewer_type in {"docx", "xlsx", "xls", "ppt", "pptx", "pdf"},
    }


def _project_root(project_id: str) -> tuple[dict | None, Path | None, tuple | None]:
    if not project_id:
        return None, None, error("项目ID不能为空")
    project = ProjectStore(get_db()).get_by_id(project_id)
    if not project:
        return None, None, error("项目不存在", 404)
    root = Path(project["work_dir"]).expanduser().resolve()
    # 2026-08-20：集成应用专属项目（work_dir 指向应用固定目录）可能尚未创建——
    # 目录不存在时自动创建（仅影响新目录，现有项目 work_dir 均已存在不受影响）
    if not root.exists():
        try:
            root.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            return project, root, error(f"工作目录创建失败：{exc}", 500)
    if not root.is_dir():
        return project, root, error("项目工作目录不是文件夹", 400)
    return project, root, None


def _resolve_inside(root: Path, relative_path: str | None = None) -> Path:
    target = root if not relative_path else root / relative_path
    resolved = target.resolve()
    if resolved != root and root not in resolved.parents:
        raise ValueError("路径超出项目工作目录")
    return resolved


def _relative(root: Path, target: Path) -> str:
    return target.relative_to(root).as_posix()


def _entry(root: Path, target: Path) -> dict:
    stat = target.stat()
    return {
        "name": target.name,
        "path": _relative(root, target),
        "type": "directory" if target.is_dir() else "file",
        "size": stat.st_size if target.is_file() else None,
        "updated_at": stat.st_mtime,
    }


def _tree_entry(root: Path, target: Path) -> dict:
    entry = _entry(root, target)
    if not target.is_dir():
        return entry
    children = []
    for child in target.iterdir():
        if child.name.startswith("."):
            continue
        children.append(_tree_entry(root, child))
    children.sort(key=lambda item: (item["type"] != "directory", item["name"].lower()))
    entry["children"] = children
    return entry


def _safe_upload_name(filename: str) -> str:
    return Path(filename.replace("\\", "/")).name.strip()


def _safe_upload_relative_path(filename: str) -> str:
    parts = []
    for part in filename.replace("\\", "/").split("/"):
        cleaned = part.strip()
        if not cleaned or cleaned in {".", ".."}:
            continue
        parts.append(cleaned)
    return "/".join(parts)


@files_bp.get("/tree")
def list_tree():
    project_id = request.args.get("project_id", "").strip()
    relative_path = request.args.get("path", "").strip()
    recursive = request.args.get("recursive") == "1"
    _project, root, failure = _project_root(project_id)
    if failure:
        return failure
    try:
        current = _resolve_inside(root, relative_path)
    except ValueError as exc:
        return error(str(exc), 400)
    if not current.exists():
        return error("目录不存在", 404)
    if not current.is_dir():
        return error("目标不是目录", 400)
    entries = []
    try:
        for child in current.iterdir():
            if child.name.startswith("."):
                continue
            entries.append(_tree_entry(root, child) if recursive else _entry(root, child))
    except OSError as exc:
        return error(f"读取目录失败：{exc}", 500)
    entries.sort(key=lambda item: (item["type"] != "directory", item["name"].lower()))
    return success({"path": _relative(root, current) if current != root else "", "entries": entries})


@files_bp.get("/read")
def read_file():
    project_id = request.args.get("project_id", "").strip()
    relative_path = request.args.get("path", "").strip()
    _project, root, failure = _project_root(project_id)
    if failure:
        return failure
    try:
        target = _resolve_inside(root, relative_path)
    except ValueError as exc:
        return error(str(exc), 400)
    if not target.exists():
        return error("文件不存在", 404)
    if not target.is_file():
        return error("目标不是文件", 400)
    try:
        content = target.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return error("当前文件不是 UTF-8 文本文件", 415)
    except OSError as exc:
        return error(f"读取文件失败：{exc}", 500)
    return success({"file": _meta_payload(root, target), "content": content})


@files_bp.get("/meta")
def file_meta():
    project_id = request.args.get("project_id", "").strip()
    relative_path = request.args.get("path", "").strip()
    _project, root, failure = _project_root(project_id)
    if failure:
        return failure
    try:
        target = _resolve_inside(root, relative_path)
    except ValueError as exc:
        return error(str(exc), 400)
    if not target.exists():
        return error("文件不存在", 404)
    if not target.is_file():
        return error("目标不是文件", 400)
    return success({"file": _meta_payload(root, target)})


@files_bp.get("/raw")
def read_raw_file():
    project_id = request.args.get("project_id", "").strip()
    relative_path = request.args.get("path", "").strip()
    encoding = (request.args.get("encoding", "utf-8") or "utf-8").strip()
    _project, root, failure = _project_root(project_id)
    if failure:
        return failure
    try:
        target = _resolve_inside(root, relative_path)
    except ValueError as exc:
        return error(str(exc), 400)
    if not target.exists():
        return error("文件不存在", 404)
    if not target.is_file():
        return error("目标不是文件", 400)
    if request.args.get("binary") == "1" and _viewer_type(target) in {"image", "pdf", "docx", "xlsx", "ppt", "pptx"}:
        try:
            return send_file(target)
        except OSError as exc:
            return error(f"读取文件失败：{exc}", 500)
    if not _is_text_readable(target):
        return error("当前文件类型不支持文本读取", 415)
    try:
        content = target.read_text(encoding=encoding)
    except UnicodeDecodeError:
        return error(f"文件无法按 {encoding} 解码", 415)
    except OSError as exc:
        return error(f"读取文件失败：{exc}", 500)
    return success({"file": _meta_payload(root, target), "encoding": encoding, "content": content})


@files_bp.post("/create")
def create_item():
    data = payload()
    project_id = str(data.get("project_id", "")).strip()
    relative_path = str(data.get("path", "")).strip()
    item_type = str(data.get("type", "file")).strip()
    if item_type not in {"file", "directory"}:
        return error("类型必须是 file 或 directory")
    if not relative_path:
        return error("路径不能为空")
    _project, root, failure = _project_root(project_id)
    if failure:
        return failure
    try:
        target = _resolve_inside(root, relative_path)
    except ValueError as exc:
        return error(str(exc), 400)
    if target.exists():
        return error("目标已存在", 409)
    try:
        if item_type == "directory":
            target.mkdir(parents=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(str(data.get("content", "")), encoding="utf-8")
    except OSError as exc:
        return error(f"创建失败：{exc}", 500)
    return success(_entry(root, target), 201)


@files_bp.put("/write")
def write_file():
    data = payload()
    project_id = str(data.get("project_id", "")).strip()
    relative_path = str(data.get("path", "")).strip()
    _project, root, failure = _project_root(project_id)
    if failure:
        return failure
    try:
        target = _resolve_inside(root, relative_path)
    except ValueError as exc:
        return error(str(exc), 400)
    if target.exists() and not target.is_file():
        return error("目标不是文件", 400)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(str(data.get("content", "")), encoding="utf-8")
    except OSError as exc:
        return error(f"写入文件失败：{exc}", 500)
    return success(_entry(root, target))


@files_bp.put("/rename")
def rename_item():
    data = payload()
    project_id = str(data.get("project_id", "")).strip()
    source_path = str(data.get("path", "")).strip()
    target_path = str(data.get("new_path", "")).strip()
    if not source_path or not target_path:
        return error("原路径和新路径不能为空")
    _project, root, failure = _project_root(project_id)
    if failure:
        return failure
    try:
        source = _resolve_inside(root, source_path)
        destination = _resolve_inside(root, target_path)
    except ValueError as exc:
        return error(str(exc), 400)
    if source == root:
        return error("不能重命名项目根目录", 400)
    if not source.exists():
        return error("目标不存在", 404)
    if destination.exists():
        return error("新路径已存在", 409)
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        source.rename(destination)
    except OSError as exc:
        return error(f"重命名失败：{exc}", 500)
    return success(_entry(root, destination))


@files_bp.post("/copy")
def copy_item():
    data = payload()
    project_id = str(data.get("project_id", "")).strip()
    source_path = str(data.get("path", "")).strip()
    target_path = str(data.get("target_path", "")).strip()
    if not source_path or not target_path:
        return error("源路径和目标路径不能为空")
    _project, root, failure = _project_root(project_id)
    if failure:
        return failure
    try:
        source = _resolve_inside(root, source_path)
        destination = _resolve_inside(root, target_path)
    except ValueError as exc:
        return error(str(exc), 400)
    if not source.exists():
        return error("源路径不存在", 404)
    if destination.exists():
        return error("目标路径已存在", 409)
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            shutil.copytree(source, destination)
        else:
            shutil.copy2(source, destination)
    except OSError as exc:
        return error(f"复制失败：{exc}", 500)
    return success(_entry(root, destination), 201)


@files_bp.post("/upload")
def upload_file():
    project_id = request.form.get("project_id", "").strip()
    directory_path = request.form.get("path", "").strip()
    relative_upload_path = _safe_upload_relative_path(request.form.get("relative_path", "").strip())
    uploaded = request.files.get("file")
    if not uploaded or not uploaded.filename:
        return error("请选择要上传的文件")
    filename = relative_upload_path or _safe_upload_name(uploaded.filename)
    if not filename:
        return error("文件名无效")
    _project, root, failure = _project_root(project_id)
    if failure:
        return failure
    try:
        directory = _resolve_inside(root, directory_path)
        destination_path = f"{directory_path}/{filename}" if directory_path else filename
        destination = _resolve_inside(root, destination_path)
    except ValueError as exc:
        return error(str(exc), 400)
    if not directory.exists() or not directory.is_dir():
        return error("上传目录不存在", 404)
    if destination.exists():
        return error("同名文件已存在", 409)
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        uploaded.save(destination)
    except OSError as exc:
        return error(f"上传失败：{exc}", 500)
    return success(_entry(root, destination), 201)


@files_bp.delete("")
def delete_item():
    data = payload()
    project_id = str(data.get("project_id", "")).strip()
    relative_path = str(data.get("path", "")).strip()
    _project, root, failure = _project_root(project_id)
    if failure:
        return failure
    try:
        target = _resolve_inside(root, relative_path)
    except ValueError as exc:
        return error(str(exc), 400)
    if not target.exists():
        return error("目标不存在", 404)
    if target == root:
        return error("不能删除项目根目录", 400)
    try:
        if target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink()
    except OSError as exc:
        return error(f"删除失败：{exc}", 500)
    return success({"path": relative_path})


@files_bp.post("/open-external")
def open_external():
    data = payload()
    project_id = str(data.get("project_id", "")).strip()
    relative_path = str(data.get("path", "")).strip()
    _project, root, failure = _project_root(project_id)
    if failure:
        return failure
    try:
        target = _resolve_inside(root, relative_path)
    except ValueError as exc:
        return error(str(exc), 400)
    if not target.exists() or not target.is_file():
        return error("目标文件不存在", 404)

    viewer_type = _viewer_type(target)
    if viewer_type not in {"docx", "xlsx", "xls", "ppt", "pptx", "pdf"}:
        return error("当前文件类型不支持外部打开", 400)

    try:
        os.startfile(str(target))
    except OSError as exc:
        return error(f"外部打开失败：{exc}", 500)

    return success({
        "file": _meta_payload(root, target),
        "opened": True,
        "message": "已调用本机程序打开文件",
    })


@files_bp.post("/export-docx")
def export_docx():
    """D4：Markdown → Word (docx)。

    入参 {project_id, path, content?}：
      - content 传入时优先（未保存的编辑内容直接导出）；否则读 path 对应文件。
    转换：pandoc -f markdown+tex_math_dollars -t docx。
    Pandoc 缺失 → 501 明确错误（设计文档：不降级，保证质量一致）。
    """
    data = payload()
    project_id = str(data.get("project_id", "")).strip()
    relative_path = str(data.get("path", "")).strip()
    content = data.get("content")
    if not project_id or not relative_path:
        return error("project_id 与 path 不能为空")

    _project, root, failure = _project_root(project_id)
    if failure:
        return failure
    try:
        target = _resolve_inside(root, relative_path)
    except ValueError as exc:
        return error(str(exc), 400)
    if target.exists() and target.is_file() and _viewer_type(target) not in {"markdown", "text"}:
        return error("仅支持 Markdown/文本文件导出 Word", 415)

    if content is None:
        if not target.exists():
            return error("文件不存在", 404)
        if not target.is_file():
            return error("目标不是文件", 400)
        try:
            content = target.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return error("当前文件不是 UTF-8 文本文件", 415)
        except OSError as exc:
            return error(f"读取文件失败：{exc}", 500)

    pandoc = _find_pandoc()
    if not pandoc:
        return error(
            "Pandoc 未安装：请从离线介质 offline_packages/pandoc/ 安装 "
            "pandoc.exe（或加入系统 PATH）后重试",
            501,
        )

    stem = Path(relative_path).stem or "document"
    # D8：报告内图片为相对项目根路径（如 财务分析报告/财务分析报告N/x.svg）。
    #  1) SVG→PNG 预处理：Word 不支持 SVG，Pandoc 需 rsvg-convert（离线缺失）。
    #     用 cairosvg 把 .svg 转同目录 .png，改写 markdown 引用为 .png。
    #  2) 设置 --resource-path=<work_dir>，让 Pandoc 能按相对路径定位图片。
    content = _svg_to_png(content, str(root)) if root else content
    # 论文/报告排版模板：Pandoc --reference-doc（离线 offline_packages/pandoc/）
    _ref_doc = _BASE_DIR / "offline_packages" / "pandoc" / "reference-template.docx"
    try:
        fd, out_path = tempfile.mkstemp(suffix=".docx")
        os.close(fd)
        cmd = [pandoc, "-f", "markdown+tex_math_dollars", "-t", "docx", "-o", out_path, "-"]
        if _ref_doc.is_file():
            cmd.insert(1, f"--reference-doc={_ref_doc}")
        if root:
            cmd.insert(1, f"--resource-path={root}")
        proc = subprocess.run(
            cmd,
            input=content.encode("utf-8"),
            capture_output=True,
            timeout=60,
        )
    except subprocess.TimeoutExpired:
        return error("Word 导出超时（60s）", 500)
    except OSError as exc:
        return error(f"Pandoc 执行失败：{exc}", 500)

    if proc.returncode != 0:
        err_msg = proc.stderr.decode("utf-8", errors="replace")[:300]
        return error(f"Word 导出失败：{err_msg}", 500)

    try:
        return send_file(
            out_path,
            as_attachment=True,
            download_name=f"{stem}.docx",
            mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
    except OSError as exc:
        return error(f"导出文件读取失败：{exc}", 500)
    finally:
        try:
            os.remove(out_path)
        except OSError:
            pass