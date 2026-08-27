# 更新日志

## 0.2.0（2026-08-27）

- 新增 LLM 工具 `emoji_like_list`：查询当前配置的可用贴表情列表（表情 ID + 表情名 + 描述），供 LLM 在调用 `emoji_like` 前确认可用表情与对应 ID。
- `emoji_like` 工具描述强化引导：调用前必须先调用 `emoji_like_list` 确认表情 ID，把 ID（数字）传入 `emoji` 参数，不要凭印象编造表情表达。
- 新增配置项 `emoji_reaction.allow_fallback_to_default`（默认开启）：LLM 传入的描述库外表达（如「开心」「俏皮」等情绪词）或无效表情时，自动回退到默认表情 12951，不再返回「未识别的表情表达」错误。关闭后保持旧行为（返回失败）。
- 默认描述库扩充：从内置映射表（emoji_map/）挑选代表性经典表情（12951 祝(猪)、14 微笑、21 可爱、46 猪头、66 爱心、76 赞、174 无奈、182 笑哭、271 吃瓜、319 比心、357 裂开），覆盖常见情绪/互动场景，供 LLM 选择。
- 12951 名称映射改为「祝(猪)」（emoji_reaction_extra.json 覆盖 merged 表），与 QQ 客户端实际显示名一致。
- 说明：MaiBot 插件 SDK 无「强制链式工具调用」机制（`@Tool` 为静态声明、`ctx.tool` 仅只读查询），因此采用「新查询工具 + 描述引导 + 失败回退」组合方案。
- 修复：`emoji_like_list` 返回的 dict 现在包含 `content` 字段（MaiBot Tool 规范中给 LLM 阅读的纯文本），逐行列出每个表情的 `emoji_id`（数字）+ 名称 + 描述；此前 LLM 只能看到"有 11 个表情"但看不到具体 ID（结构化字段 `emoji_list` 对 LLM 不可见）。`emoji_like` 成功/失败返回也补上 `content`，未识别时明确引导先查 `emoji_like_list`、不要盲试。

## 0.1.0（2026-08-27）

- 首个版本。
- 功能：
  - LLM 工具 `emoji_like`：对聊天消息贴 QQ 表情回应（reaction），可作为 `send_emoji` 表达情绪的替代/补充；支持描述库选表情或直接给表情 ID；未指定目标时自动定位最近一条非机器人消息。
  - 贴表情动作入库：通过 MessageGateway 注入 `[事件-群消息表情回应] 机器人名 对消息(ID:xxx)贴了表情：描述` 合成通知，WebUI 可见、不真发、不触发 LLM 回复。
  - 表情回应通知翻译：拦截 NapCat `group_msg_emoji_like` 通知，翻译为「谁 对哪条消息 贴了 什么表情」注入框架；表情名来自多源合并映射表（QQ 官方 / NapCat / SnowLuma / JSON 自定义扩展）。
  - 描述库命中时显示 `表达了 表情名：具体描述`（如 `表达了 玫瑰：鲜花`）；描述库支持 `emoji_id: 描述` 列表格式，并兼容旧版 JSON 字符串/字典配置。
  - 群友是🐷：用户发消息自动贴表情（默认关闭），支持群/用户黑白名单、普通用户概率+全局冷却、猪友独立冷却+免冷却连贴链（最多 `pig_max_chain` 条）。
  - 消息 ID 兼容带符号 int32（负 ID 合法），通过 NapCat 适配器通用 action 入口 `adapter.napcat.action.call` 下发 `set_msg_emoji_like` 动作，未修改官方适配器代码。
  - 机器人昵称通过 NapCat `get_login_info` 查询（缓存 1 小时），注入记录正确显示机器人名（避免群友名错配）。
- 修复：
  - 表情解析器改用相对导入，避免 runner 加载插件时 sys.path 不含插件目录导致绝对导入失败、所有表情退化为「一个表情」。
  - 描述库命中时显示表情名 + 描述（此前统一显示「一个表情：描述」）。

## 0.1.0（2026-08-27 · 修订，来自 maisakagithub 的建议）

- **依赖声明**：`_manifest.json` 在 `dependencies` 中声明插件级硬依赖 `maibot-team.napcat-adapter`（`>=1.0.0`），与 README/manifest 描述中的依赖说明一致；缺失时由 Host 依赖流水线阻止加载，README 安装说明同步更新。
- **通知文本安全**：表情回应通知翻译在拼入 `processed_plain_text` / `raw_message` 前对昵称等用户可控文本清理控制字符（含换行/回车）、压缩空白并限长（昵称 ≤64 字符），防止恶意昵称注入提示词。
