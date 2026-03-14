from __future__ import annotations

import json
from pathlib import Path
from typing import Any


RESOURCE_SUBDIRS: dict[str, tuple[str, ...]] = {
    "skill": ("skills", "skill"),
    "plugin": ("plugins", "plugin"),
    "hook": ("hooks", "hook"),
}


def collect_candidate_roots(
    *,
    project_root: str | None,
    active_project_root: str | None,
    active_config_file: str | None,
    active_config_dir: str | None,
) -> list[Path]:
    candidates: list[Path] = []
    for value in (project_root, active_project_root):
        root = _safe_path(value)
        if root is not None:
            candidates.append(root)
            candidates.append(root / ".opencode")
    config_file = _safe_path(active_config_file)
    if config_file is not None:
        candidates.append(config_file.parent)
        candidates.append(config_file.parent / ".opencode")
    config_dir = _safe_path(active_config_dir)
    if config_dir is not None:
        candidates.append(config_dir)
        candidates.append(config_dir.parent)
    seen: set[str] = set()
    unique: list[Path] = []
    for candidate in candidates:
        key = str(candidate.resolve(strict=False))
        if key in seen:
            continue
        seen.add(key)
        unique.append(candidate)
    return unique


def discover_resource_entries(kind: str, *, roots: list[Path]) -> list[dict[str, Any]]:
    normalized_kind = str(kind or "").strip().lower()
    subdirs = RESOURCE_SUBDIRS.get(normalized_kind)
    if not subdirs:
        return []
    results: list[dict[str, Any]] = []
    seen: set[str] = set()
    for root in roots:
        for subdir in subdirs:
            target = root / subdir
            if not target.exists():
                continue
            if normalized_kind == "skill":
                for skill_file in sorted(target.glob("**/SKILL.md")):
                    entry_path = skill_file.parent
                    key = str(entry_path.resolve(strict=False))
                    if key in seen:
                        continue
                    seen.add(key)
                    results.append(
                        {
                            "kind": normalized_kind,
                            "name": entry_path.name,
                            "path": str(entry_path.resolve(strict=False)),
                            "entryType": "directory",
                            "description": _extract_skill_description(skill_file),
                            "sourceRoot": str(root.resolve(strict=False)),
                            "metadata": {"file": str(skill_file.resolve(strict=False))},
                        }
                    )
                continue
            for item in sorted(target.iterdir()):
                key = str(item.resolve(strict=False))
                if key in seen:
                    continue
                seen.add(key)
                results.append(
                    {
                        "kind": normalized_kind,
                        "name": item.name,
                        "path": key,
                        "entryType": "directory" if item.is_dir() else "file",
                        "description": _extract_item_description(item),
                        "sourceRoot": str(root.resolve(strict=False)),
                        "metadata": {"exists": True},
                    }
                )
    return results


def load_json_file(path: str | Path | None) -> dict[str, Any] | None:
    file_path = _safe_path(path)
    if file_path is None or not file_path.is_file():
        return None
    try:
        payload = json.loads(file_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def flatten_models_from_provider_payload(payload: Any) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not isinstance(payload, dict):
        return [], []
    providers_payload = payload.get("value") if isinstance(payload.get("value"), dict) else payload
    if not isinstance(providers_payload, dict):
        return [], []
    providers: list[dict[str, Any]] = []
    models: list[dict[str, Any]] = []
    for provider_id, raw_provider in sorted(providers_payload.items()):
        if not isinstance(raw_provider, dict):
            continue
        model_map = raw_provider.get("models")
        if isinstance(model_map, dict):
            raw_models = model_map
        else:
            raw_models = {}
        providers.append(
            {
                "providerId": str(provider_id),
                "name": str(raw_provider.get("name") or provider_id),
                "modelCount": len(raw_models),
                "defaultModelId": str(raw_provider.get("defaultModel") or "") or None,
                "raw": raw_provider,
            }
        )
        for model_id, raw_model in sorted(raw_models.items()):
            if not isinstance(raw_model, dict):
                raw_model = {"name": str(model_id)}
            models.append(
                {
                    "id": str(raw_model.get("id") or model_id),
                    "providerId": str(raw_model.get("providerID") or provider_id),
                    "name": str(raw_model.get("name") or model_id),
                    "status": str(raw_model.get("status") or "active"),
                    "limit": raw_model.get("limit") if isinstance(raw_model.get("limit"), dict) else {},
                    "capabilities": raw_model.get("capabilities")
                    if isinstance(raw_model.get("capabilities"), dict)
                    else {},
                    "raw": raw_model,
                }
            )
    return providers, models


def extract_commands(payload: Any) -> list[dict[str, Any]]:
    values = payload.get("value") if isinstance(payload, dict) else payload
    if isinstance(values, dict):
        values = list(values.values())
    if not isinstance(values, list):
        return []
    items: list[dict[str, Any]] = []
    for raw in values:
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("name") or raw.get("id") or "").strip()
        if not name:
            continue
        items.append(
            {
                "name": name,
                "description": str(raw.get("description") or "").strip() or None,
                "source": str(raw.get("source") or "command"),
                "template": str(raw.get("template") or "").strip() or None,
                "subtask": bool(raw.get("subtask", False)),
                "hints": [str(item) for item in raw.get("hints", []) if str(item).strip()],
                "raw": raw,
            }
        )
    return items


