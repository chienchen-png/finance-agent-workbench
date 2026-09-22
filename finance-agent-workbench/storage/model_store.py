"""model_providers / models CRUD for Phase 6."""

from __future__ import annotations

import uuid
from sqlite3 import Connection

from storage._utils import iso_now, row_to_dict

PRESET_PROVIDERS = [
    {
        "id": "provider_tianjian_local",
        "name": "天箭惯性本地大模型",
        "api_url": "http://172.18.1.7:4000/v1",
        "api_key": "",
        "api_key_url": "",
        "description": "内网环境下可使用的本地 OpenAI 兼容模型服务。",
        "is_preset": 1,
        "models": [
            {"name": "glm", "type": "chat", "capabilities": "对话,工具", "context_window": 200000},
            {"name": "qwen", "type": "chat", "capabilities": "对话,工具,视觉", "context_window": 200000},
            {"name": "Qwen3-Embedding-8B", "type": "embedding", "capabilities": "知识库嵌入", "context_window": 8192},
            {"name": "Qwen3-Reranker-8B", "type": "reranker", "capabilities": "知识库排序", "context_window": 8192},
        ],
    },
    {
        "id": "provider_deepseek",
        "name": "Deepseek",
        "api_url": "https://api.deepseek.com",
        "api_key": "",
        "api_key_url": "https://platform.deepseek.com/usage",
        "description": "官方公网通道，测试用 OpenAI 兼容服务。",
        "is_preset": 1,
        "models": [
            {"name": "deepseek-v4-pro", "type": "chat", "capabilities": "对话,工具", "context_window": 1000000},
            {"name": "deepseek-v4-flash", "type": "chat", "capabilities": "对话,工具", "context_window": 1000000},
        ],
    },
    {
        "id": "provider_chat_api",
        "name": "Chat Api",
        "api_url": "https://api.zhangsan.cool",
        "api_key": "",
        "api_key_url": "https://api.zhangsan.cool/register?aff=m3b6",
        "description": "第三方中转站，支持多供应商 OpenAI 兼容模型。",
        "is_preset": 1,
        "models": [
            {"name": "gpt-5.5", "type": "chat", "capabilities": "对话,工具,视觉", "context_window": 0},
            {"name": "gpt-5.4", "type": "chat", "capabilities": "对话,工具,视觉", "context_window": 0},
            {"name": "claude-sonnet-4-6", "type": "chat", "capabilities": "对话,工具,视觉", "context_window": 0},
            {"name": "claude-sonnet-5", "type": "chat", "capabilities": "对话,工具,视觉", "context_window": 0},
            {"name": "gemini-3-pro-all", "type": "chat", "capabilities": "对话,工具,视觉", "context_window": 0},
            {"name": "glm-5.2", "type": "chat", "capabilities": "对话,工具", "context_window": 0},
        ],
    },
]


