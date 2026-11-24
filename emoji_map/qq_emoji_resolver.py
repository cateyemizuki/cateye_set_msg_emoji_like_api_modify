"""加载 QQ 表情名称、描述和情绪标签，供表情工具与通知翻译使用。"""
from __future__ import annotations

import json
import os
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
MAX_EMOJI_ID = 2**31 - 1


def parse_emoji_id(value: Any) -> int | None:
    """解析非负 int32 表情 ID。"""
    text = str(value).strip()
    if not text.removeprefix("+").isdecimal():
        return None
    try:
        emoji_id = int(text)
    except ValueError:
        return None
    return emoji_id if emoji_id <= MAX_EMOJI_ID else None


@dataclass(frozen=True, slots=True)
class QQEmoji:
    emoji_id: str
    name: str
    description: str = ""
    emotion_tags: tuple[str, ...] = ()
    aliases: tuple[str, ...] = ()


class QQEmojiResolver:
    """按 ID 查表情，或按名称、别名、情绪标签和描述检索。"""

    def __init__(self, extra_paths: list[str] | None = None) -> None:
        self._mapped_emojis: dict[str, QQEmoji] = {}
        paths = [
            HERE / "qq_face_merged.json",
            HERE / "emoji_reaction_extra.json",
            HERE / "emoji_reaction_custom.json",
            *(Path(path) for path in extra_paths or []),
        ]
        env_extra = os.environ.get("QQ_EMOJI_EXTRA", "").strip()
        if env_extra:
            paths.append(Path(env_extra))
        for path in paths:
            self._load_map(path)
        self._emojis = self._mapped_emojis

    def _load_map(self, path: Path) -> None:
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            return
        for raw_id, raw in _iter_emoji_entries(data):
            emoji_id = parse_emoji_id(raw_id)
            if emoji_id is None:
                continue
            key = str(emoji_id)
            current = self._mapped_emojis.get(key, QQEmoji(key, ""))
            if isinstance(raw, (str, int)):
                raw = {"name": str(raw)}
            if not isinstance(raw, dict):
                continue

            aliases = _text_list(raw.get("aliases", current.aliases))
            name = _text(raw.get("name")) or current.name or (aliases[0] if aliases else "")
            if name:
                self._mapped_emojis[key] = QQEmoji(
                    key,
                    name,
                    _text(raw.get("description")) or current.description,
                    _text_list(raw.get("emotion_tags", current.emotion_tags)),
                    aliases,
                )

    def set_description_overrides(self, descriptions: Mapping[str, str]) -> None:
        """叠加旧配置中的自定义描述，已删除的覆盖项会恢复为映射表内容。"""
        emojis = self._mapped_emojis.copy()
        for raw_id, description in descriptions.items():
            emoji_id = parse_emoji_id(raw_id)
            if emoji_id is None:
                continue
            key = str(emoji_id)
            entry = emojis.get(key, QQEmoji(key, f"未知表情{key}"))
            emojis[key] = replace(entry, description=description)
        self._emojis = emojis

    def get(self, emoji_id: Any) -> QQEmoji | None:
        key = parse_emoji_id(emoji_id)
        return self._emojis.get(str(key))

    def resolve(self, emoji_id: Any) -> str:
        """把表情 ID 解析为名称，未收录的 ID 显示为「未知表情<id>」。"""
        entry = self.get(emoji_id)
        if entry is not None:
            return entry.name
        key = "" if emoji_id is None else str(emoji_id).strip()
        return f"未知表情{key}"

    def description(self, emoji_id: Any) -> str:
        entry = self.get(emoji_id)
        return entry.description if entry is not None else ""

    def search(self, keyword: str) -> list[QQEmoji]:
        query = keyword.strip().casefold()
        if not query:
            return []
        return [
            emoji for emoji in self._emojis.values()
            if any(query in text.casefold() for text in (
                emoji.name, emoji.description, *emoji.emotion_tags, *emoji.aliases
            ))
        ]

    def resolve_likes(self, likes: list[Any]) -> list[str]:
        """解析表情回应通知的 likes 列表（[{emoji_id, count}]）。"""
        names: list[str] = []
        if not isinstance(likes, list):
            return names
        for like in likes:
            if not isinstance(like, dict):
                continue
            name = self.resolve(like.get("emoji_id"))
            count = like.get("count", 1)
            if count and int(count) != 1:
                names.append(f"[{name}]x{count}")
            else:
                names.append(f"[{name}]")
        return names

    @property
    def size(self) -> int:
        return len(self._emojis)


def _iter_emoji_entries(data: Any) -> Iterator[tuple[Any, Any]]:
    """兼容 ID 字典、含 emojis 列表的对象和纯列表。"""
    if isinstance(data, dict):
        if "emojis" not in data:
            yield from data.items()
            return
        data = data["emojis"]
    if isinstance(data, list):
        for entry in data:
            if isinstance(entry, dict):
                yield entry.get("id"), entry


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _text_list(values: Any) -> tuple[str, ...]:
    if not isinstance(values, (list, tuple)):
        return ()
    return tuple(dict.fromkeys(text for value in values if (text := _text(value))))


if __name__ == "__main__":
    resolver = QQEmojiResolver()
    print(f"已加载 {resolver.size} 条映射")
    for test_id in ("76", "66", "12951", "379", "320", "127801", "999999"):
        print(f"  {test_id} -> {resolver.resolve(test_id)}")
