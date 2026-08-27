"""表情回应通知翻译核心逻辑（纯 Python，不依赖 SDK）。

拦截 NapCat 的 ``group_msg_emoji_like`` 通知（位于 message 的
``additional_config.napcat_notice_payload``），提取「谁 对哪条消息 贴了什么表情」，
翻译为可读文本，供 Hook 改写 ``processed_plain_text`` / ``raw_message`` 后
注入 MaiBot 框架内部。

参考数据（MaiBot DB 实测，NapCat 插件 codecs/notice/message_codec.py 保留原始 payload）::

    {
      "notice_type": "group_msg_emoji_like",
      "sub_type": "add",
      "group_id": 123456789,
      "user_id": 987654321,
      "operator_id": 987654321,
      "message_id": -822208709,     # 被回应消息 ID（带符号 int32，可为负）
      "message_seq": 867893,        # 被回应消息 msgSeq
      "likes": [{"emoji_id": "12951", "count": 1}]
    }
"""
from __future__ import annotations

from typing import Any, Dict, Mapping, Optional

# 表情回应通知类型（NapCat 插件 codecs/notice/message_codec.py）
NOTICE_TYPE_EMOJI_LIKE = "group_msg_emoji_like"

# 附加配置键（NapCat 插件 codecs/notice/message_codec.py:56-61）
CFG_NOTICE_TYPE = "napcat_notice_type"
CFG_NOTICE_SUB_TYPE = "napcat_notice_sub_type"
CFG_NOTICE_PAYLOAD = "napcat_notice_payload"


