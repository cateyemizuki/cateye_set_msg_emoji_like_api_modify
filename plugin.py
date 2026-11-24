"""表情回应插件 — MaiBot 插件入口。

功能：
1. 注册 LLM 工具「贴表情」（emoji_like）：让 LLM 自然决定对消息贴表情回应，
   用同一个工具按关键词检索表情，或按 ID 贴到聊天消息上。
2. 拦截 NapCat 的「表情回应」通知（group_msg_emoji_like），翻译为
   「谁 对哪条消息 贴了 什么表情」后改写消息文本，注入 MaiBot 框架内部。

实现要点：
- 贴表情：通过 NapCat 适配器插件的通用 action 入口
  ``adapter.napcat.action.call`` 直接下发 set_msg_emoji_like 动作，
  message_id 传原始带符号值（QQ 消息 ID 为带符号 int32，负 ID 合法）；
- 拦截通知：@HookHandler("chat.receive.before_process", BLOCKING) 改写
  ``kwargs["message"]["processed_plain_text"]`` 和 ``raw_message``；
- 表情名解析：emoji_map.qq_emoji_resolver.QQEmojiResolver（内置合并映射 +
  外部 JSON 覆盖，未知 ID 显示「一个表情」）。
"""

from __future__ import annotations

import asyncio
import json
import random
import time
from unicodedata import normalize
from typing import Any, ClassVar, Dict, Iterable, Literal, Mapping, Optional

from maibot_sdk import Field, HookHandler, MaiBotPlugin, MessageGateway, PluginConfigBase, Tool
from maibot_sdk.types import ErrorPolicy, HookMode, HookOrder, ToolParameterInfo, ToolParamType
from pydantic import field_validator

from .emoji_map.qq_emoji_resolver import MAX_EMOJI_ID, QQEmoji, QQEmojiResolver, parse_emoji_id
from .emoji_reaction_replacer import EmojiReactionReplacer, PigReactState
from .notice_translator import EmojiLikeNoticeParser, sanitize_user_text

# ==================== 常量 ====================

# 配置版本：与 _manifest.json 的 version 保持同步。
# MaiBot 1.2.3+ 强制要求插件配置提供 plugin.config_version（runner_main.py
# extract_plugin_config_version），缺失会导致插件初始化失败。
SUPPORTED_CONFIG_VERSION = "0.4.1"

# 「群友是🐷」自动贴表情的默认和兜底 ID（祝(猪)）。
DEFAULT_EMOJI_ID = 12951

# 事件文本前缀：
# - 常规事件（LLM 工具调用贴表情 / 群友贴表情通知翻译）：
EVENT_TAG_NORMAL = "[事件-群消息表情回应]"
# - 插件概率自动触发事件（「群友是🐷」概率自动贴表情，非 bot 调用工具）：
#   聊天中用户未直接提及该行为时 LLM 应忽视该信息；若用户提及则回应为「随手贴的」。
EVENT_TAG_PROBABILISTIC = "[事件-插件概率事件（聊天中用户未直接提及该行为则忽视该信息，如果提及该行为则回应为随手贴的）]"

# 官方适配器的通用 action 入口（NapCat 兼容命名，合并版 SnowLuma 适配器同样提供）。
# 用它直接下发 set_msg_emoji_like 动作，可传负 message_id（QQ 消息 ID 为带符号 int32）。
# 合并版适配器（1.0+）的专用 set_msg_emoji_like API 已原生接受负 ID，但 action.call
# 仍是新旧适配器（1.2.x 旧版 NapCat 适配器的专用 API 校验正整数）共用的稳妥通道。
NAPCAT_ACTION_CALL_API = "adapter.napcat.action.call"
REACTION_NOTICE_GATEWAY = "emoji_reaction_reporter"


def _ui_field(label: str, hint: str, en_label: str, en_hint: str) -> Dict[str, Any]:
    """生成字段标签、提示及显式的中英文翻译。"""
    return {
        "label": label,
        "hint": hint,
        "i18n": {
            "zh-CN": {"label": label, "hint": hint},
            "en": {"label": en_label, "hint": en_hint},
        },
    }


# ==================== 配置模型 ====================


class EmojiLikeConfig(PluginConfigBase):
    """表情（emoji 配置节）：表情展示与未知表情显示方式。"""

    __ui_label__ = "表情"
    __ui_i18n__: ClassVar[Dict[str, Dict[str, str]]] = {
        "zh-CN": {"title": "表情", "description": "表情展示与未知表情显示方式。"},
        "en": {"title": "Emoji Display", "description": "Emoji display and unknown-emoji rendering."}
    }
    __ui_icon__ = "sentiment_satisfied"
    __ui_order__ = 1

    optimize_unknown_emoji: bool = Field(
        default=False,
        description="优化未知表情信息：开启后未知表情显示为「一个表情」（如「表达了 一个表情」）；关闭时显示「未知表情<id>」（与 snowluma 一致，默认关闭）",
        json_schema_extra=_ui_field(
            "优化未知表情显示", "未知表情显示优化",
            "Optimize unknown emoji display", "Show unknown emoji as 'an emoji'",
        ),
    )


