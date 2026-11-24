"""贴表情核心逻辑（纯 Python，不依赖 SDK）。

提供：
1. set_msg_emoji_like 动作参数构造（message_id 保留符号，负 ID 合法）；
2. 合成通知消息构造（MessageGateway 注入，走完整入站链入库）；
3. 「群友是🐷」冷却/连贴状态机（PigReactState）与工具频控。
"""
from __future__ import annotations

from typing import Any, Dict, Mapping, Optional

class EmojiReactionReplacer:
    """贴表情核心逻辑。"""

    # ---------- 执行贴表情 ----------

    @staticmethod
    def parse_reactable_message_id(message_id: Any) -> Optional[int]:
        """把目标消息 ID 解析为可贴表情的整数 ID（QQ 消息 ID 为带符号 int32，负 ID 合法）。

        解析失败（如 napcat-shadow-* / emoji-reaction-notice-* 等合成通知 ID）
        返回 None：这类消息不是真实 QQ 消息，协议端没有可操作的消息 ID。
        """
        try:
            return int(str(message_id).strip())
        except (TypeError, ValueError):
            return None

    @staticmethod
    def build_set_emoji_like_params(message_id: Any, emoji_id: int, set_like: bool = True) -> Dict[str, Any]:
        """构造 set_msg_emoji_like 动作参数（message_id 保留符号，负 ID 合法）。"""
        return {
            "message_id": int(str(message_id).strip()),
            "emoji_id": str(emoji_id),
            "set": bool(set_like),
        }

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
    - normal_cooldowns: **全局冷却**（单 key，所有普通用户共享），默认 600s——
      任意普通用户贴了一次后，600s 内其它普通用户也不能贴（0 = 禁用冷却）；
    - pig_cooldowns: 「你是那么大个🐷」用户（**每 QQ 独立** key），默认 30min
      （0 = 禁用冷却）；
    - pig_chain: 「你是那么大个🐷」用户的连贴状态（当前连贴数，免冷却链内）；
    - tool_cooldowns: `emoji_like` 工具的每会话频控（key 为 stream_id，默认 10s）。
    """

    def __init__(self) -> None:
        self.normal_cooldowns: Dict[str, float] = {}
        self.pig_cooldowns: Dict[str, float] = {}
        self.pig_chain: Dict[str, int] = {}  # qq -> 已连贴数（本轮免冷却链）
        self.tool_cooldowns: Dict[str, float] = {}  # stream_id -> 冷却截止时间

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

    def tool_try_take(self, key: str, now: float, cooldown_seconds: float) -> bool:
        """工具频控（如 `emoji_like` 每会话最小调用间隔）。

        cooldown_seconds <= 0 时恒放行（不限频）；冷却期内返回 False 且**不延长**
        冷却（与占坑型判定不同：被拒的调用不重置计时）。
        """
        if cooldown_seconds <= 0:
            return True
        expires = self.tool_cooldowns.get(key)
        if expires is not None and expires > now:
            return False
        self.tool_cooldowns[key] = now + cooldown_seconds
        return True

    def cleanup(self, now: float) -> None:
        """清理过期冷却（简单遍历，量小可接受）。"""
        for store in (self.normal_cooldowns, self.pig_cooldowns, self.tool_cooldowns):
            expired = [k for k, v in store.items() if v <= now]
            for k in expired:
                store.pop(k, None)