class EmojiLikeNoticeParser:
    """解析 NapCat 表情回应通知，生成可读文本。"""

    def __init__(
        self,
        emoji_resolver: Any = None,
        *,
        optimize_unknown: bool = False,
        description_library: Optional[Mapping[str, str]] = None,
    ) -> None:
        """初始化。

        Args:
            emoji_resolver: 表情 ID 解析器（实现 resolve() / resolve_likes()）。
                缺省时内部 lazy 导入 emoji_map.qq_emoji_resolver.QQEmojiResolver。
            optimize_unknown: 是否优化未知表情信息。True：未知表情显示为
                「一个表情」；False（默认）：显示「未知表情<id>」（与 snowluma 一致）。
            description_library: 插件的描述库 {emoji_id: 描述}。命中时在表情后追加
                「：描述」（如「一个表情：该回应表情等效网络流行的猪猪表情包...」）。
        """
        self._emoji_resolver = emoji_resolver
        self._optimize_unknown = bool(optimize_unknown)
        self._description_library: Dict[str, str] = {
            str(k): str(v) for k, v in (description_library or {}).items() if str(k).strip() and str(v).strip()
        }

    @property
    def optimize_unknown(self) -> bool:
        return self._optimize_unknown

    @optimize_unknown.setter
    def optimize_unknown(self, value: bool) -> None:
        self._optimize_unknown = bool(value)

    def set_description_library(self, library: Optional[Mapping[str, str]]) -> None:
        """更新描述库（配置热重载时调用）。"""
        self._description_library = {
            str(k): str(v) for k, v in (library or {}).items() if str(k).strip() and str(v).strip()
        }

    @property
    def description_library(self) -> Dict[str, str]:
        return dict(self._description_library)

    @property
    def emoji_resolver(self) -> Any:
        if self._emoji_resolver is None:
            try:
                from emoji_map.qq_emoji_resolver import QQEmojiResolver

                self._emoji_resolver = QQEmojiResolver()
            except Exception:
                self._emoji_resolver = _FallbackResolver()
        return self._emoji_resolver

    # ---------- 判定 ----------

    def is_emoji_like_notice(self, message_dict: Mapping[str, Any]) -> bool:
        """判断消息 dict 是否为表情回应通知。"""
        if not isinstance(message_dict, Mapping):
            return False
        if not bool(message_dict.get("is_notify", False)):
            return False
        additional = message_dict.get("message_info", {}).get("additional_config", {})
        if not isinstance(additional, Mapping):
            return False
        return str(additional.get(CFG_NOTICE_TYPE) or "").strip() == NOTICE_TYPE_EMOJI_LIKE

    # ---------- 解析 ----------

    def parse(self, message_dict: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
        """解析表情回应通知，返回结构化信息；非表情回应通知返回 None。

        返回::

            {
                "actor_user_id": "987654321",        # 谁（操作者）
                "actor_nickname": "群友A",             # 谁（显示名，可能为空）
                "target_message_id": "-822208709",    # 对哪条消息
                "target_message_seq": "867893",        # 被回应消息 msgSeq
                "likes": [{"emoji_id": "12951", "count": 1}],
                "names": ["点赞"],                      # 表情名列表（解析后）
                "summary": "群友A 对消息(ID:-822208709) 贴了 点赞",
            }
        """
        if not self.is_emoji_like_notice(message_dict):
            return None

        additional = message_dict.get("message_info", {}).get("additional_config", {})
        payload = additional.get(CFG_NOTICE_PAYLOAD)
        if not isinstance(payload, Mapping):
            return None

        actor_user_id = str(payload.get("user_id") or payload.get("operator_id") or "").strip()
        actor_nickname = self._resolve_actor_nickname(message_dict, actor_user_id)
        target_message_id = str(payload.get("message_id") or "").strip()
        target_message_seq = str(payload.get("message_seq") or "").strip()

        likes = payload.get("likes")
        if not isinstance(likes, list):
            likes = []

        names = self.emoji_resolver.resolve_likes(likes) if likes else []
        # 描述库命中：首个表情 ID 若在描述库中，取描述文本（如「一个表情：<描述>」）
        desc_hint = ""
        if likes and self._description_library:
            first_emoji_id = str(likes[0].get("emoji_id") or "").strip() if isinstance(likes[0], Mapping) else ""
            if first_emoji_id:
                desc_hint = self._description_library.get(first_emoji_id, "")
        # 未知表情（映射表缺失）：名称列表可能含 [未知表情<id>]；按 optimize_unknown 决定是否优化
        summary = self._build_summary(
            actor=actor_nickname or actor_user_id or "有人",
            target_message_id=target_message_id,
            names=names,
            has_likes=bool(likes),
            optimize_unknown=self._optimize_unknown,
            desc_hint=desc_hint,
        )

        return {
            "actor_user_id": actor_user_id,
            "actor_nickname": actor_nickname,
            "target_message_id": target_message_id,
            "target_message_seq": target_message_seq,
            "likes": likes,
            "names": names,
            "summary": summary,
        }

    # ---------- 文本构造 ----------

    def build_notice_text(self, message_dict: Mapping[str, Any]) -> Optional[str]:
        """生成改写后的通知文本；非表情回应通知返回 None。"""
        parsed = self.parse(message_dict)
        return parsed["summary"] if parsed else None

    @staticmethod
    def _build_summary(
        actor: str,
        target_message_id: str,
        names: list[str],
        has_likes: bool,
        optimize_unknown: bool = False,
        desc_hint: str = "",
    ) -> str:
        """构造 snowluma 风格通知文本。

        格式：``[事件-群消息表情回应] {actor} 对消息(ID:{id})表达了 {emoji}``

        - 表情名列表非空且不含未知 → 列出表情（如 [流泪]、[点赞]x2）；
        - 未知表情：
          - optimize_unknown=True → 「一个表情」；
          - optimize_unknown=False（默认）→ 保留解析器输出的「[未知表情<id>]」（与 snowluma 一致）。
        - desc_hint 非空（表情 ID 命中插件描述库）→ 显示「表情名：<描述>」
          （表情名取映射表解析结果，如「玫瑰：鲜花」；映射表缺失时退回「一个表情：<描述>」）。
        """
        target = f"消息(ID:{target_message_id})" if target_message_id else "一条消息"
        if desc_hint:
            # 描述库命中：优先显示「映射表情名：描述」（如「玫瑰：鲜花」）。
            # 表情名取 names 第一项并去掉方括号；names 为空（映射表缺失）时退回「一个表情：描述」。
            name_str = ""
            if has_likes and names:
                name_str = str(names[0]).strip("[]")
            emoji_part = f"{name_str}：{desc_hint}" if name_str else f"一个表情：{desc_hint}"
        elif has_likes and names:
            if optimize_unknown:
                known = [
                    n
                    for n in names
                    if n and not (n.startswith("[未知") or "未知表情" in n)
                ]
                emoji_part = "、".join(known) if known else "一个表情"
            else:
                emoji_part = "、".join(names)
        else:
            emoji_part = "一个表情"
        return f"[事件-群消息表情回应] {actor} 对{target}表达了 {emoji_part}"

    @staticmethod
    def _resolve_actor_nickname(message_dict: Mapping[str, Any], actor_user_id: str) -> str:
        """从消息的 user_info 或 payload 中取操作者昵称。"""
        user_info = message_dict.get("message_info", {}).get("user_info", {})
        if isinstance(user_info, Mapping):
            nickname = str(user_info.get("user_nickname") or "").strip()
            if nickname:
                return nickname
        # 兜底：通知里没有昵称时返回空，调用方用 user_id 代替
        return ""


class _FallbackResolver:
    """映射表不可用时的兜底解析器：全部显示为「一个表情」。"""

    def resolve_likes(self, likes: list) -> list:
        return []

    def resolve(self, emoji_id: Any) -> str:
        return "一个表情"


# 便捷工厂
def parse_emoji_like_notice(message_dict: Mapping[str, Any], emoji_resolver: Any = None) -> Optional[Dict[str, Any]]:
    """解析表情回应通知（便捷入口）。"""
    return EmojiLikeNoticeParser(emoji_resolver).parse(message_dict)
