"""表情回应插件 — MaiBot 插件入口。

功能：
1. 注册 LLM 工具「贴表情」（emoji_like）：让 LLM 自然决定对消息贴表情回应，
   作为 send_emoji 表达情绪的替代/补充（工具描述引导）。
2. 拦截 NapCat 的「表情回应」通知（group_msg_emoji_like），翻译为
   「谁 对哪条消息 贴了 什么表情」后改写消息文本，注入 MaiBot 框架内部。

实现要点（详见 IMPLEMENTATION_NOTES.md）：
- 贴表情：通过 NapCat 适配器插件的通用 action 入口
  ``adapter.napcat.action.call`` 直接下发 set_msg_emoji_like 动作，
  message_id 传原始带符号值（QQ 消息 ID 为带符号 int32，负 ID 合法）；
- 拦截通知：@HookHandler("chat.receive.before_process", BLOCKING) 改写
  ``kwargs["message"]["processed_plain_text"]`` 和 ``raw_message``；
- 表情名解析：emoji_map.qq_emoji_resolver.QQEmojiResolver（内置合并映射 +
  外部 JSON 覆盖，未知 ID 显示「一个表情」）。
"""

from __future__ import annotations

import json
import random
import time
from typing import Any, ClassVar, Dict, Iterable, Mapping, Optional

from maibot_sdk import Field, HookHandler, MaiBotPlugin, MessageGateway, PluginConfigBase, Tool
from maibot_sdk.types import ErrorPolicy, HookMode, HookOrder, ToolParameterInfo, ToolParamType
from pydantic import field_validator

from .emoji_reaction_replacer import DEFAULT_DESCRIPTION_LIBRARY, EmojiReactionReplacer, PigReactState
from .notice_translator import EmojiLikeNoticeParser

# ==================== 常量 ====================

# 配置版本：与 _manifest.json 的 version 保持同步。
# MaiBot 1.2.3+ 强制要求插件配置提供 plugin.config_version（runner_main.py
# extract_plugin_config_version），缺失会导致插件初始化失败。
SUPPORTED_CONFIG_VERSION = "0.1.0"

# 默认贴表情 ID（描述库为空时的兜底）：对应 QQ 表情「点赞」
DEFAULT_EMOJI_ID = 12951

# NapCat 适配器插件的通用 action 入口（唯一短名）。
# 用它直接下发 set_msg_emoji_like 动作，可传负 message_id（QQ 消息 ID 为带符号 int32），
# 绕过 NapCat 插件专用 set_msg_emoji_like API 的正整数校验。
NAPCAT_ACTION_CALL_API = "adapter.napcat.action.call"


# ==================== 配置模型 ====================


class EmojiLikeConfig(PluginConfigBase):
    """表情配置。"""

    __ui_label__ = "表情"
    __ui_icon__ = "sentiment_satisfied"
    __ui_order__ = 1

    optimize_unknown_emoji: bool = Field(
        default=False,
        description="优化未知表情信息：开启后未知表情显示为「一个表情」（如「表达了 一个表情」）；关闭时显示「未知表情<id>」（与 snowluma 一致，默认关闭）",
    )


class EmojiReactionConfig(PluginConfigBase):
    """贴表情工具配置。"""

    __ui_label__ = "贴表情工具"
    __ui_icon__ = "swap_horiz"
    __ui_order__ = 2

    description_library: list[str] = Field(
        default_factory=lambda: [
            f"{emoji_id}: {desc}" for emoji_id, desc in DEFAULT_DESCRIPTION_LIBRARY.items()
        ],
        description="描述库（每行一条）：`emoji_id: 描述`。如 `12951: 该回应表情等效网络流行的猪猪表情包，表达群友可爱又有点笨的样子`",
    )

    @field_validator("description_library", mode="before")
    @classmethod
    def _coerce_description_library(cls, value: Any) -> Any:
        """兼容旧配置格式：str JSON / dict → list[str]（每行 `id: 描述`）。"""
        if isinstance(value, str) and value.strip():
            try:
                parsed = json.loads(value)
            except Exception:
                return value
            value = parsed
        if isinstance(value, Mapping):
            return [f"{k}: {v}" for k, v in value.items()]
        return value


