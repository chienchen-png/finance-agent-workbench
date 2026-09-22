"""Shared helpers for API route blueprints."""

from __future__ import annotations

from flask import jsonify, request


def success(data=None, status_code: int = 200):
    resp = jsonify({"success": True, "data": data})
    # 阶段 7.9.2：禁用浏览器启发式缓存——API 全是动态数据（文件树/上下文/项目），
    # 无 Cache-Control 时浏览器会缓存 GET 响应，导致删除/复制后刷新仍显示旧数据。
    resp.headers["Cache-Control"] = "no-store"
    return resp, status_code


def error(message: str, status_code: int = 400, extra: dict | None = None):
    body = {"success": False, "message": message}
    if extra:
        body.update(extra)
    resp = jsonify(body)
    resp.headers["Cache-Control"] = "no-store"
    return resp, status_code


def payload() -> dict:
    return request.get_json(silent=True) or {}