class EmojiReactionConfig(PluginConfigBase):
    """贴表情工具的检索、频控和通知补录配置。"""

    __ui_label__ = "贴表情工具"
    __ui_i18n__: ClassVar[Dict[str, Dict[str, str]]] = {
        "zh-CN": {"title": "贴表情工具", "description": "表情检索、贴表情冷却与通知补录。"},
        "en": {"title": "Emoji Reaction Tool", "description": "Emoji search, reaction cooldown and notices."}
    }
    __ui_icon__ = "swap_horiz"
    __ui_order__ = 2

    search_result_limit: int = Field(
        default=5,
        ge=1,
        description="每次关键词检索最多返回的表情数。命中更多时随机抽取。",
        json_schema_extra=_ui_field(
            "检索结果上限", "命中超出上限时随机抽取",
            "Search result limit", "Randomly sample results when the limit is exceeded",
        ),
    )

    featured_emoji_mode: Literal["不使用", "使用", "始终启用"] = Field(
        default="使用",
        description="不使用：不附精选表情。使用：仅在关键词查询无结果时附上精选表情。始终启用：每次关键词查询都附上精选表情。",
        json_schema_extra=_ui_field(
            "精选表情模式", "默认仅在查询无结果时附上精选表情",
            "Featured emoji mode", "By default, show featured emoji only when there are no matches",
        ),
    )

    featured_emoji_ids: list[int] = Field(
        default_factory=lambda: [424, 478, 479, 12951],
        description="按顺序列出精选表情的 ID。请填写映射表内已收录的 ID，留空时没有精选候选。",
        json_schema_extra=_ui_field(
            "精选表情 ID", "按填写顺序向 Bot 推荐精选表情",
            "Featured emoji IDs", "Shown to the bot in the configured order",
        ),
    )

    description_library: list[str] = Field(
        default_factory=list,
        description="可选的旧配置描述覆盖，每行一条「表情 ID: 描述」。留空使用映射表。",
        json_schema_extra=_ui_field(
            "自定义描述覆盖", "留空使用映射表",
            "Description overrides", "Leave empty to use the emoji maps",
        ),
    )

    tool_cooldown_seconds: float = Field(
        default=10.0,
        description="每个会话实际贴表情的最小间隔（默认 10 秒，0 = 不限频），查询不占冷却",
        json_schema_extra=_ui_field(
            "贴表情工具冷却（秒）", "每会话最小调用间隔",
            "Reaction cooldown (seconds)", "Minimum interval between reactions in a chat",
        ),
    )

    record_reaction_notice: bool = Field(
        default=False,
        description=(
            "把机器人贴表情的动作补录到 WebUI 聊天记录。关闭后注销补录网关，实际贴表情、"
            "群友表情通知翻译和 Planner 上下文仍可使用。"
        ),
        json_schema_extra=_ui_field(
            "补录表情通知",
            "关闭后注销 QQ 补录网关",
            "Record reaction notices",
            "Turn off to unregister the QQ recording gateway",
        ),
    )

    @field_validator("description_library", mode="before")
    @classmethod
    def _coerce_description_library(cls, value: Any) -> Any:
        """兼容旧配置格式：str JSON / dict → list[str]（每行 `id: 描述`）。"""
        if isinstance(value, str):
            if not value.strip():
                return []
            try:
                value = json.loads(value)
            except ValueError:
                return value
        if isinstance(value, Mapping):
            return [f"{k}: {v}" for k, v in value.items()]
        return value