def extract_agents(payload: Any) -> list[dict[str, Any]]:
    values = payload.get("value") if isinstance(payload, dict) else payload
    if isinstance(values, dict):
        values = list(values.values())
    if not isinstance(values, list):
        return []
    items: list[dict[str, Any]] = []
    for raw in values:
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("name") or raw.get("id") or "").strip()
        if not name:
            continue
        permissions = raw.get("permission") if isinstance(raw.get("permission"), list) else []
        items.append(
            {
                "name": name,
                "description": str(raw.get("description") or "").strip() or None,
                "mode": str(raw.get("mode") or "").strip() or None,
                "native": bool(raw.get("native", False)),
                "permissionCount": len(permissions),
                "raw": raw,
            }
        )
    return items


def extract_mcps(payload: Any) -> list[dict[str, Any]]:
    values = payload.get("value") if isinstance(payload, dict) else payload
    if isinstance(values, list):
        raw_items = values
    elif isinstance(values, dict):
        raw_items = []
        for name, raw in values.items():
            item = dict(raw) if isinstance(raw, dict) else {"value": raw}
            item.setdefault("name", name)
            raw_items.append(item)
    else:
        return []
    items: list[dict[str, Any]] = []
    for raw in raw_items:
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("name") or raw.get("id") or "").strip()
        if not name:
            continue
        items.append(
            {
                "name": name,
                "enabled": bool(raw.get("enabled", True)),
                "transport": str(raw.get("transport") or raw.get("type") or "").strip() or None,
                "description": str(raw.get("description") or "").strip() or None,
                "raw": raw,
            }
        )
    return items


def extract_tool_ids(payload: Any) -> list[dict[str, Any]]:
    values = payload.get("value") if isinstance(payload, dict) else payload
    if not isinstance(values, list):
        return []
    return [
        {"id": str(item), "name": str(item), "description": None, "raw": {"id": str(item)}}
        for item in values
        if str(item).strip()
    ]


def extract_tool_details(payload: Any) -> list[dict[str, Any]]:
    values = payload.get("value") if isinstance(payload, dict) else payload
    if not isinstance(values, list):
        return []
    items: list[dict[str, Any]] = []
    for raw in values:
        if not isinstance(raw, dict):
            continue
        tool_id = str(raw.get("id") or raw.get("name") or "").strip()
        if not tool_id:
            continue
        items.append(
            {
                "id": tool_id,
                "name": str(raw.get("name") or tool_id),
                "description": str(raw.get("description") or "").strip() or None,
                "raw": raw,
            }
        )
    return items


def extract_commands_from_raw_config(raw_config: dict[str, Any] | None) -> list[dict[str, Any]]:
    return _extract_named_object_entries(raw_config, "command")


def extract_agents_from_raw_config(raw_config: dict[str, Any] | None) -> list[dict[str, Any]]:
    return _extract_named_object_entries(raw_config, "agent")


def extract_mcps_from_raw_config(raw_config: dict[str, Any] | None) -> list[dict[str, Any]]:
    return _extract_named_object_entries(raw_config, "mcp")


def flatten_models_from_raw_config(raw_config: dict[str, Any] | None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    providers = raw_config.get("provider") if isinstance(raw_config, dict) else None
    if not isinstance(providers, dict):
        return [], []
    return flatten_models_from_provider_payload(providers)


def render_command_prompt(
    *,
    command: dict[str, Any],
    arguments: list[str] | None,
    raw_input: str | None,
) -> str:
    template = str(command.get("template") or "").strip()
    argument_text = str(raw_input or "").strip()
    if not argument_text and arguments:
        argument_text = " ".join(str(item).strip() for item in arguments if str(item).strip())
    if template:
        return template.replace("$ARGUMENTS", argument_text).strip()
    return f"/{command['name']} {argument_text}".strip()


def _extract_named_object_entries(raw_config: dict[str, Any] | None, key: str) -> list[dict[str, Any]]:
    values = raw_config.get(key) if isinstance(raw_config, dict) else None
    if not isinstance(values, dict):
        return []
    items: list[dict[str, Any]] = []
    for name, raw in sorted(values.items()):
        payload = dict(raw) if isinstance(raw, dict) else {"value": raw}
        payload.setdefault("name", name)
        items.append(payload)
    return items


def _extract_skill_description(skill_file: Path) -> str | None:
    try:
        for line in skill_file.read_text(encoding="utf-8").splitlines():
            stripped = line.strip().lstrip("#").strip()
            if stripped:
                return stripped
    except Exception:
        return None
    return None


def _extract_item_description(path: Path) -> str | None:
    if path.is_dir():
        return None
    if path.suffix.lower() not in {".md", ".txt", ".json", ".toml", ".yaml", ".yml"}:
        return None
    try:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            stripped = line.strip().lstrip("#").strip()
            if stripped:
                return stripped[:240]
    except Exception:
        return None
    return None


def _safe_path(value: str | Path | None) -> Path | None:
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    return Path(raw).resolve(strict=False)
