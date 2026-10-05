# 更新日志

## 0.3.1（2026-09-29）

**安全与规范审查修复版：行为一致性 + 健壮性打磨，无新功能。**

- **行为变更：「群友是🐷」猪友现在真正无视黑白名单**。此前实现中群/用户名单过滤先于
  猪友判定执行，与配置描述「这些 QQ 号不看黑白名单」矛盾；现改为猪友判定提前——命中
  `pig_users` 即跳过群/用户名单检查直接走猪友分支，仅普通用户路径先过两级名单。
  README 相关表述同步更正。
- **修复：冷却秒数配 `0` 无法禁用冷却**。普通/猪友冷却解析由 `or 兜底` 改为显式校验：
  `0` = 禁用冷却（命中概率/冷却过即贴），负数或非法值回退默认（600s / 1800s）；
  配置 description、`PigReactState` 与 Hook docstring 的默认值口径同步更正（清理遗留的「120s」旧默认）。
- **新增：`emoji_like` 工具频控**。新配置 `emoji_reaction.tool_cooldown_seconds`
  （默认 10 秒，0 = 不限频）：每个会话最小调用间隔，超限返回「贴表情太频繁」的 LLM 可读
  提示，防止失控模型或提示注入诱导短时间内反复贴表情刷屏。
- **修复：冷却状态清理缺失**。`PigReactState.cleanup()` 现由「群友是🐷」Hook 入口每小时
  低频调用一次（含新增的工具频控表），长期运行不再内存缓慢增长。
- **清理与健壮性**：
  - 删除死代码 `build_chat_record` / `validate_chat_record`（v0.3.0 改走合成通知注入后遗留）
    与 `_fetch_stream_info` 中的空 `pass` 分支；
  - `_resolve_emoji_id` 描述库匹配收紧：去掉「描述包含于输入」的反向子串，子串匹配要求
    输入 ≥2 字符且单向（输入包含于描述），避免「猪」这类单字宽泛词模糊命中多条；
  - `emoji_id` 全链路范围校验（非负 int32，上限 2^31-1）：数字直传、描述库反查、
    `set_msg_emoji_like` 参数构造三处把关，越界 ID 不再透传协议端（走回退/报错）；
  - `session_id` 为空时提前拒绝贴表情（Hook 判定与 `_apply_emoji_like` 双处），
    不再出现「表情贴出但记录注入必然失败」的半成品调用；
  - 记录注入 `dedupe_key` 附带分钟级时间片：同一条消息第二次贴同款表情（合法重复）
    不再被去重吞掉 WebUI 记录。
- README 配置示例 `config_version` 更正为 0.3.1（原示例停留在 0.2.1）。

## 0.3.0（2026-09-28）

**MaiBot 1.3.0 兼容版本：适配器依赖切换到合并版 SnowLuma 适配器。**

- **适配器依赖切换**（`_manifest.json` `dependencies`）：旧声明 `maibot-team.napcat-adapter
  >=1.0.0` → **`maibot-team.snowluma-adapter >=1.0.0,<2.0.0`**。合并版适配器（1.0.x，随
  MaiBot 1.3.0 发布，已合并 NapCat 适配器）插件 ID 已变更，旧声明在 1.3.0 下会因 Host
  依赖流水线报「依赖未满足: maibot-team.napcat-adapter (未找到依赖插件)」而**阻止本插件
  加载**。切换后同时获得适配器先于本插件的启动顺序保证（v1.3.0 开发文档 §4.3 建议）。
  注意：仅装旧版 NapCat 适配器（`maibot-team.napcat-adapter`）的 1.2.x 环境无法加载本
  0.3.0（合并版适配器宿主区间 1.2.0 ~ 1.3.99，1.2.x 也可改装合并版；如需维持旧组合请用 0.2.3）。
- **兼容性核查（对照合并版适配器 1.0.2 源码）**，全部通过：
  - `adapter.napcat.action.call`（apis/support.py:249）：`params={...}` 包装支持，负 `message_id`
    原样透传；动作失败时适配器侧抛 RuntimeError（services/action_service.py:56-58），本插件
    try/except 与 status/retcode 双路径兜底均覆盖；
  - 通知注入结构（codecs/notice/message_codec.py）：`additional_config` 仍携带
    `napcat_notice_type / napcat_notice_sub_type / napcat_notice_payload / self_id`，`is_notify=True`，
    与翻译器逐字段吻合；
  - `adapter.napcat.system.get_login_info` 存在且返回结构兼容（`data.nickname` 取昵称）；
  - `gateway.route_message` / `gateway.update_state` 对应的宿主 RPC（`host.route_message` /
    `host.update_message_gateway_state`）在 1.3.0 均在；能力注册表无增删。