class PigFriendsConfig(PluginConfigBase):
    """群友是🐷（pig_friends 配置节）：自动贴表情的开关、名单与概率。"""

    __ui_label__ = "群友是🐷"
    __ui_i18n__: ClassVar[Dict[str, Dict[str, str]]] = {
        "zh-CN": {"title": "群友是🐷", "description": "自动贴表情开关、名单与概率。"},
        "en": {"title": "Pig Friends", "description": "Auto-reaction switch, lists and probability."}
    }
    __ui_icon__ = "pets"
    __ui_order__ = 3

    enabled: bool = Field(
        default=False,
        description="总开关：启用「群友是🐷」自动贴表情功能",
        json_schema_extra=_ui_field(
            "启用自动贴表情", "自动贴表情总开关",
            "Enable auto reaction", "Master switch for auto reaction",
        ),
    )
    auto_emoji_id: int = Field(
        default=DEFAULT_EMOJI_ID,
        description=(
            "自动贴的表情 ID（默认 12951，祝(猪)）：普通用户概率命中与🐷用户冷却触发时，"
            "都对目标消息贴这个表情。需为 0 ~ 2147483647 的整数，非法/越界值回退默认 12951"
        ),
        json_schema_extra=_ui_field(
            "自动贴表情 ID", "自动贴表情使用的表情 ID",
            "Auto reaction emoji ID", "Emoji ID used for auto reactions",
        ),
    )
    group_list_mode: str = Field(
        default="whitelist",
        description="群名单模式：whitelist=仅以下群生效；blacklist=以下群不生效",
        json_schema_extra=_ui_field("群名单模式", "群名单模式", "Group list mode", "whitelist or blacklist"),
    )
    group_list: list[str] = Field(
        default_factory=list,
        description="群名单（填群号；按 group_list_mode 决定白/黑名单）",
        json_schema_extra=_ui_field("群名单", "群号名单，留空全群", "Group list", "Group IDs; empty means all groups"),
    )
    user_list_mode: str = Field(
        default="blacklist",
        description="用户名单模式：whitelist=仅以下用户生效；blacklist=以下用户不生效",
        json_schema_extra=_ui_field("用户名单模式", "用户名单模式", "User list mode", "whitelist or blacklist"),
    )
    user_list: list[str] = Field(
        default_factory=list,
        description="用户名单（填 QQ 号；按 user_list_mode 决定白/黑名单）",
        json_schema_extra=_ui_field("用户名单", "QQ 号名单", "User list", "QQ IDs"),
    )
    normal_probability: float = Field(
        default=0.05,
        description="普通用户每次发消息自动贴表情（ID 见「自动贴表情 ID」）的概率（0~1，默认 0.05）",
        json_schema_extra=_ui_field(
            "普通用户触发概率", "普通用户贴表情概率",
            "Normal user probability", "Chance per message for normal users",
        ),
    )
    normal_cooldown_seconds: int = Field(
        default=600,
        description="普通用户贴表情后的冷却秒数（默认 600 秒；0 = 禁用冷却）",
        json_schema_extra=_ui_field(
            "普通用户冷却（秒）", "普通用户冷却时长",
            "Normal user cooldown (seconds)", "0 disables cooldown",
        ),
    )
    pig_users: list[str] = Field(
        default_factory=list,
        description="你是那么大个🐷：这些 QQ 号不看黑白名单，每次发消息且冷却过即贴表情（ID 见「自动贴表情 ID」）",
        json_schema_extra=_ui_field("🐷用户名单", "🐷用户不受名单限制", "Pig user list", "Pig users bypass list checks"),
    )
    pig_cooldown_seconds: int = Field(
        default=1800,
        description="🐷用户冷却秒数（默认 1800 = 30 分钟，每个 QQ 独立；0 = 禁用冷却）",
        json_schema_extra=_ui_field(
            "🐷用户冷却（秒）", "🐷用户独立冷却时长",
            "Pig user cooldown (seconds)", "Independent per QQ; 0 disables",
        ),
    )
    pig_chain_skip_cooldown_probability: float = Field(
        default=0.25,
        description="🐷用户每次贴后不进冷却的概率（默认 0.25；命中则下一条消息直接贴）",
        json_schema_extra=_ui_field(
            "免冷却连贴概率", "免冷却连贴概率",
            "No-cooldown chain probability", "Chance to skip cooldown after reacting",
        ),
    )
    pig_max_chain: int = Field(
        default=3,
        description="🐷用户最多连贴的不同消息数（默认 3，第 3 个贴完停止本轮连贴）",
        json_schema_extra=_ui_field("最大连贴条数", "一轮最多连贴条数", "Max chain count", "Max distinct messages per chain"),
    )


