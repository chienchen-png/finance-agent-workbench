from __future__ import annotations

import json
import urllib.error
import urllib.request

from flask import Blueprint

from routes._utils import error, payload, success
from storage.db import get_db
from storage.log_store import LogStore
from storage.model_store import ModelStore

models_bp = Blueprint("models_api", __name__, url_prefix="/api/models")


def _build_chat_url(api_url: str) -> str:
    """Normalize a base URL to the /chat/completions endpoint."""
    base = api_url.rstrip("/")
    if base.endswith("/chat/completions"):
        return base
    if "/v1" in base:
        return base + "/chat/completions"
    return base + "/v1/chat/completions"


def _log(db, event_type: str, summary: str, status: str = "success",
         detail: str | None = None) -> None:
    """Best-effort local_logs write (PRD §3.8 最简化本地日志)."""
    try:
        LogStore(db).write(event_type=event_type, event_summary=summary,
                           status=status, detail=detail)
    except Exception:
        pass


def _provider_payload(data: dict) -> tuple[dict | None, str | None]:
    name = str(data.get("name") or "").strip()
    api_url = str(data.get("api_url") or "").strip()
    if not name:
        return None, "供应商名称不能为空"
    if not api_url:
        return None, "API URL 不能为空"
    return {
        "name": name,
        "api_url": api_url,
        "api_key": str(data.get("api_key") or "").strip(),
        "api_key_url": str(data.get("api_key_url") or "").strip(),
        "description": str(data.get("description") or "").strip(),
        "status": str(data.get("status") or "available").strip() or "available",
        "icon": str(data.get("icon") or "").strip(),
    }, None


def _model_payload(data: dict) -> tuple[dict | None, str | None]:
    name = str(data.get("name") or "").strip()
    if not name:
        return None, "模型名称不能为空"
    try:
        context_window = int(data.get("context_window") or 0)
    except (TypeError, ValueError):
        return None, "上下文窗口必须是数字"
    return {
        "name": name,
        "type": str(data.get("type") or "chat").strip() or "chat",
        "capabilities": str(data.get("capabilities") or "").strip(),
        "context_window": max(context_window, 0),
        "is_default": bool(data.get("is_default")),
        "status": str(data.get("status") or "available").strip() or "available",
        "icon": str(data.get("icon") or "").strip(),
    }, None


@models_bp.post("/test")
def test_connection():
    """Test a model API connection (PRD §2.5/§3.6 测试连接).

    Sends one short chat completion to the given endpoint and returns
    the model info, so users can validate configuration before saving.
    """
    data = payload()
    api_url = str(data.get("api_url") or "").strip()
    api_key = str(data.get("api_key") or "").strip()
    model = str(data.get("model") or "").strip()
    if not api_url or not model:
        return error("API 地址和模型名称必填")

    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 8,
        "stream": False,
    }).encode("utf-8")
    req = urllib.request.Request(
        _build_chat_url(api_url), data=body, method="POST",
        headers={
            "Content-Type": "application/json",
            **({"Authorization": f"Bearer {api_key}"} if api_key else {}),
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = json.loads(resp.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as e:
        msg = e.read().decode("utf-8", errors="replace")[:200]
        _log(get_db(), "model.test_failed", f"测试连接失败: {api_url}",
             status="error", detail=f"HTTP {e.code}: {msg}")
        return error(f"连接失败 (HTTP {e.code}): {msg}")
    except Exception as e:  # noqa: BLE001
        _log(get_db(), "model.test_failed", f"测试连接失败: {api_url}",
             status="error", detail=str(e)[:200])
        return error(f"连接失败: {e}")

    model_name = raw.get("model") or model
    usage = raw.get("usage") or {}
    return success({
        "message": f"连接成功，模型响应: {model_name}",
        "model": model_name,
        "usage": usage,
    })


@models_bp.get("/providers")
def list_providers():
    store = ModelStore(get_db())
    store.ensure_presets()
    return success(store.list_providers())


@models_bp.post("/providers")
def create_provider():
    data, message = _provider_payload(payload())
    if message:
        return error(message)
    db = get_db()
    store = ModelStore(db)
    try:
        provider = store.create_provider(data or {})
    except Exception as exc:
        if "UNIQUE" in str(exc).upper():
            return error("供应商名称已存在")
        raise
    _log(db, "model_provider.create", f"添加供应商「{provider.get('name')}」")
    return success(provider, 201)


@models_bp.put("/providers/<provider_id>")
def update_provider(provider_id: str):
    data, message = _provider_payload(payload())
    if message:
        return error(message)
    provider = ModelStore(get_db()).update_provider(provider_id, data or {})
    if not provider:
        return error("供应商不存在", 404)
    return success(provider)


@models_bp.post("/providers/<provider_id>/models")
def create_model(provider_id: str):
    data, message = _model_payload(payload())
    if message:
        return error(message)
    model = ModelStore(get_db()).create_model(provider_id, data or {})
    if not model:
        return error("供应商不存在", 404)
    return success(model, 201)


@models_bp.put("/<model_id>")
def update_model(model_id: str):
    data, message = _model_payload(payload())
    if message:
        return error(message)
    model = ModelStore(get_db()).update_model(model_id, data or {})
    if not model:
        return error("模型不存在", 404)
    return success(model)


@models_bp.delete("/<model_id>")
def delete_model(model_id: str):
    db = get_db()
    deleted = ModelStore(db).delete_model(model_id)
    if not deleted:
        return error("模型不存在", 404)
    _log(db, "model.delete", f"删除模型 {model_id}")
    return success(None, 204)


@models_bp.delete("/providers/<provider_id>")
def delete_provider(provider_id: str):
    db = get_db()
    deleted = ModelStore(db).delete_provider(provider_id)
    if not deleted:
        return error("供应商不存在", 404)
    _log(db, "model_provider.delete", f"删除供应商 {provider_id}")
    return success(None, 204)
