"""贴表情核心逻辑（纯 Python，不依赖 SDK）。

提供：
1. 描述库规范化（emoji_id -> 描述文本，供 LLM 工具选择）；
2. set_msg_emoji_like 动作参数构造（message_id 保留符号，负 ID 合法）；
3. 聊天流记录（mai_messages）构造与身份校验（换环境/人设安全）。
"""
from __future__ import annotations

from typing import Any, Dict, Mapping

# 描述库配置默认值：emoji_id -> 描述文本
DEFAULT_DESCRIPTION_LIBRARY: Dict[str, str] = {
    "12951": "该回应表情等效网络流行的猪猪表情包，表达群友可爱又有点笨的样子",
}


class EmojiReactionReplacer:
    """贴表情核心逻辑。"""

    # ---------- 描述库 ----------

    @staticmethod
    def normalize_description_library(raw: Any) -> Dict[str, str]:
        """规范化描述库配置：{emoji_id: 描述}。"""
        library: Dict[str, str] = {}
        if not isinstance(raw, Mapping):
            return library
        for key, value in raw.items():
            emoji_id = str(key).strip()
            desc = str(value or "").strip()
            if emoji_id and desc:
                library[emoji_id] = desc
        return library

    # ---------- 执行贴表情 ----------

    @staticmethod
    def build_set_emoji_like_params(message_id: Any, emoji_id: int, set_like: bool = True) -> Dict[str, Any]:
        """构造 set_msg_emoji_like 动作参数（message_id 保留符号，负 ID 合法）。"""
        return {
            "message_id": int(str(message_id).strip()),
            "emoji_id": str(emoji_id),
            "set": bool(set_like),
        }

    # ---------- 聊天流记录（写入 mai_messages） ----------

    @staticmethod
    def build_chat_record(
        *,
        message_id: str,
        session_id: str,
        stream_info: Mapping[str, Any],
        record_text: str,
        raw_content: Any,
    ) -> Dict[str, Any]:
        """构造一条可写入 mai_messages 的「贴表情记录」数据。

        以机器人（self）身份写入，processed_plain_text 为记录文本，
        raw_content 为调用方序列化好的消息段 bytes。

        所有身份字段均来自运行时数据（stream_info），不做环境/人设假设；
        关键字段缺失时由 validate_chat_record 判断是否放弃写入。
        """
        user_info = stream_info.get("user_info") if isinstance(stream_info.get("user_info"), Mapping) else {}
        group_info = stream_info.get("group_info") if isinstance(stream_info.get("group_info"), Mapping) else {}
        self_id = str(stream_info.get("self_id") or "").strip()
        platform = str(stream_info.get("platform") or "").strip() or "qq"
        # 机器人昵称：优先 user_info.user_nickname，缺失回退 bot_nickname，
        # 不再写死「机器人」避免跨人设错名（缺失由校验拒绝）。
        nickname = str(
            user_info.get("user_nickname")
            or stream_info.get("bot_nickname")
            or ""
        ).strip()
        group_id = str(group_info.get("group_id") or "").strip()
        group_name = str(group_info.get("group_name") or "").strip()

        return {
            "message_id": str(message_id),
            "timestamp": __import__("datetime").datetime.now(),
            "platform": platform,
            "user_id": self_id,
            "user_nickname": nickname,
            "user_cardname": None,
            "group_id": group_id or None,
            "group_name": group_name or None,
            "is_mentioned": False,
            "is_at": False,
            "session_id": str(session_id),
            "reply_to": None,
            "is_emoji": False,
            "is_picture": False,
            "is_command": False,
            "is_notify": False,
            "raw_content": raw_content,
            "processed_plain_text": str(record_text),
            "additional_config": None,
            "reply_frequency": None,
        }

    @staticmethod
    def validate_chat_record(record: Mapping[str, Any]) -> bool:
        """校验贴表情记录是否可安全写入：身份字段缺失时返回 False（调用方放弃写入）。

        避免换环境/人设后 self_id、昵称等缺失导致写入脏数据（如 user_id="0"、昵称"机器人"）。
        """
        if not str(record.get("message_id") or "").strip():
            return False
        if not str(record.get("session_id") or "").strip():
            return False
        if not str(record.get("user_id") or "").strip():
            return False
        if not str(record.get("user_nickname") or "").strip():
            return False
        if not str(record.get("processed_plain_text") or "").strip():
            return False
        return True

    # ---------- 合成通知消息（MessageGateway 注入，走完整入站链入库） ----------

    @staticmethod
    def build_inject_notice_message(
        *,
        stream_info: Mapping[str, Any],
        record_text: str,
        extra_payload: Mapping[str, Any] | None = None,
    ) -> Dict[str, Any]:
        """构造一条 is_notify=True 的合成通知消息 dict，供 ctx.gateway.route_message 注入。

        参照 NapCat 插件通知消息结构（codecs/notice/message_codec.py build_notice_message_dict）：
        - is_notify=True → 走完整入站链 → heartflow process_message 自动写 DB（WebUI 可见）；
        - user_info 用机器人自己（self_id / 昵称）；
        - group_info 从 stream_info 取（群聊时）。
        """
        from uuid import uuid4

        user_info = stream_info.get("user_info") if isinstance(stream_info.get("user_info"), Mapping) else {}
        group_info = stream_info.get("group_info") if isinstance(stream_info.get("group_info"), Mapping) else {}
        self_id = str(stream_info.get("self_id") or "").strip()
        platform = str(stream_info.get("platform") or "qq").strip() or "qq"
        # ⚠️ bot_nickname 只从 stream_info.bot_nickname 取（_fetch_stream_info 已保证
        # 它是机器人自己的昵称）；不能用 user_info.user_nickname（那是最近消息的发送者，
        # 可能是群友，会导致 WebUI 显示「机器人头像 + 群友名字」错配）。
        # 最终兜底：仍为空时用 self_id，保证 user_nickname 非空（Host 校验要求）。
        bot_nickname = str(stream_info.get("bot_nickname") or "").strip() or self_id

        message_info: Dict[str, Any] = {
            "user_info": {
                "user_id": self_id,
                "user_nickname": bot_nickname,
                "user_cardname": None,
            },
            "additional_config": {
                "self_id": self_id,
                "plugin_injected_notice": "emoji_reaction_record",
                **(extra_payload or {}),
            },
        }
        if group_info.get("group_id"):
            message_info["group_info"] = {
                "group_id": str(group_info.get("group_id") or ""),
                "group_name": str(group_info.get("group_name") or ""),
            }

        return {
            "message_id": f"emoji-reaction-notice-{uuid4().hex}",
            "timestamp": str(__import__("time").time()),
            "platform": platform,
            "message_info": message_info,
            "raw_message": [{"type": "text", "data": record_text}],
            "is_mentioned": False,
            "is_at": False,
            "is_emoji": False,
            "is_picture": False,
            "is_command": False,
            "is_notify": True,
            "session_id": "",
            "processed_plain_text": record_text,
            "display_message": record_text,
        }

    # ---------- 群友是🐷：黑白名单 / 冷却 / 连贴 ----------

    @staticmethod
    def is_allowed_by_list(value: str, items: Any, mode: str) -> bool:
        """黑白名单判定：mode in {"whitelist", "blacklist"}。

        - whitelist：在名单内才放行；
        - blacklist：在名单内则拦截。
        """
        value = str(value or "").strip()
        if not value:
            return False
        items_set = {str(x).strip() for x in (items or []) if str(x).strip()}
        if mode == "whitelist":
            return value in items_set
        if mode == "blacklist":
            return value not in items_set
        return True