- **不再需要的功能/产物**（随本次清理）：
  - 旧版 NapCat 适配器「专用 `set_msg_emoji_like` API 校验正整数、必须走 action.call 绕道」的
    前提已消失——合并版适配器 `_normalize_message_id`（apis/support.py:113）原生接受负 ID；
    action.call 通道保留，注释同步更新；
  - 「影子适配器补投的 `napcat-shadow-*` 通知」语境过时（影子适配器已随 1.3.0 退役）：合成消息
    跳过逻辑本身保留（`qq-notice-*`、`emoji-reaction-notice-*` 等合成 ID 仍需跳过）；
  - 删除两份已完成使命的 issue 草稿：`SNOWLUMA_ADAPTER_PASSTHROUGH_API_ISSUE_DRAFT.md`
    （对应透传 feat，已在合并版适配器落地）与 `emoji_map/NAPCAT_DEDUPE_ISSUE_DRAFT.md`
    （对应去重缺陷 #97，已在合并版适配器修复）；`emoji_map/SNOWLUMA_ISSUE_DRAFT.md`
    （表情映射表错位）修复状态未确认，保留。
- README（依赖说明/安装步骤/致谢）、manifest description、`SUPPORTED_CONFIG_VERSION`
  同步更新。功能逻辑零改动。

## 0.2.3（2026-09-07）

- 为全部配置项补充/完善了用户友好的中文注释与说明（悬停提示），完善配置节说明；插件功能与行为不变。

## 0.2.2（2026-09-06）

- 修复：**与 NapCat 影子适配器（cateye.napcat-shadow-adapter）同装时贴表情报错** `invalid literal for int() with base 10: 'napcat-shadow-…'`。根因：影子适配器补投的合成通知（`is_notify=True`）以群友身份入库，`filter_mai` 拦不住，会被 `emoji_like` 的「自动定位最近一条非机器人消息」选中；而其 message_id 是隔离键空间的字符串 `napcat-shadow-<uuid>`，`build_set_emoji_like_params` 强转 int 抛异常。修复：
  - 自动定位目标时跳过合成消息（`is_notify=True` 或 message_id 非数字），落到最近一条真实群友消息；
  - 贴表情前校验目标 ID 可解析为带符号整数（负 ID 仍合法），不可解析（如 `napcat-shadow-*`、本插件入库的 `emoji-reaction-notice-*`）时返回 LLM 可读的失败原因（目标是系统通知，请贴普通聊天消息），不再抛异常原文。

## 0.2.1（2026-08-28）

- **概率自动贴表情事件标签**：「群友是🐷」概率自动触发的贴表情记录（非 LLM 调用工具）改用 `[事件-插件概率事件（聊天中用户未直接提及该行为则忽视该信息，如果提及该行为则回应为随手贴的）]` 前缀，区别于 LLM 主动调用 `emoji_like` 工具的 `[事件-群消息表情回应]`；避免模型把概率行为当作主动行为回应（用户未提及则忽视，提及则回应为「随手贴的」）。
- README 同步更新「动作入库显示」与「群友是🐷」段落说明。

## 0.2.0（2026-08-27）

- 新增 LLM 工具 `emoji_like_list`：查询当前配置的可用贴表情列表（表情 ID + 表情名 + 描述），供 LLM 在调用 `emoji_like` 前确认可用表情与对应 ID。
- `emoji_like` 工具描述强化引导：调用前必须先调用 `emoji_like_list` 确认表情 ID，把 ID（数字）传入 `emoji` 参数，不要凭印象编造表情表达。
- 新增配置项 `emoji_reaction.allow_fallback_to_default`（默认开启）：LLM 传入的描述库外表达（如「开心」「俏皮」等情绪词）或无效表情时，自动回退到默认表情 12951，不再返回「未识别的表情表达」错误。关闭后保持旧行为（返回失败）。
- 默认描述库扩充：从内置映射表（emoji_map/）挑选代表性经典表情（12951 祝(猪)、14 微笑、21 可爱、46 猪头、66 爱心、76 赞、174 无奈、182 笑哭、271 吃瓜、319 比心、357 裂开），覆盖常见情绪/互动场景，供 LLM 选择。
- 12951 名称映射改为「祝(猪)」（emoji_reaction_extra.json 覆盖 merged 表），与 QQ 客户端实际显示名一致。
- 说明：MaiBot 插件 SDK 无「强制链式工具调用」机制（`@Tool` 为静态声明、`ctx.tool` 仅只读查询），因此采用「新查询工具 + 描述引导 + 失败回退」组合方案。
- 修复：`emoji_like_list` 返回的 dict 现在包含 `content` 字段（MaiBot Tool 规范中给 LLM 阅读的纯文本），逐行列出每个表情的 `emoji_id`（数字）+ 名称 + 描述；此前 LLM 只能看到"有 11 个表情"但看不到具体 ID（结构化字段 `emoji_list` 对 LLM 不可见）。`emoji_like` 成功/失败返回也补上 `content`，未识别时明确引导先查 `emoji_like_list`、不要盲试。
- 修复：**机器人自己贴表情时重复入库两条**。根因：机器人贴表情后 QQ/NapCat 会回推一条 `group_msg_emoji_like` 通知（操作者是机器人自己），插件 Hook 把它当"群友贴表情"翻译入库；而插件在贴表情成功时已主动注入一条记录（`_record_and_context`），导致同一次贴表情出现两条入库。修复：通知翻译 Hook 识别 `actor_user_id == self_id`（机器人自己发起的表情回应）并跳过（abort），只保留主动注入的记录；群友贴表情通知照常翻译。

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