class ModelStore:
    def __init__(self, db: Connection) -> None:
        self.db = db

    # 阶段 7.9.2：模型名称 → 内置官方 logo 自动匹配（无 icon 时回退）
    _ICON_MAP: list[tuple[str, str]] = [
        ("deepseek", "deepseek.png"),
        ("glm", "glm.png"),
        ("qwen", "qwen.png"),
        ("claude", "claude.png"),
        ("gemini", "gemini.png"),
        ("gpt", "openai.png"),
        ("openai", "openai.png"),
    ]

    @staticmethod
    def resolve_model_icon(name: str) -> str:
        """按名称关键字匹配内置官方 logo，返回文件名；未匹配返回 generic.svg。"""
        lower = (name or "").lower()
        for key, file in ModelStore._ICON_MAP:
            if key in lower:
                return file
        return "generic.svg"

    def ensure_presets(self) -> None:
        now = iso_now()
        for provider in PRESET_PROVIDERS:
            # Skip if user has explicitly deleted this provider
            deleted = self.db.execute(
                "SELECT 1 FROM deleted_presets WHERE id = ?", (provider["id"],)
            ).fetchone()
            if deleted:
                continue
            # 供应商图标（内置按名称匹配）
            provider_icon = ModelStore.resolve_model_icon(provider["name"])
            self.db.execute(
                """INSERT OR IGNORE INTO model_providers
                   (id, name, api_url, api_key, api_key_url, description,
                    is_preset, status, created_at, updated_at, icon)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 'available', ?, ?, ?)""",
                (
                    provider["id"], provider["name"], provider["api_url"],
                    provider["api_key"], provider["api_key_url"], provider["description"],
                    provider["is_preset"], now, now, provider_icon,
                ),
            )
            for index, model in enumerate(provider["models"]):
                model_id = f"{provider['id']}_{model['name'].lower().replace('.', '_').replace('-', '_')}"
                # Skip if user has explicitly deleted this model
                deleted_model = self.db.execute(
                    "SELECT 1 FROM deleted_presets WHERE id = ?", (model_id,)
                ).fetchone()
                if deleted_model:
                    continue
                model_icon = ModelStore.resolve_model_icon(model["name"])
                self.db.execute(
                    """INSERT OR IGNORE INTO models
                       (id, provider_id, name, api_url, api_key, type, capabilities,
                        context_window, is_default, status, created_at, updated_at, icon)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'available', ?, ?, ?)""",
                    (
                        model_id, provider["id"], model["name"], provider["api_url"],
                        provider["api_key"], model["type"], model["capabilities"],
                        model["context_window"], 1 if provider["id"] == "provider_tianjian_local" and index == 0 else 0,
                        now, now, model_icon,
                    ),
                )
        # 阶段 7.9.2：存量数据 icon 回填（新增 icon 列后，按名称自动匹配）
        try:
            rows = self.db.execute(
                "SELECT id, name FROM models WHERE icon IS NULL OR icon = ''"
            ).fetchall()
            for row in rows:
                self.db.execute(
                    "UPDATE models SET icon = ? WHERE id = ?",
                    (ModelStore.resolve_model_icon(row["name"]), row["id"]),
                )
            prow = self.db.execute(
                "SELECT id, name FROM model_providers WHERE icon IS NULL OR icon = ''"
            ).fetchall()
            for row in prow:
                self.db.execute(
                    "UPDATE model_providers SET icon = ? WHERE id = ?",
                    (ModelStore.resolve_model_icon(row["name"]), row["id"]),
                )
        except Exception:
            pass
        self.db.commit()

    def list_providers(self) -> list[dict]:
        rows = self.db.execute(
            "SELECT * FROM model_providers ORDER BY is_preset DESC, name"
        ).fetchall()
        providers = [row_to_dict(row) for row in rows]
        for provider in providers:
            provider["models"] = self.list_models(provider["id"])

        # Custom sort: 天箭 → Deepseek → Chat Api → others alphabetically
        _order = {"天箭惯性本地大模型": 0, "deepseek": 1, "chat api": 2}
        providers.sort(key=lambda p: (_order.get(p["name"].strip().lower(), 99), p["name"].lower()))

        return providers

    def get_provider(self, provider_id: str) -> dict:
        row = self.db.execute(
            "SELECT * FROM model_providers WHERE id = ?", (provider_id,)
        ).fetchone()
        provider = row_to_dict(row)
        if provider:
            provider["models"] = self.list_models(provider_id)
        return provider

    def create_provider(self, data: dict) -> dict:
        now = iso_now()
        provider_id = uuid.uuid4().hex
        provider_icon = data.get("icon") or ModelStore.resolve_model_icon(data["name"])
        self.db.execute(
            """INSERT INTO model_providers
               (id, name, api_url, api_key, api_key_url, description,
                is_preset, status, created_at, updated_at, icon)
               VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?)""",
            (
                provider_id, data["name"], data["api_url"], data.get("api_key") or "",
                data.get("api_key_url") or "", data.get("description") or "",
                data.get("status") or "available", now, now, provider_icon,
            ),
        )
        self.db.commit()
        return self.get_provider(provider_id)

    def update_provider(self, provider_id: str, data: dict) -> dict | None:
        if not self.get_provider(provider_id):
            return None
        now = iso_now()
        # 图标：显式传入用传入值；未传则按新名称自动匹配（保留旧值优先）
        provider_icon = data.get("icon") or ModelStore.resolve_model_icon(data["name"])
        self.db.execute(
            """UPDATE model_providers
               SET name = ?, api_url = ?, api_key = ?, api_key_url = ?,
                   description = ?, status = ?, updated_at = ?, icon = ?
               WHERE id = ?""",
            (
                data["name"], data["api_url"], data.get("api_key") or "",
                data.get("api_key_url") or "", data.get("description") or "",
                data.get("status") or "available", now, provider_icon, provider_id,
            ),
        )
        self.db.execute(
            """UPDATE models
               SET api_url = ?, api_key = ?, updated_at = ?
               WHERE provider_id = ?""",
            (data["api_url"], data.get("api_key") or "", now, provider_id),
        )
        self.db.commit()
        return self.get_provider(provider_id)

    def list_models(self, provider_id: str | None = None) -> list[dict]:
        if provider_id:
            rows = self.db.execute(
                "SELECT * FROM models WHERE provider_id = ? ORDER BY name", (provider_id,)
            ).fetchall()
        else:
            rows = self.db.execute(
                "SELECT * FROM models ORDER BY is_default DESC, name"
            ).fetchall()
        return [row_to_dict(row) for row in rows]

    def get_model(self, model_id: str) -> dict:
        row = self.db.execute("SELECT * FROM models WHERE id = ?", (model_id,)).fetchone()
        return row_to_dict(row)

    def create_model(self, provider_id: str, data: dict) -> dict | None:
        provider = self.get_provider(provider_id)
        if not provider:
            return None
        now = iso_now()
        model_id = uuid.uuid4().hex
        model_icon = data.get("icon") or ModelStore.resolve_model_icon(data["name"])
        self.db.execute(
            """INSERT INTO models
               (id, provider_id, name, api_url, api_key, type, capabilities,
                context_window, is_default, status, created_at, updated_at, icon)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                model_id, provider_id, data["name"], provider["api_url"],
                provider.get("api_key") or "", data.get("type") or "chat",
                data.get("capabilities") or "", data.get("context_window") or 0,
                1 if data.get("is_default") else 0, data.get("status") or "available",
                now, now, model_icon,
            ),
        )
        if data.get("is_default"):
            self._set_single_default(model_id)
        self.db.commit()
        return self.get_model(model_id)

    def update_model(self, model_id: str, data: dict) -> dict | None:
        existing = self.get_model(model_id)
        if not existing:
            return None
        now = iso_now()
        # 图标：显式传入用传入值；未传则按新名称自动匹配
        model_icon = data.get("icon") or ModelStore.resolve_model_icon(data["name"])
        self.db.execute(
            """UPDATE models
               SET name = ?, type = ?, capabilities = ?, context_window = ?,
                   is_default = ?, status = ?, updated_at = ?, icon = ?
               WHERE id = ?""",
            (
                data["name"], data.get("type") or "chat", data.get("capabilities") or "",
                data.get("context_window") or 0, 1 if data.get("is_default") else 0,
                data.get("status") or "available", now, model_icon, model_id,
            ),
        )
        if data.get("is_default"):
            self._set_single_default(model_id)
        self.db.commit()
        return self.get_model(model_id)

    def delete_model(self, model_id: str) -> bool:
        existing = self.get_model(model_id)
        if not existing:
            return False
        # Record in deleted_presets so ensure_presets won't recreate it
        self.db.execute(
            "INSERT OR IGNORE INTO deleted_presets (id, deleted_at) VALUES (?, ?)",
            (model_id, iso_now()),
        )
        self.db.execute("DELETE FROM models WHERE id = ?", (model_id,))
        self.db.commit()
        return True

    def delete_provider(self, provider_id: str) -> bool:
        existing = self.get_provider(provider_id)
        if not existing:
            return False
        # Record provider and all its models in deleted_presets
        now = iso_now()
        self.db.execute(
            "INSERT OR IGNORE INTO deleted_presets (id, deleted_at) VALUES (?, ?)",
            (provider_id, now),
        )
        # Also mark all child models
        for model in (existing.get("models") or []):
            self.db.execute(
                "INSERT OR IGNORE INTO deleted_presets (id, deleted_at) VALUES (?, ?)",
                (model["id"], now),
            )
        self.db.execute("DELETE FROM models WHERE provider_id = ?", (provider_id,))
        self.db.execute("DELETE FROM model_providers WHERE id = ?", (provider_id,))
        self.db.commit()
        return True

    def _set_single_default(self, model_id: str) -> None:
        self.db.execute("UPDATE models SET is_default = CASE WHEN id = ? THEN 1 ELSE 0 END", (model_id,))