class PigReactState:
    """「群友是🐷」的冷却与连贴状态机（纯内存，线程内安全）。

    冷却语义：
    - normal_cooldowns: **全局冷却**（单 key，所有普通用户共享），默认 120s——
      任意普通用户贴了一次后，120s 内其它普通用户也不能贴；
    - pig_cooldowns: 「你是那么大个🐷」用户（**每 QQ 独立** key），默认 30min；
    - pig_chain: 「你是那么大个🐷」用户的连贴状态（当前连贴数，免冷却链内）。
    """

    def __init__(self) -> None:
        self.normal_cooldowns: Dict[str, float] = {}
        self.pig_cooldowns: Dict[str, float] = {}
        self.pig_chain: Dict[str, int] = {}  # qq -> 已连贴数（本轮免冷却链）

    def _in_cooldown(self, store: Dict[str, float], key: str, now: float, cooldown_seconds: float) -> bool:
        expires = store.get(key)
        if expires is not None and expires > now:
            return True
        store[key] = now + cooldown_seconds
        return False

    def normal_try_take(self, now: float, cooldown_seconds: float) -> bool:
        """普通用户：**全局冷却**（单 key，所有普通用户共享）。

        冷却期过则占坑（进入冷却）并返回 True（本次可贴）。
        """
        return not self._in_cooldown(self.normal_cooldowns, "global", now, cooldown_seconds)

    def pig_try_take(self, qq: str, now: float, cooldown_seconds: float) -> bool:
        """猪用户：冷却期过则占坑并返回 True（本次可贴）。

        免冷却链内（pig_chain_active）时直接返回 True 且不占坑（链由
        pig_chain_advance 管理）。
        """
        if self.pig_chain_active(qq):
            return True
        return not self._in_cooldown(self.pig_cooldowns, qq, now, cooldown_seconds)

    def pig_chain_active(self, qq: str) -> bool:
        """是否处于免冷却连贴链（链内消息直接贴，不再判冷却）。"""
        return int(self.pig_chain.get(qq, 0)) > 0

    def pig_chain_count(self, qq: str) -> int:
        return int(self.pig_chain.get(qq, 0))

    def pig_chain_reset(self, qq: str, now: float = 0.0, cooldown_seconds: float = 0.0) -> None:
        """退出免冷却连贴链。

        若指定了 now/cooldown（链结束时），重新占冷却坑，恢复正常冷却流程；
        否则仅清计数（如首次触发前）。
        """
        self.pig_chain.pop(qq, None)
        if now > 0 and cooldown_seconds > 0:
            self.pig_cooldowns[qq] = now + cooldown_seconds

    def pig_chain_advance(self, qq: str, now: float, cooldown_seconds: float) -> int:
        """推进免冷却连贴链：进入链（计数 +1）并清除冷却占坑（本链内免冷却）。

        返回新的连贴计数。
        """
        count = int(self.pig_chain.get(qq, 0)) + 1
        self.pig_chain[qq] = count
        self.pig_cooldowns.pop(qq, None)  # 清除冷却，链内下一条直接贴
        return count

    def cleanup(self, now: float) -> None:
        """清理过期冷却（简单遍历，量小可接受）。"""
        for store in (self.normal_cooldowns, self.pig_cooldowns):
            expired = [k for k, v in store.items() if v <= now]
            for k in expired:
                store.pop(k, None)
