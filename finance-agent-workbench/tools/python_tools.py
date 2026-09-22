"""Python Tools — Python environment introspection and configuration.

Phase 8: Real Python runtime queries with subprocess isolation.
"""

from __future__ import annotations

import json
import subprocess
import sys
from typing import Any


def get_version() -> dict[str, Any]:
    """Get the Python interpreter version."""
    try:
        result = subprocess.run(
            [sys.executable, "--version"],
            capture_output=True, text=True, timeout=10,
        )
        full = (result.stdout or "").strip() or (result.stderr or "").strip()
        parts = sys.version_info
        return {
            "success": True, "version": f"{parts.major}.{parts.minor}.{parts.micro}",
            "major": parts.major, "minor": parts.minor, "micro": parts.micro,
            "full_version": full or f"Python {parts.major}.{parts.minor}.{parts.micro}",
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def get_executable() -> dict[str, Any]:
    """Get the path to the Python interpreter executable."""
    try:
        exe = sys.executable
        is_venv = sys.prefix != sys.base_prefix
        venv_path = sys.prefix if is_venv else ""
        return {
            "success": True, "executable": exe,
            "is_venv": is_venv, "venv_path": venv_path,
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def get_installed_packages() -> dict[str, Any]:
    """List installed Python packages."""
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "list", "--format=json"],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            return {"success": False, "error": result.stderr.strip()}
        packages = json.loads(result.stdout)
        return {
            "success": True,
            "packages": packages,
            "count": len(packages),
        }
    except json.JSONDecodeError:
        return {"success": False, "error": "无法解析pip输出"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def configure_environment(
    work_dir: str = "",
    python_path: str = "",
    install_packages: list[str] | None = None,
) -> dict[str, Any]:
    """Configure Python environment. Requires user confirmation."""
    changes = []
    try:
        exe = python_path or sys.executable

        if install_packages:
            for pkg in install_packages:
                result = subprocess.run(
                    [exe, "-m", "pip", "install", pkg],
                    capture_output=True, text=True, timeout=120,
                    cwd=work_dir or None,
                )
                if result.returncode == 0:
                    changes.append(f"已安装: {pkg}")
                else:
                    changes.append(f"安装失败: {pkg} — {result.stderr.strip()[:200]}")

        return {
            "success": True,
            "environment": {
                "version": get_version(),
                "executable": get_executable(),
                "packages": get_installed_packages(),
            },
            "changes_made": changes,
        }
    except Exception as e:
        return {"success": False, "error": str(e), "changes_made": changes}