class PigFriendsConfig(PluginConfigBase):
    """群友是🐷：用户发消息时按概率/规则自动贴表情。"""

    __ui_label__ = "群友是🐷"
    __ui_icon__ = "pets"
    __ui_order__ = 3

    enabled: bool = Field(
        default=False,
        description="总开关：启用「群友是🐷」自动贴表情功能",
    )
    group_list_mode: str = Field(
        default="whitelist",
        description="群名单模式：whitelist=仅以下群生效；blacklist=以下群不生效",
    )
    group_list: list[str] = Field(
        default_factory=list,
        description="群名单（填群号；按 group_list_mode 决定白/黑名单）",
    )
    user_list_mode: str = Field(
        default="blacklist",
        description="用户名单模式：whitelist=仅以下用户生效；blacklist=以下用户不生效",
    )
    user_list: list[str] = Field(
        default_factory=list,
        description="用户名单（填 QQ 号；按 user_list_mode 决定白/黑名单）",
    )
    normal_probability: float = Field(
        default=0.05,
        description="普通用户每次发消息贴 12951 表情的概率（0~1，默认 0.05）",
    )
    normal_cooldown_seconds: int = Field(
        default=600,
        description="普通用户贴表情后的冷却秒数（默认 600 秒）",
    )
    pig_users: list[str] = Field(
        default_factory=list,
        description="你是那么大个🐷：这些 QQ 号不看黑白名单，每次发消息且冷却过即贴 12951",
    )
    pig_cooldown_seconds: int = Field(
        default=1800,
        description="🐷用户冷却秒数（默认 1800 = 30 分钟，每个 QQ 独立）",
    )
    pig_chain_skip_cooldown_probability: float = Field(
        default=0.25,
        description="🐷用户每次贴后不进冷却的概率（默认 0.25；命中则下一条消息直接贴）",
    )
    pig_max_chain: int = Field(
        default=3,
        description="🐷用户最多连贴的不同消息数（默认 3，第 3 个贴完停止本轮连贴）",
    )


class PluginSectionConfig(PluginConfigBase):
    """插件自身配置（plugin 配置节）。"""

    __ui_label__ = "插件"
    __ui_icon__ = "package"
    __ui_order__ = 0

    enabled: bool = Field(default=True, description="是否启用插件")
    config_version: str = Field(
        default=SUPPORTED_CONFIG_VERSION,
        description="配置版本（与插件版本同步，用于检查配置文件是否需要更新）",
        json_schema_extra={
            "disabled": True,
            "hidden": True,
            "label": "配置版本",
        },
    )


class CateyeSetMsgEmojiLikeConfig(PluginConfigBase):
    plugin: PluginSectionConfig = Field(default_factory=PluginSectionConfig)
    emoji: EmojiLikeConfig = Field(default_factory=EmojiLikeConfig)
    emoji_reaction: EmojiReactionConfig = Field(default_factory=EmojiReactionConfig)
    pig_friends: PigFriendsConfig = Field(default_factory=PigFriendsConfig)


# ==================== 插件主体 ====================


