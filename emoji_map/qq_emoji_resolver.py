# -*- coding: utf-8 -*-
"""QQ 表情 ID → 名称解析模块（插件可复用）。

提供分层加载（内置合并映射 + 外部 JSON 覆盖），与 Undefined 项目 qq_emoji.py
的扩展机制一致（反向版：id -> 名称）。

用法（插件内）::

    from emoji_map.qq_emoji_resolver import QQEmojiResolver

    resolver = QQEmojiResolver()
    # 解析表情回应通知的 likes[].emoji_id
    name = resolver.resolve("12951")   # -> "点赞"
    name = resolver.resolve("999999")  # -> "未知表情999999"

外部覆盖文件（可选，按加载顺序后者覆盖前者）:
    - 环境变量 QQ_EMOJI_EXTRA 指向的 JSON（id -> 名称 字典）
    - 本模块同目录下 emoji_reaction_extra.json（扩展表情）
    - 本模块同目录下 qq_face_merged.json（内置合并映射，可被覆盖）
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent


class QQEmojiResolver:
    """QQ 表情 ID -> 名称 解析器。"""

    def __init__(self, extra_paths: list[str] | None = None) -> None:
        """初始化并加载映射。

        Args:
            extra_paths: 额外的 JSON 覆盖文件路径（id -> 名称 字典），
                后加载的覆盖先加载的。默认加载内置合并映射 + 扩展表。
        """
        self._id_to_name: dict[str, str] = {}
        self._load_builtin()
        self._load_extra(extra_paths or [])

    def _load_builtin(self) -> None:
        """加载内置映射：合并映射 + 扩展表情表。"""
        merged = HERE / "qq_face_merged.json"
        if merged.exists():
            self._id_to_name.update(_parse_emoji_json(_read_json(merged)))
        extra = HERE / "emoji_reaction_extra.json"
        if extra.exists():
            self._id_to_name.update(_parse_emoji_json(_read_json(extra)))

    def _load_extra(self, extra_paths: list[str]) -> None:
        """加载额外覆盖文件（含环境变量 QQ_EMOJI_EXTRA）。"""
        paths = list(extra_paths)
        env_extra = os.environ.get("QQ_EMOJI_EXTRA", "").strip()
        if env_extra:
            paths.append(env_extra)
        for raw_path in paths:
            path = Path(raw_path)
            if not path.is_file():
                continue
            self._id_to_name.update(_parse_emoji_json(_read_json(path)))

    def resolve(self, emoji_id: Any) -> str:
        """把表情 ID 解析为名称；未知返回「未知表情<id>」。"""
        key = str(emoji_id or "").strip()
        if not key:
            return "未知表情"
        return self._id_to_name.get(key, f"未知表情{key}")

    def resolve_likes(self, likes: list[Any]) -> list[str]:
        """解析表情回应通知的 likes 列表（[{emoji_id, count}]），返回名称列表。"""
        names: list[str] = []
        if not isinstance(likes, list):
            return names
        for like in likes:
            if not isinstance(like, dict):
                continue
            emoji_id = like.get("emoji_id")
            count = like.get("count", 1)
            name = self.resolve(emoji_id)
            if count and int(count) != 1:
                names.append(f"[{name}]x{count}")
            else:
                names.append(f"[{name}]")
        return names

    @property
    def size(self) -> int:
        return len(self._id_to_name)


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _parse_emoji_json(data: Any) -> dict[str, str]:
    """把三种 JSON 格式解析为 id -> 名称 字典。

    格式 A（简单字典）: {"12951": "点赞", ...}
    格式 B（emojis 列表）: {"emojis": [{"id": 12951, "name": "点赞", "aliases": [...]}, ...]}
    格式 C（纯列表）: [{"id": 12951, "name": "点赞"}, ...]
    """
    result: dict[str, str] = {}
    if not isinstance(data, dict):
        if isinstance(data, list):  # 格式 C
            return _parse_emoji_entries(data)
        return result

    if "emojis" in data:  # 格式 B
        emojis = data.get("emojis")
        if isinstance(emojis, list):
            result.update(_parse_emoji_entries(emojis))
        return result

    # 格式 A
    for k, v in data.items():
        if isinstance(v, (str, int)):
            result[str(k)] = str(v)
    return result


def _parse_emoji_entries(entries: list[Any]) -> dict[str, str]:
    """解析 emojis 列表条目（id + name/aliases）。"""
    result: dict[str, str] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        raw_id = entry.get("id")
        if raw_id is None:
            continue
        emoji_id = str(raw_id).strip()
        if not emoji_id:
            continue
        name = str(entry.get("name") or "").strip()
        if not name:
            aliases = entry.get("aliases")
            if isinstance(aliases, list) and aliases:
                name = str(aliases[0]).strip()
        if name:
            result[emoji_id] = name
    return result


if __name__ == "__main__":
    r = QQEmojiResolver()
    print(f"已加载 {r.size} 条映射")
    for test_id in ("76", "66", "12951", "379", "320", "127801", "999999"):
        print(f"  {test_id} -> {r.resolve(test_id)}")