class PluginSectionConfig(PluginConfigBase):
    """插件（plugin 配置节）：插件级开关与配置版本。"""

    __ui_label__ = "插件"
    __ui_i18n__: ClassVar[Dict[str, Dict[str, str]]] = {
        "zh-CN": {"title": "插件", "description": "插件总开关与配置版本。"},
        "en": {"title": "Plugin", "description": "Plugin-level switch and config version."}
    }
    __ui_icon__ = "package"
    __ui_order__ = 0

    enabled: bool = Field(
        default=True,
        description="是否启用插件",
        json_schema_extra=_ui_field("启用插件", "插件总开关", "Enable plugin", "Master switch for the plugin."),
    )
    config_version: str = Field(
        default=SUPPORTED_CONFIG_VERSION,
        description="配置版本（与插件版本同步，用于检查配置文件是否需要更新）",
        json_schema_extra={
            "disabled": True,
            "hidden": True,
            **_ui_field("配置版本", "配置版本，勿改", "Config version", "Config version, do not edit."),
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
        self._emoji_resolver = QQEmojiResolver()
        self._notice_parser = EmojiLikeNoticeParser(emoji_resolver=self._emoji_resolver)
        self._replacer = EmojiReactionReplacer()
        self._pig_state = PigReactState()  # 「群友是🐷」冷却与连贴状态
        self._pig_state_last_cleanup = 0.0  # 上次冷却状态清理时间（每小时低频清理一次）
        self._bot_nickname_cache: Dict[str, Any] = {"value": "", "expires": 0.0}  # 机器人昵称缓存

        self._notice_gateway_lock = asyncio.Lock()
        self._notice_gateway_route: tuple[str, str] | None = None
        self._notice_gateway_state_unknown = False
        self._loaded = False

    # ==================== MessageGateway：注入合成通知 ====================

    @MessageGateway(
        "receive",
        name=REACTION_NOTICE_GATEWAY,
        description="注入贴表情合成通知消息（走完整入站链，入库显示在 WebUI）",
        platform="qq",
    )
    async def gateway_emoji_reaction_reporter(self, **kwargs: Any) -> Any:
        """接收网关声明：本插件通过此网关 route_message 注入合成通知消息。

        网关方法本身不需要处理外部消息（仅作组件载体），route_message 由工具调用。
        """
        del kwargs
        return None

    # ==================== Tool：查询或贴表情 ====================

    @Tool(
        "emoji_like",
        brief_description="按中文情绪或描述查询 QQ 表情，按数字 ID 贴表情",
        description=(
            "对聊天消息贴 QQ 表情回应，可作为 send_emoji 的轻量替代。"
            "如果只知道想表达的情绪，先把简短的中文词传入 emoji（如「开心」「无奈」「赞同」）。"
            "工具会返回匹配表情的 ID、名称和描述，并可能附上精选表情。"
            "选好后，将返回的数字 ID 再传给本工具即可贴表情。"
            "如果已经知道有效的数字 ID，可以直接贴。遇到无效 ID 时改用关键词查询。"
            "贴表情默认使用最近一条非机器人消息。"
        ),
        parameters=[
            ToolParameterInfo(
                name="emoji",
                param_type=ToolParamType.STRING,
                description="数字 ID（如「76」）用于贴表情，中文关键词（如「赞同」）用于查询表情。",
                required=True,
            ),
            ToolParameterInfo(
                name="target_message_id",
                param_type=ToolParamType.STRING,
                description="贴表情的目标消息 ID。省略时使用最近一条非机器人消息。",
                required=False,
            ),
        ],
    )
    async def tool_emoji_like(self, **kwargs: Any) -> Dict[str, Any]:
        """用关键词查询表情，或按已收录的 ID 贴表情。"""
        raw_emoji = kwargs.get("emoji")
        query = normalize("NFKC", str(raw_emoji)).strip() if raw_emoji is not None else ""
        if not query:
            return self._tool_error("请传入中文情绪词查询表情，或传入已知的数字 ID 贴表情。")
        if not query.lstrip("+-").isdecimal():
            return self._search_emoji(query)

        emoji_id = parse_emoji_id(query)
        if emoji_id is None or self._emoji_resolver.get(emoji_id) is None:
            return self._tool_error(
                f"表情 ID {sanitize_user_text(query)} 无效或未收录。"
                "请用中文情绪词查询表情，再传入查询返回的 ID。"
            )

        stream_id = str(kwargs.get("stream_id") or "").strip()
        if not stream_id:
            return self._tool_error("缺少会话信息，无法贴表情。")

        target_message_id = str(kwargs.get("target_message_id") or "").strip()
        if not target_message_id:
            target_message_id = await self._find_recent_user_message(stream_id)
        if not target_message_id:
            return self._tool_error("未找到可贴表情的目标消息（最近没有非机器人消息）。")

        # 只对实际贴表情的分支限频，检索和无效 ID 不占冷却。
        try:
            tool_cooldown = float(self.config.emoji_reaction.tool_cooldown_seconds)
        except (TypeError, ValueError):
            tool_cooldown = 10.0
        if tool_cooldown < 0:
            tool_cooldown = 10.0
        if tool_cooldown > 0 and not self._pig_state.tool_try_take(stream_id, time.time(), tool_cooldown):
            return self._tool_error("贴表情太频繁，请稍等片刻后再试。")

        ok, error = await self._apply_emoji_like(stream_id, target_message_id, emoji_id)
        if not ok:
            return self._tool_error(error)

        await self._record_and_context(stream_id, target_message_id, emoji_id)
        emoji_name = self._emoji_resolver.resolve(emoji_id)
        desc = self._emoji_description(emoji_id)
        content = f"已对消息(ID:{target_message_id})贴了表情：{emoji_name}(ID:{emoji_id})，{desc}"
        return {
            "success": True,
            "content": content,
            "message": content,
            "emoji_id": emoji_id,
            "emoji_name": emoji_name,
            "target_message_id": target_message_id,
        }

    def _search_emoji(self, query: str) -> Dict[str, Any]:
        config = self.config.emoji_reaction
        matches = self._emoji_resolver.search(query)
        count = len(matches)
        if count > config.search_result_limit:
            matches = random.sample(matches, config.search_result_limit)
        emoji_list = self._emoji_candidates(matches)
        featured_emoji_list: list[Dict[str, str]] = []
        if config.featured_emoji_mode == "始终启用" or (config.featured_emoji_mode == "使用" and not count):
            featured_emoji_list = self._emoji_candidates(
                emoji for emoji_id in dict.fromkeys(config.featured_emoji_ids)
                if (emoji := self._emoji_resolver.get(emoji_id)) is not None
            )

        label = sanitize_user_text(query)
        if emoji_list:
            lines = [f"「{label}」匹配 {count} 个表情，返回 {len(emoji_list)} 个。"]
            lines.extend(self._emoji_candidate_lines(emoji_list))
        else:
            lines = [f"没有找到包含「{label}」的表情。"]

        if emoji_list or featured_emoji_list:
            lines.append("选好后，把对应数字 ID 传入 emoji_like 的 emoji 参数即可贴表情。")
        else:
            lines.append("请换一个简短的情绪词查询。")
        if featured_emoji_list:
            lines.extend(("", "以下是精选表情，可按当前语境选择。"))
            lines.extend(self._emoji_candidate_lines(featured_emoji_list))

        content = "\n".join(lines)
        return {
            "success": True,
            "emoji_list": emoji_list,
            "matched_count": count,
            "featured_emoji_list": featured_emoji_list,
            "content": content,
            "message": content,
        }

    @staticmethod
    def _emoji_candidates(emojis: Iterable[QQEmoji]) -> list[Dict[str, str]]:
        return [
            {"emoji_id": emoji.emoji_id, "emoji_name": emoji.name, "description": emoji.description or emoji.name}
            for emoji in emojis
        ]

    @staticmethod
    def _emoji_candidate_lines(items: list[Dict[str, str]]) -> Iterable[str]:
        for item in items:
            yield f"- ID {item['emoji_id']} {item['emoji_name']}：{item['description']}"

    @staticmethod
    def _tool_error(text: str) -> Dict[str, Any]:
        return {"success": False, "error": text, "content": text}

    # ==================== 贴表情辅助 ====================

    def _get_description_overrides(self) -> Dict[str, str]:
        """读取旧配置中自定义的 ID 与描述。"""
        descriptions = {}
        for line in self.config.emoji_reaction.description_library:
            emoji_id, _, description = line.partition(":")
            if emoji_id.strip() and description.strip():
                descriptions[emoji_id.strip()] = description.strip()
        return descriptions

    def _validated_config_emoji_id(self, raw_value: Any, config_name: str) -> int:
        """校验配置的表情 ID（非负 int32）；非法/越界回退硬兜底 DEFAULT_EMOJI_ID 并告警。"""
        emoji_id = parse_emoji_id(raw_value)
        if emoji_id is None:
            self.ctx.logger.warning(
                "配置 %s=%r 无效（需为 0 ~ %d 的整数），回退默认表情 %d",
                config_name, raw_value, MAX_EMOJI_ID, DEFAULT_EMOJI_ID,
            )
            return DEFAULT_EMOJI_ID
        return emoji_id

    def _get_pig_auto_emoji_id(self) -> int:
        """「群友是🐷」自动贴表情 ID（配置 pig_friends.auto_emoji_id）。"""
        try:
            return self._validated_config_emoji_id(
                self.config.pig_friends.auto_emoji_id, "pig_friends.auto_emoji_id"
            )
        except Exception:
            return DEFAULT_EMOJI_ID

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
            # 跳过合成通知：is_notify 消息（适配器注入的 qq-notice-* 通知等）以群友身份入库，
            # filter_mai 拦不住；message_id 非数字（qq-notice-*、emoji-reaction-notice-*）
            # 的都不是真实 QQ 消息，不能作为贴表情目标。
            if bool(msg.get("is_notify", False)):
                continue
            mid = str(msg.get("message_id") or "").strip()
            if mid and EmojiReactionReplacer.parse_reactable_message_id(mid) is not None:
                return mid
        return ""

    async def _apply_emoji_like(self, stream_id: str, message_id: str, emoji_id: int) -> tuple[bool, str]:
        """调用 NapCat 通用 action 入口贴表情。返回 (ok, error)。"""
        if not str(stream_id or "").strip():
            # 无会话 ID：api.call 或许能发出，但后续记录注入必然失败——统一提前拒绝
            return False, "缺少会话信息，无法贴表情"
        emoji_id_num = parse_emoji_id(emoji_id)
        if emoji_id_num is None:
            # 表情 ID 必须是非负 int32，越界 ID 不透传给协议端（防无效调用）
            return False, "表情 ID 无效或超出有效范围，请用 emoji_like 按关键词查询表情"
        emoji_id = emoji_id_num
        if EmojiReactionReplacer.parse_reactable_message_id(message_id) is None:
            # 合成通知（如适配器注入的 qq-notice-*、本插件的 emoji-reaction-notice-*）不是真实 QQ 消息，
            # 协议端无从贴表情：返回 LLM 可读的失败原因，而不是 int() 异常原文。
            return False, (
                f"目标消息(ID:{message_id})是系统通知或合成记录，不是真实QQ消息，无法贴表情；"
                "请改为对普通聊天消息贴表情（target_message_id 留空即可自动定位最近的真实消息）"
            )
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
        entry = self._emoji_resolver.get(emoji_id)
        return (entry.description or entry.name) if entry else f"表情 {emoji_id}"

    async def _record_and_context(
        self, stream_id: str, message_id: str, emoji_id: int, *, event_tag: str = EVENT_TAG_NORMAL
    ) -> None:
        """把贴表情行为记录到聊天流（WebUI 可见）+ 注入 Planner 上下文。

        方式：构造 is_notify=True 合成通知消息 → ctx.gateway.route_message 注入
        → 走完整入站链（heartflow process_message 自动写 DB）→ WebUI 可见、
        进聊天流，且不真发到群里（参照智能戳戳插件机器人自戳通知的入库机制）。

        event_tag: 事件文本前缀。默认「[事件-群消息表情回应]」；
            插件概率自动触发（「群友是🐷」）时传 EVENT_TAG_PROBABILISTIC，
            提示 LLM 这是概率事件：用户未直接提及则忽视，提及则回应为随手贴的。
        """
        desc = self._emoji_description(emoji_id)
        # 反查流信息（self_id、群、昵称）——身份字段缺失时放弃注入，避免脏数据
        stream_info = await self._fetch_stream_info(stream_id)
        # 期望结构：`{event_tag} {bot名} 对消息(ID:X)贴了表情：{描述}`
        bot_name = str(stream_info.get("bot_nickname") or stream_info.get("self_id") or "").strip() or "机器人"
        record_text = f"{event_tag} {bot_name} 对消息(ID:{message_id})贴了表情：{desc}"
        if self.config.emoji_reaction.record_reaction_notice:
            await self._record_reaction_notice(stream_id, message_id, emoji_id, stream_info, record_text)

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

    async def _record_reaction_notice(
        self, stream_id: str, message_id: str, emoji_id: int, stream_info: Dict[str, Any], record_text: str
    ) -> None:
        async with self._notice_gateway_lock:
            if not (self._loaded and self.config.emoji_reaction.record_reaction_notice):
                return
            # 私聊以入站作者决定会话，机器人作为作者的通知只适合注入原群聊。
            if stream_info.get("platform") != "qq" or not stream_info.get("group_info", {}).get("group_id"):
                return
            account_id = str(stream_info.get("self_id") or "").strip()
            if not account_id:
                self.ctx.logger.warning(
                    "贴表情记录缺少机器人账号，跳过补录（stream=%s）", stream_id
                )
                return

            scope = str(stream_info.get("scope") or "").strip()
            try:
                # 宿主要求消息与接收网关声明的账号和作用域一致。
                await self._set_notice_gateway((account_id, scope))
                if not self._loaded or not self.config.emoji_reaction.record_reaction_notice:
                    return
                notice_message = self._replacer.build_inject_notice_message(
                    stream_info=stream_info,
                    record_text=record_text,
                    extra_payload={"target_message_id": message_id, "emoji_id": str(emoji_id)},
                )
                notice_message["account_id"] = account_id
                notice_message["scope"] = scope or None
                accepted = await self.ctx.gateway.route_message(
                    REACTION_NOTICE_GATEWAY,
                    notice_message,
                    external_message_id=str(notice_message.get("message_id") or ""),
                    # dedupe_key 附带分钟级时间片：同一条消息第二次贴同款表情
                    # （合法重复）不会被旧键去重吞掉记录注入
                    dedupe_key=(
                        f"emoji-reaction-{stream_id}-{message_id}-{emoji_id}-"
                        f"{int(time.time() // 60)}"
                    ),
                )
                if accepted:
                    self.ctx.logger.info("贴表情记录已注入聊天流：%s", record_text)
                else:
                    self.ctx.logger.warning("贴表情记录注入被拒绝（stream=%s）", stream_id)
            except Exception as exc:
                self.ctx.logger.warning("注入贴表情聊天记录失败（stream=%s）：%s", stream_id, exc)

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
                    account_id = str(msg.get("account_id") or "").strip()
                    if account_id:
                        scope = msg.get("scope")
                    else:
                        account_id = str(additional.get("platform_io_account_id") or additional.get("self_id") or "").strip()
                        scope = additional.get("platform_io_scope") or additional.get("route_scope")
                    if account_id:
                        stream_info.update(
                            platform=str(msg.get("platform") or "qq").strip().lower(),
                            self_id=account_id,
                            scope=str(scope or "").strip(),
                            group_info=group_info,
                        )
                        break
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
        description="用户发消息时按概率/规则自动贴表情（群友是🐷，表情 ID 见 pig_friends.auto_emoji_id）",
        mode=HookMode.BLOCKING,
        order=HookOrder.EARLY,
        error_policy=ErrorPolicy.SKIP,
    )
    async def hook_pig_friends_listener(self, message: Optional[Mapping[str, Any]] = None, **kwargs: Any) -> Dict[str, Any]:
        """拦截用户入站消息，判定是否自动贴表情。

        流程：总开关 → 猪友判定 →（仅普通用户）群名单 → 用户名单 → 冷却 → 贴表情。
        - 🐷用户：无视黑白名单、不看概率，冷却过即贴（独立冷却，连贴链）；
        - 普通用户：先过群/用户名单，再按概率贴 1 个 → 默认 600s 冷却（0 = 禁用冷却）。
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
        if not stream_id:
            # 无会话 ID：贴表情与记录注入都无法进行，直接跳过
            return

        cfg = self.config.pig_friends
        now = time.time()

        # 低频清理过期冷却状态（每小时一次），防止长期运行内存缓慢增长
        if now - self._pig_state_last_cleanup > 3600.0:
            self._pig_state_last_cleanup = now
            self._pig_state.cleanup(now)

        pig_qqs = {str(x).strip() for x in (cfg.pig_users or []) if str(x).strip()}
        is_pig = user_id in pig_qqs

        # 猪友无视黑白名单：命中猪友名单即跳过群/用户名单检查直接走猪友分支；
        # 仅普通用户路径需要先过两级名单
        if not is_pig:
            # 群名单（先验证群号；私聊 group_id 空 → 无群校验，直接过）
            if group_id:
                if not EmojiReactionReplacer.is_allowed_by_list(group_id, cfg.group_list, cfg.group_list_mode):
                    return
            # 用户名单（后验证 QQ 号）
            if not EmojiReactionReplacer.is_allowed_by_list(user_id, cfg.user_list, cfg.user_list_mode):
                return

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
        # 显式校验：非法/负值回退默认 600s；0 = 禁用冷却（命中概率即贴）
        try:
            cooldown = int(cfg.normal_cooldown_seconds)
        except (TypeError, ValueError):
            cooldown = 600
        if cooldown < 0:
            cooldown = 600
        # 全局冷却判定 + 占坑（所有普通用户共享，原子）
        if not self._pig_state.normal_try_take(now, cooldown):
            return
        await self._do_pig_stick(stream_id, target_message_id, user_id)

    async def _pig_react(
        self, user_id: str, target_message_id: str, stream_id: str, cfg: Any, now: float,
    ) -> None:
        """🐷用户：冷却过即贴；贴后 0.25 概率免冷却连贴（最多 max_chain 条）。

        连贴链：0.25 命中 → pig_chain_advance 进入链（清除冷却）→ 下一条消息
        触发时 pig_chain_active 判定 → 直接贴（不再判冷却/概率）→ 贴后再次 0.25
        判定是否继续链；链计数达 max_chain 时退出链（恢复正常冷却流程）。
        """
        # 显式校验：非法/负值回退默认 1800s；0 = 禁用冷却
        try:
            cooldown = int(cfg.pig_cooldown_seconds)
        except (TypeError, ValueError):
            cooldown = 1800
        if cooldown < 0:
            cooldown = 1800
        chain_max = max(1, int(cfg.pig_max_chain or 3))
        skip_prob = max(0.0, min(1.0, float(cfg.pig_chain_skip_cooldown_probability or 0.25)))

        # 冷却判定 + 占坑（链内 pig_try_take 直接 True）
        if not self._pig_state.pig_try_take(user_id, now, cooldown):
            return

        # 贴当前消息
        await self._do_pig_stick(stream_id, target_message_id, user_id)

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

    async def _do_pig_stick(self, stream_id: str, target_message_id: str, user_id: str) -> None:
        """贴自动表情（pig_friends.auto_emoji_id；标准流程：贴表情 + 记录 + 上下文）。"""
        emoji_id = self._get_pig_auto_emoji_id()
        ok, err = await self._apply_emoji_like(stream_id, target_message_id, emoji_id)
        if not ok:
            self.ctx.logger.warning("群友是🐷贴表情失败（user=%s msg=%s）：%s", user_id, target_message_id, err)
            return
        self.ctx.logger.info("群友是🐷：对用户 %s 的消息 %s 贴了 %d", user_id, target_message_id, emoji_id)
        # 概率自动触发（非 bot 调用工具）：记录带「插件概率事件」标签，
        # 提示 LLM 用户未直接提及该行为则忽视，提及则回应为随手贴的
        await self._record_and_context(
            stream_id, target_message_id, emoji_id, event_tag=EVENT_TAG_PROBABILISTIC
        )

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
        - 非表情回应通知原样返回，不拦截；
        - **机器人自己发起的表情回应通知跳过**：机器人贴表情后，QQ/NapCat 会回推一条
          「机器人贴了表情」的通知，而本插件在贴表情成功时已主动注入一条记录
          （_record_and_context），若再翻译这条通知会重复入库两条。因此这里识别
          actor_user_id == self_id 的通知并跳过（群友的照常翻译）。
        """
        message = kwargs.get("message")
        if not isinstance(message, Mapping):
            return {"action": "continue", "modified_kwargs": kwargs}

        parsed = self._notice_parser.parse(message)
        if parsed is None:
            return {"action": "continue", "modified_kwargs": kwargs}

        # 跳过机器人自己发起的表情回应通知（避免与主动注入记录重复）
        try:
            message_info = message.get("message_info") if isinstance(message.get("message_info"), Mapping) else {}
            additional = message_info.get("additional_config") if isinstance(message_info.get("additional_config"), Mapping) else {}
            self_id = str(additional.get("self_id") or additional.get("platform_io_account_id") or "").strip()
            actor_user_id = str(parsed.get("actor_user_id") or "").strip()
            if self_id and actor_user_id == self_id:
                self.ctx.logger.info(
                    "跳过机器人自己发起的表情回应通知（self_id=%s，避免与主动记录重复）", self_id
                )
                return {"action": "abort"}
        except Exception:
            pass

        notice_text = parsed["summary"] if parsed.get("summary") else None
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

        Runner 在配置注入时已按默认值自动补齐
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
        """同步通知设置与旧配置中的自定义描述。"""
        self._notice_parser.optimize_unknown = self.config.emoji.optimize_unknown_emoji
        self._emoji_resolver.set_description_overrides(self._get_description_overrides())

    # ==================== 生命周期 ====================

    async def _set_notice_gateway(self, route: tuple[str, str] | None) -> None:
        if self._notice_gateway_route == route and not self._notice_gateway_state_unknown:
            return

        # RPC 可能在宿主已应用后断开。仅用宿主确认更新本地状态。
        self._notice_gateway_state_unknown = True
        account_id, scope = route or ("", "")
        accepted = await self.ctx.gateway.update_state(
            REACTION_NOTICE_GATEWAY,
            ready=route is not None,
            platform="qq",
            account_id=account_id,
            scope=scope,
        )
        if not accepted:
            raise RuntimeError("宿主未确认表情补录网关状态")
        self._notice_gateway_route = route
        self._notice_gateway_state_unknown = False

    async def _sync_notice_gateway(self) -> None:
        async with self._notice_gateway_lock:
            if self._loaded and self.config.emoji_reaction.record_reaction_notice:
                route = self._notice_gateway_route or ("", "")
                try:
                    await self._set_notice_gateway(route)
                except Exception as exc:
                    self.ctx.logger.warning("启用表情补录网关失败：%s", exc)
            else:
                try:
                    await self._set_notice_gateway(None)
                except Exception as exc:
                    raise RuntimeError("未能注销表情补录网关") from exc

    async def on_load(self) -> None:
        self._check_config_version()
        self._sync_notice_config()
        self._loaded = True
        await self._sync_notice_gateway()
        self.ctx.logger.info("表情回应插件已加载")

    async def on_unload(self) -> None:
        self._loaded = False
        await self._sync_notice_gateway()
        self.ctx.logger.info("表情回应插件已卸载")

    async def on_config_update(self, scope: str, config_data: Dict[str, Any], version: str) -> None:
        del config_data, version
        if scope == "self":
            self._check_config_version()
            self._sync_notice_config()
            await self._sync_notice_gateway()
            self.ctx.logger.info("表情回应插件配置已更新")


def create_plugin() -> CateyeSetMsgEmojiLikePlugin:
    return CateyeSetMsgEmojiLikePlugin()