class CateyeSetMsgEmojiLikePlugin(MaiBotPlugin):
    """表情回应插件。"""

    config_model: ClassVar[type[PluginConfigBase] | None] = CateyeSetMsgEmojiLikeConfig
    config_reload_subscriptions: ClassVar[Iterable[str]] = ()

    def __init__(self) -> None:
        super().__init__()
        # 表情解析器：显式用「相对导入」构造，避免 runner 加载插件时
        # sys.path 不含插件目录导致的绝对导入失败（`from emoji_map...` 找不到包，
        # 退化为 _FallbackResolver → 所有表情都显示「一个表情」）。
        from .emoji_map.qq_emoji_resolver import QQEmojiResolver

        self._notice_parser = EmojiLikeNoticeParser(emoji_resolver=QQEmojiResolver())  # 表情回应通知解析器（内含表情映射）
        self._replacer = EmojiReactionReplacer()  # 贴表情核心逻辑（描述库/参数/聊天记录）
        self._pig_state = PigReactState()  # 「群友是🐷」冷却与连贴状态
        self._bot_nickname_cache: Dict[str, Any] = {"value": "", "expires": 0.0}  # 机器人昵称缓存

    # ==================== MessageGateway：注入合成通知 ====================

    @MessageGateway(
        "receive",
        name="emoji_reaction_reporter",
        description="注入贴表情合成通知消息（走完整入站链，入库显示在 WebUI）",
        platform="qq",
    )
    async def gateway_emoji_reaction_reporter(self, **kwargs: Any) -> Any:
        """接收网关声明：本插件通过此网关 route_message 注入合成通知消息。

        网关方法本身不需要处理外部消息（仅作组件载体），route_message 由工具调用。
        """
        del kwargs
        return None

    # ==================== Tool：贴表情 ====================

    @Tool(
        "emoji_like",
        description=(
            "对聊天中的某条消息贴一个 QQ 表情回应（reaction）。"
            "用于替代 send_emoji 表达情绪或与群友交互：当你想表达赞同、开心、无奈、可爱等情绪，"
            "或想与群友互动时，可以对目标消息贴一个表情回应，比发送表情包更轻量自然。"
            "默认贴到最近一条非机器人消息（通常是你正在回复/讨论的那条）。"
            "调用后请在你的回复中自然提及这次贴表情，避免重复表达。"
        ),
        parameters=[
            ToolParameterInfo(
                name="emoji",
                param_type=ToolParamType.STRING,
                description=(
                    "要贴的表情：可为描述库中的表达（如「猪猪表情」），或直接给表情 ID。"
                    "留空时使用默认表情（点赞）。"
                ),
                required=False,
            ),
            ToolParameterInfo(
                name="target_message_id",
                param_type=ToolParamType.STRING,
                description=(
                    "目标消息 ID（可选）。一般不需要传，插件会自动定位最近一条非机器人消息；"
                    "只有你明确知道要对某条具体消息贴表情时才传。"
                ),
                required=False,
            ),
        ],
    )
    async def tool_emoji_like(self, **kwargs: Any) -> Dict[str, Any]:
        """对消息贴 QQ 表情回应（LLM 工具入口）。"""
        stream_id = str(kwargs.get("stream_id") or "")
        emoji_raw = str(kwargs.get("emoji") or "").strip()
        target_message_id = str(kwargs.get("target_message_id") or "").strip()
        if not stream_id:
            return {"success": False, "error": "缺少 stream_id，无法贴表情"}

        # 1. 解析表情 ID（描述库匹配 or 直接数字）
        emoji_id = self._resolve_emoji_id(emoji_raw)
        if emoji_id is None:
            return {"success": False, "error": f"未识别的表情表达：{emoji_raw!r}，请从描述库中选择或使用有效表情 ID"}

        # 2. 定位目标消息（未指定时取最近一条非机器人消息）
        if not target_message_id:
            target_message_id = await self._find_recent_user_message(stream_id)
        if not target_message_id:
            return {"success": False, "error": "未找到可贴表情的目标消息（最近没有非机器人消息）"}

        # 3. 贴表情
        ok, error = await self._apply_emoji_like(stream_id, target_message_id, emoji_id)
        if not ok:
            return {"success": False, "error": error}

        # 4. 写聊天流记录（WebUI 可见）+ 注入 Planner 上下文
        await self._record_and_context(stream_id, target_message_id, emoji_id)

        desc = self._emoji_description(emoji_id)
        return {
            "success": True,
            "message": f"已对消息(ID:{target_message_id})贴了表情：{desc}",
            "emoji_id": emoji_id,
            "target_message_id": target_message_id,
        }

    # ==================== 贴表情辅助 ====================

    def _get_description_library(self) -> Dict[str, str]:
        """解析配置的 description_library 为 {emoji_id: 描述}。

        支持三种格式：
        - list[str]（当前主格式）：每行 `emoji_id: 描述`；
        - dict（旧格式）：{emoji_id: 描述}；
        - str JSON（过渡格式）：JSON 字符串。
        """
        raw = self.config.emoji_reaction.description_library
        parsed: Any = None
        if isinstance(raw, list):
            # 主格式：每行 "emoji_id: 描述"
            parsed = {}
            for line in raw:
                line = str(line or "").strip()
                if not line:
                    continue
                if ":" in line:
                    emoji_id, _, desc = line.partition(":")
                    emoji_id = emoji_id.strip()
                    desc = desc.strip()
                    if emoji_id and desc:
                        parsed[emoji_id] = desc
        elif isinstance(raw, Mapping):
            parsed = raw  # 兼容旧 dict 配置
        elif isinstance(raw, str) and raw.strip():
            try:
                parsed = json.loads(raw)
            except Exception:
                self.ctx.logger.warning("description_library JSON 解析失败，使用默认：%r", raw[:80])
        return self._replacer.normalize_description_library(parsed or DEFAULT_DESCRIPTION_LIBRARY)

    def _resolve_emoji_id(self, emoji_raw: str) -> Optional[int]:
        """解析表情：描述库按值匹配 → 数字直接转 int → 失败返回 None。"""
        emoji_raw = str(emoji_raw or "").strip()
        if not emoji_raw:
            # 空 → 默认表情
            return DEFAULT_EMOJI_ID
        # 描述库：值匹配（描述文本）
        library = self._get_description_library()
        for emoji_id, desc in library.items():
            if emoji_raw == desc or emoji_raw in desc or desc in emoji_raw:
                try:
                    return int(emoji_id)
                except (TypeError, ValueError):
                    continue
        # 直接数字
        try:
            return int(emoji_raw)
        except (TypeError, ValueError):
            return None

    async def _find_recent_user_message(self, stream_id: str) -> str:
        """找最近一条非机器人消息的 message_id（get_by_time_in_chat + filter_mai）。"""
        try:
            result = await self.ctx.message.get_by_time_in_chat(
                stream_id,
                start_time=str(time.time() - 24 * 3600),
                end_time=str(time.time()),
                filter_mai=True,
                limit=10,
            )
        except Exception as exc:
            self.ctx.logger.warning("获取最近消息失败（stream=%s）：%s", stream_id, exc)
            return ""
        messages = result
        # 兼容两种返回形态：SDK 归一化后直接是 list；防御性兼容 dict 包装
        if isinstance(result, dict):
            messages = result.get("messages")
        if not isinstance(messages, list) or not messages:
            return ""
        for msg in messages:
            if not isinstance(msg, Mapping):
                continue
            mid = str(msg.get("message_id") or "").strip()
            if mid:
                return mid
        return ""

    async def _apply_emoji_like(self, stream_id: str, message_id: str, emoji_id: int) -> tuple[bool, str]:
        """调用 NapCat 通用 action 入口贴表情。返回 (ok, error)。"""
        try:
            response = await self.ctx.api.call(
                NAPCAT_ACTION_CALL_API,
                action_name="set_msg_emoji_like",
                params=self._replacer.build_set_emoji_like_params(message_id, emoji_id),
            )
        except Exception as exc:
            self.ctx.logger.error("贴表情异常（stream=%s message_id=%s emoji_id=%s）：%s", stream_id, message_id, emoji_id, exc)
            return False, f"贴表情调用异常：{exc}"
        ok = (
            isinstance(response, Mapping)
            and (str(response.get("status") or "").lower() == "ok"
                 or response.get("retcode") == 0)
        )
        if not ok:
            err = ""
            if isinstance(response, Mapping):
                err = str(response.get("wording") or response.get("message") or response.get("error") or "")
            self.ctx.logger.warning("贴表情失败（stream=%s message_id=%s emoji_id=%s）：%s", stream_id, message_id, emoji_id, err or response)
            return False, err or "贴表情失败"
        return True, ""

    def _emoji_description(self, emoji_id: int) -> str:
        library = self._get_description_library()
        return library.get(str(emoji_id), "") or f"表情 {emoji_id}"

    async def _record_and_context(self, stream_id: str, message_id: str, emoji_id: int) -> None:
        """把贴表情行为记录到聊天流（WebUI 可见）+ 注入 Planner 上下文。

        方式：构造 is_notify=True 合成通知消息 → ctx.gateway.route_message 注入
        → 走完整入站链（heartflow process_message 自动写 DB）→ WebUI 可见、
        进聊天流，且不真发到群里（参照智能戳戳插件机器人自戳通知的入库机制）。
        """
        desc = self._emoji_description(emoji_id)
        # 反查流信息（self_id、群、昵称）——身份字段缺失时放弃注入，避免脏数据
        stream_info = await self._fetch_stream_info(stream_id)
        # 期望结构：`[事件-群消息表情回应] {bot名} 对消息(ID:X)贴了表情：{描述}`
        bot_name = str(stream_info.get("bot_nickname") or stream_info.get("self_id") or "").strip() or "机器人"
        record_text = f"[事件-群消息表情回应] {bot_name} 对消息(ID:{message_id})贴了表情：{desc}"
        if not str(stream_info.get("self_id") or "").strip():
            self.ctx.logger.warning(
                "贴表情记录身份信息缺失（self_id 为空），放弃注入聊天流（stream=%s）", stream_id
            )
        else:
            try:
                notice_message = self._replacer.build_inject_notice_message(
                    stream_info=stream_info,
                    record_text=record_text,
                    extra_payload={"target_message_id": message_id, "emoji_id": str(emoji_id)},
                )
                accepted = await self.ctx.gateway.route_message(
                    "emoji_reaction_reporter",
                    notice_message,
                    route_metadata={"self_id": stream_info.get("self_id") or ""},
                    external_message_id=str(notice_message.get("message_id") or ""),
                    dedupe_key=f"emoji-reaction-{stream_id}-{message_id}-{emoji_id}",
                )
                if accepted:
                    self.ctx.logger.info("贴表情记录已注入聊天流：%s", record_text)
                else:
                    self.ctx.logger.warning("贴表情记录注入被拒绝（stream=%s）", stream_id)
            except Exception as exc:
                self.ctx.logger.warning("注入贴表情聊天记录失败（stream=%s）：%s", stream_id, exc)

        # 注入 Planner 上下文（保证 LLM 后续回复知道贴了表情）
        try:
            await self.ctx.maisaka.context.append(
                stream_id,
                [{"type": "text", "content": record_text}],
                visible_text=record_text,
                source_kind="emoji_like_tool",
            )
        except Exception as exc:
            self.ctx.logger.warning("追加贴表情上下文失败（stream=%s）：%s", stream_id, exc)

    async def _fetch_stream_info(self, stream_id: str) -> Dict[str, Any]:
        """获取流信息（self_id、群、昵称）。

        bot_nickname 优先用 NapCat get_login_info 查机器人自己的昵称（缓存），
        彻底避免「反查最近消息 → 撞上本插件注入消息 → 循环取到群友名」的问题；
        消息反查仅作为 self_id / group 兜底来源。
        """
        stream_info: Dict[str, Any] = {}
        # 1. 消息反查：拿 self_id / group（不依赖昵称）
        try:
            result = await self.ctx.message.get_by_time_in_chat(
                stream_id,
                start_time=str(time.time() - 24 * 3600),
                end_time=str(time.time()),
                filter_mai=False,
                limit=10,
            )
            messages = result
            if isinstance(result, dict):
                messages = result.get("messages")
            if isinstance(messages, list):
                for msg in messages:
                    if not isinstance(msg, Mapping):
                        continue
                    message_info = msg.get("message_info") if isinstance(msg.get("message_info"), Mapping) else {}
                    group_info = message_info.get("group_info") if isinstance(message_info.get("group_info"), Mapping) else {}
                    additional = message_info.get("additional_config") if isinstance(message_info.get("additional_config"), Mapping) else {}
                    if not stream_info.get("self_id") and (additional.get("self_id") or additional.get("platform_io_account_id")):
                        stream_info["platform"] = str(msg.get("platform") or "qq")
                        stream_info["self_id"] = str(additional.get("self_id") or additional.get("platform_io_account_id") or "")
                        stream_info["group_info"] = group_info
                        if stream_info.get("group_info") and not stream_info.get("group_info").get("group_name"):
                            pass
        except Exception as exc:
            self.ctx.logger.warning("获取流信息失败（stream=%s）：%s", stream_id, exc)
        if not stream_info.get("self_id"):
            return {"platform": "qq", "self_id": "", "bot_nickname": "", "user_info": {}, "group_info": {}}

        # 2. bot_nickname：优先 get_login_info（缓存），兜底 self_id
        bot_nickname = await self._fetch_bot_nickname(str(stream_info.get("self_id") or ""))
        stream_info["bot_nickname"] = bot_nickname
        stream_info["user_info"] = {
            "user_id": stream_info.get("self_id") or "",
            "user_nickname": bot_nickname,
            "user_cardname": None,
        }
        return stream_info

    async def _fetch_bot_nickname(self, self_id: str) -> str:
        """用 NapCat get_login_info 查机器人自己的昵称（缓存 1 小时）。"""
        now = time.time()
        cached = self._bot_nickname_cache.get("value")
        if cached and self._bot_nickname_cache.get("expires", 0) > now:
            return cached
        try:
            result = await self.ctx.api.call("adapter.napcat.system.get_login_info")
            if isinstance(result, Mapping):
                data = result.get("data") if isinstance(result.get("data"), Mapping) else result
                nickname = str(data.get("nickname") or data.get("user_nickname") or "").strip()
                if nickname:
                    self._bot_nickname_cache = {"value": nickname, "expires": now + 3600}
                    return nickname
        except Exception as exc:
            self.ctx.logger.warning("获取机器人昵称失败（self_id=%s）：%s", self_id, exc)
        return self_id  # 兜底：QQ 号

    # ==================== Hook：群友是🐷 ====================

    @HookHandler(
        "chat.receive.before_process",
        name="pig_friends_listener",
        description="用户发消息时按概率/规则自动贴 12951 表情（群友是🐷）",
        mode=HookMode.BLOCKING,
        order=HookOrder.EARLY,
        error_policy=ErrorPolicy.SKIP,
    )
    async def hook_pig_friends_listener(self, message: Optional[Mapping[str, Any]] = None, **kwargs: Any) -> Dict[str, Any]:
        """拦截用户入站消息，判定是否自动贴表情。

        流程：总开关 → 群名单 → 用户名单 → 🐷用户/普通用户分流 → 冷却 → 贴表情。
        - 🐷用户：不看黑白名单，冷却过即贴（独立冷却，连贴链）；
        - 普通用户：0.05 概率贴 1 个 → 120s 冷却。
        贴表情走标准流程（_apply_emoji_like + _record_and_context）。
        """
        del kwargs
        if message is None:
            return {"action": "continue"}
        try:
            if not self.config.pig_friends.enabled:
                return {"action": "continue"}
            await self._pig_try_react(message)
        except Exception as exc:
            self.ctx.logger.warning("群友是🐷判定异常：%s", exc)
        return {"action": "continue"}

    async def _pig_try_react(self, message: Mapping[str, Any]) -> None:
        """「群友是🐷」核心判定：命中则贴表情。"""
        # 仅处理用户入站消息（非通知、非命令、非机器人自己）
        if bool(message.get("is_notify", False)):
            return
        if bool(message.get("is_command", False)):
            return
        message_info = message.get("message_info") if isinstance(message.get("message_info"), Mapping) else {}
        user_info = message_info.get("user_info") if isinstance(message_info.get("user_info"), Mapping) else {}
        group_info = message_info.get("group_info") if isinstance(message_info.get("group_info"), Mapping) else {}
        additional = message_info.get("additional_config") if isinstance(message_info.get("additional_config"), Mapping) else {}
        self_id = str(additional.get("self_id") or additional.get("platform_io_account_id") or "").strip()
        user_id = str(user_info.get("user_id") or "").strip()
        group_id = str(group_info.get("group_id") or "").strip()
        if not user_id or user_id == self_id:
            return
        # 私聊无 group_id
        stream_id = str(message.get("session_id") or "")

        cfg = self.config.pig_friends
        now = time.time()

        # 群名单（先验证群号；私聊 group_id 空 → 无群校验，直接过）
        if group_id:
            if not EmojiReactionReplacer.is_allowed_by_list(group_id, cfg.group_list, cfg.group_list_mode):
                return
        # 用户名单（后验证 QQ 号）
        if not EmojiReactionReplacer.is_allowed_by_list(user_id, cfg.user_list, cfg.user_list_mode):
            return

        pig_qqs = {str(x).strip() for x in (cfg.pig_users or []) if str(x).strip()}
        is_pig = user_id in pig_qqs

        # 目标消息：当前用户消息本身（标准流程贴到用户消息）
        target_message_id = str(message.get("message_id") or "").strip()
        if not target_message_id:
            return

        if is_pig:
            await self._pig_react(user_id, target_message_id, stream_id, cfg, now)
        else:
            await self._normal_react(user_id, group_id, target_message_id, stream_id, cfg, now)

    async def _normal_react(
        self, user_id: str, group_id: str, target_message_id: str, stream_id: str,
        cfg: Any, now: float,
    ) -> None:
        """普通用户：0.05 概率 → 贴 1 个 → 全局冷却。"""
        try:
            prob = max(0.0, min(1.0, float(cfg.normal_probability)))
        except (TypeError, ValueError):
            prob = 0.05
        if prob <= 0:
            return
        if random.random() > prob:
            return
        cooldown = max(0, int(cfg.normal_cooldown_seconds or 120))
        # 全局冷却判定 + 占坑（所有普通用户共享，原子）
        if not self._pig_state.normal_try_take(now, cooldown):
            return
        await self._do_pig_stick(stream_id, target_message_id, cfg, user_id)

    async def _pig_react(
        self, user_id: str, target_message_id: str, stream_id: str, cfg: Any, now: float,
    ) -> None:
        """🐷用户：冷却过即贴；贴后 0.25 概率免冷却连贴（最多 max_chain 条）。

        连贴链：0.25 命中 → pig_chain_advance 进入链（清除冷却）→ 下一条消息
        触发时 pig_chain_active 判定 → 直接贴（不再判冷却/概率）→ 贴后再次 0.25
        判定是否继续链；链计数达 max_chain 时退出链（恢复正常冷却流程）。
        """
        cooldown = max(0, int(cfg.pig_cooldown_seconds or 1800))
        chain_max = max(1, int(cfg.pig_max_chain or 3))
        skip_prob = max(0.0, min(1.0, float(cfg.pig_chain_skip_cooldown_probability or 0.25)))

        # 冷却判定 + 占坑（链内 pig_try_take 直接 True）
        if not self._pig_state.pig_try_take(user_id, now, cooldown):
            return

        # 贴当前消息
        await self._do_pig_stick(stream_id, target_message_id, cfg, user_id)

        # 判定是否进入免冷却连贴链
        chain_count = self._pig_state.pig_chain_count(user_id)
        if chain_count >= chain_max:
            # 达上限：退出链，恢复正常冷却（重新占坑）
            self._pig_state.pig_chain_reset(user_id, now, cooldown)
            self.ctx.logger.info("🐷用户 %s 连贴达上限（%d 条），恢复正常冷却", user_id, chain_max)
            return
        if random.random() < skip_prob:
            # 进入链：下一条消息直接贴（清除冷却）
            new_count = self._pig_state.pig_chain_advance(user_id, now, cooldown)
            self.ctx.logger.info(
                "🐷用户 %s 免冷却连贴（第 %d/%d 条后），下一条消息将直接贴",
                user_id, new_count, chain_max,
            )
        else:
            # 0.25 未命中：退出链，恢复正常冷却
            self._pig_state.pig_chain_reset(user_id, now, cooldown)

    async def _do_pig_stick(self, stream_id: str, target_message_id: str, cfg: Any, user_id: str) -> None:
        """贴 12951 表情（标准流程：贴表情 + 记录 + 上下文）。"""
        emoji_id = 12951
        ok, err = await self._apply_emoji_like(stream_id, target_message_id, emoji_id)
        if not ok:
            self.ctx.logger.warning("群友是🐷贴表情失败（user=%s msg=%s）：%s", user_id, target_message_id, err)
            return
        self.ctx.logger.info("群友是🐷：对用户 %s 的消息 %s 贴了 12951", user_id, target_message_id)
        await self._record_and_context(stream_id, target_message_id, emoji_id)

    # ==================== Hook：表情回应通知翻译 ====================

    @HookHandler(
        "chat.receive.before_process",
        name="emoji_like_notice_translator",
        description="拦截 NapCat 表情回应通知，翻译为「谁 对哪条消息 贴了 什么表情」",
        mode=HookMode.BLOCKING,
        order=HookOrder.EARLY,
        error_policy=ErrorPolicy.SKIP,
    )
    async def hook_translate_emoji_like_notice(self, **kwargs: Any) -> Dict[str, Any]:
        """拦截表情回应通知并改写消息文本。

        - 通过 blocking 模式修改 kwargs["message"]（序列化消息 dict）；
        - 改写 processed_plain_text 与 raw_message（单条 text 段），
          使 MaiBot 后续处理（含 message.process() 重生成文本）使用翻译后的内容；
        - 非表情回应通知原样返回，不拦截。
        """
        message = kwargs.get("message")
        if not isinstance(message, Mapping):
            return {"action": "continue", "modified_kwargs": kwargs}

        notice_text = self._notice_parser.build_notice_text(message)
        if not notice_text:
            return {"action": "continue", "modified_kwargs": kwargs}

        # 改写消息：processed_plain_text + raw_message（text 段），display_message 同步
        mutated = dict(message)
        mutated["processed_plain_text"] = notice_text
        mutated["display_message"] = notice_text
        mutated["raw_message"] = [{"type": "text", "data": notice_text}]

        self.ctx.logger.info("表情回应通知已翻译：%s", notice_text)

        modified_kwargs = dict(kwargs)
        modified_kwargs["message"] = mutated
        return {"action": "continue", "modified_kwargs": modified_kwargs}

    # ==================== 版本兼容 ====================

    def _check_config_version(self) -> None:
        """检测配置版本并自动兼容旧版配置文件。

        当前版本：0.1.0。Runner 在配置注入时已按默认值自动补齐
        config_version 等缺失字段，这里仅做日志提示。
        """
        try:
            raw = self.get_plugin_config_data()
            current = str((raw.get("plugin") or {}).get("config_version") or "").strip()
        except Exception:
            return
        if current and current != SUPPORTED_CONFIG_VERSION:
            self.ctx.logger.info(
                "检测到旧版配置（config_version=%s，当前支持 %s），缺失字段已按默认值自动补齐",
                current,
                SUPPORTED_CONFIG_VERSION,
            )

    def _sync_notice_config(self) -> None:
        """把配置的「未知表情优化」开关和描述库同步到通知解析器。"""
        try:
            optimize = bool(self.config.emoji.optimize_unknown_emoji)
        except Exception:
            optimize = False
        self._notice_parser.optimize_unknown = optimize
        try:
            library = self._get_description_library()
        except Exception:
            library = {}
        self._notice_parser.set_description_library(library)

    # ==================== 生命周期 ====================

    async def on_load(self) -> None:
        self._check_config_version()
        self._sync_notice_config()
        # 上报消息网关就绪（route_message 注入需要网关 ready）
        try:
            await self.ctx.gateway.update_state(
                "emoji_reaction_reporter",
                ready=True,
                platform="qq",
            )
        except Exception as exc:
            self.ctx.logger.warning("上报消息网关状态失败：%s", exc)
        self.ctx.logger.info("表情回应插件已加载")

    async def on_unload(self) -> None:
        self.ctx.logger.info("表情回应插件已卸载")

    async def on_config_update(self, scope: str, config_data: Dict[str, Any], version: str) -> None:
        del config_data, version
        if scope == "self":
            self._check_config_version()
            self._sync_notice_config()
            self.ctx.logger.info("表情回应插件配置已更新")


def create_plugin() -> CateyeSetMsgEmojiLikePlugin:
    return CateyeSetMsgEmojiLikePlugin()
