# 🐷！表情回应（MaiBot 插件）

为麦麦（MaiBot）提供的表情回应插件：让机器人对聊天消息**贴 QQ 表情回应（reaction）**，把群友的表情回应通知翻译成可读文本，并把机器人发起的贴表情动作记录注入聊天流与 WebUI。

当前代码版本：**0.4.1**（以 [`_manifest.json`](_manifest.json) 为准）。

## 效果演示

机器人「迷迭香」对群友消息贴了「祝」表情回应（QQ 端显示，含贴表情记录入库）：

![效果演示：迷迭香对群友的消息贴了「祝」表情回应](assets/emoji-like-demo.jpg)

## 功能特性

- **LLM 工具 `emoji_like`**：按「开心」「赞同」等情绪词查找表情，或传数字 ID 对聊天消息贴 QQ 表情回应。查询会返回 ID、名称和描述，适合先挑表情再贴。
- **表情回应通知翻译**：拦截 NapCat 的 `group_msg_emoji_like` 通知，翻译为「谁 对哪条消息 表达了 什么表情」，改写消息文本后交给 MaiBot 后续处理。
- **群友是🐷（默认关闭）**：用户发消息时按概率或名单规则自动贴表情，支持群/用户黑白名单、普通用户概率与全局冷却、🐷用户独立冷却与免冷却连贴链。
- **记录注入**：贴表情动作以合成通知形式注入聊天流（WebUI 可见），同时追加到 Planner 上下文；记录文本不会作为 QQ 消息发送，但贴表情本身是真实 QQ 动作。
- **消息 ID 兼容**：QQ 的 `message_id` 为带符号整数，负值合法，插件原样透传。

## 环境与依赖

| 项目 | 要求 |
|------|------|
| MaiBot 宿主 | `1.2.0 ~ 1.4.7` |
| MaiBot 插件 SDK | `2.7.1 ~ 2.99.99` |
| SnowLuma 适配器 | `maibot-team.snowluma-adapter >=1.0.0,<2.0.0`（插件级硬依赖） |

本插件只调用适配器公开接口（`adapter.napcat.action.call`、`adapter.napcat.system.get_login_info` 等），未修改适配器代码。声明插件级依赖的原因：

- 适配器插件 ID 自合并版起变更为 `maibot-team.snowluma-adapter`，旧的 `maibot-team.napcat-adapter` 依赖声明在 MaiBot 1.3.0 下会因「依赖未满足」阻止本插件加载；
- 按 [v1.3.0 开发文档 §4.3](https://github.com/Mai-with-u/MaiBot) 建议，调用适配器 API 的插件声明 `type: "plugin"` 依赖可获得启动顺序保证（适配器先于本插件启动，避免加载竞态）。

未安装或未启用该适配器时，插件不会被加载（Host 依赖流水线报「依赖未满足」），这是预期行为，不是插件故障。合并版适配器 1.0.x 支持 1.2.x 宿主。仍在使用旧版 NapCat 适配器、且无法升级的 1.2.x 环境，请使用本插件 0.2.3（0.3.0 起才依赖合并版适配器）。

如果使用中发现 MaiBot 没有正确收到回应信息，且日志中出现类似：

> 08-27 20:08:32 [平台接入管理] 忽略重复入站消息: dedupe_key=gateway:maibot-team.napcat-adapter:napcat_gateway:<去重键>

这是 MaiBot 1.2.x + 旧版适配器的已知缺陷（通知去重键误用，Napcat-Adapter issue #97），合并版适配器 1.0.x 已修复，请升级适配器而非改内部拦截规则。

## 安装

1. 将本插件目录（含 `_manifest.json`、`plugin.py`、`notice_translator.py`、`emoji_reaction_replacer.py`、`emoji_map/` 等）放入 MaiBot 的 `plugins/` 目录。
2. 安装并启用官方合并版 SnowLuma 适配器（`maibot-team.snowluma-adapter` 1.0+），确认适配器已连接到协议端。
3. 重启 MaiBot，或在 WebUI 插件中心安装/启用本插件。
4. 插件加载后会在插件目录生成 `config.toml`（已被 `.gitignore` 忽略，不会进入版本库）。

安装后自检：

- WebUI 插件列表中本插件已启用，依赖的 SnowLuma 适配器已连接；
- 用 `emoji_like` 查询「开心」，应返回最多 5 条候选，每条附数字 ID 和描述；
- 群友对消息贴一个已知表情，聊天记录应出现「[事件-群消息表情回应] …表达了 …」；
- 用查询返回的数字 ID 调用 `emoji_like`，QQ 应显示对应的表情回应。开启补录时，WebUI 聊天记录也会显示这次贴表情。

## 配置

在 WebUI 插件配置的「贴表情工具」中可切换「补录表情通知」，对应 `emoji_reaction.record_reaction_notice`，默认关闭。已有配置中显式填写的值继续生效。关闭后宿主会注销对应的 QQ 补录网关。实际贴表情、群友通知翻译和 Planner 上下文照常运行。在支持配置热更新的宿主中，保存后生效。补录写入原 QQ 群的聊天记录。

插件加载后在插件目录生成 `config.toml`，可在 WebUI 修改。全部字段与默认值如下（示例中的群号、QQ 号均为占位）：

```toml
[plugin]
enabled = true
config_version = "0.4.1"          # 由 Runner 维护，勿改

[emoji]
optimize_unknown_emoji = false    # 未知表情显示：true=「一个表情」；false=「[未知表情<id>]」（默认）

[emoji_reaction]
search_result_limit = 5          # 查询结果上限，超出时随机抽取
featured_emoji_mode = "使用"     # 不使用 / 使用 / 始终启用
featured_emoji_ids = [424, 478, 479] # 续标识、对的对的、不对不对
description_library = []         # 可选的旧配置描述覆盖
tool_cooldown_seconds = 10.0      # 每个会话的贴表情间隔（秒，0 = 不限频）
record_reaction_notice = false   # 在 WebUI 聊天记录里补录机器人贴表情的动作

[pig_friends]
enabled = false                       # 「群友是🐷」总开关
auto_emoji_id = 12951                 # 自动贴表情 ID
group_list_mode = "whitelist"         # 群名单模式：whitelist / blacklist
group_list = []                       # 群名单（群号）
user_list_mode = "blacklist"          # 用户名单模式：whitelist / blacklist
user_list = []                        # 用户名单（QQ 号）
normal_probability = 0.05             # 普通用户自动贴表情概率（0~1）
normal_cooldown_seconds = 600         # 普通用户贴后全局冷却（秒，0 = 禁用冷却）
pig_users = []                        # 🐷用户 QQ 号（无视名单与概率）
pig_cooldown_seconds = 1800           # 🐷用户独立冷却（秒，每个 QQ 独立，0 = 禁用冷却）
pig_chain_skip_cooldown_probability = 0.25  # 🐷用户贴后免冷却连贴概率（0~1）
pig_max_chain = 3                     # 连贴链上限（一轮最多贴 N+1 条）
```

- **检索上限 `search_result_limit`**：每次最多返回指定数量。命中更多时，每次会从全部匹配的表情中随机抽取。
- **精选表情**：`featured_emoji_ids` 按配置顺序列出要推荐的表情。普通搜索结果和精选列表各自显示，检索上限应用于普通搜索结果。
- **描述库 `description_library`**：默认留空，使用映射表中的描述。旧配置中的自定义「表情 ID: 描述」可继续覆盖描述，也可移入 `emoji_map/emoji_reaction_custom.json`。
- **自动贴表情 `auto_emoji_id`**：填写 `0 ~ 2147483647` 的整数，非法值会回退为 12951 并记录告警。
- **冷却秒数**：`tool_cooldown_seconds` / `normal_cooldown_seconds` / `pig_cooldown_seconds` 配 `0` 表示禁用。负值回退默认值。
- **名单模式**：`group_list_mode` / `user_list_mode` 支持 `whitelist` / `blacklist`。
- **映射表**：配置表情名称、描述与情绪标签，修改后重新加载插件或重启 MaiBot。[映射说明](emoji_map/README.md)

配置示例——只在一个群里启用「群友是🐷」：

```toml
[pig_friends]
enabled = true
group_list_mode = "whitelist"
group_list = ["123456789"]
pig_users = ["987654321"]
```

## 使用

本插件**不注册任何聊天指令**，没有 `/el` 等调试命令；所有能力通过 LLM 工具与 Hook 自动触发。

### LLM 工具

`emoji_like` 的 `emoji` 参数必填。

| 传入值 | 行为 |
|--------|------|
| `{"emoji":"赞同"}` | 搜索名称、别名、情绪标签或描述包含「赞同」的表情，返回描述与 ID。 |
| `{"emoji":"76"}` | 对目标消息贴 ID 为 76 的表情。 |
| `{"emoji":"999999"}` | 提示 ID 无效或未收录，引导模型先按词查询。 |

在 WebUI「贴表情工具」中设置 `featured_emoji_mode`。

| 模式 | 查询结果 |
|------|----------|
| 不使用 | 返回普通搜索结果。 |
| 使用（默认） | 搜索无结果时先提示未找到，再附上精选表情。 |
| 始终启用 | 每次搜索在末尾附上「以下是精选表情」。 |

精选名单和旧版自定义描述分别设置。映射表中的表情都可以按词查询或用 ID 贴出。

贴表情时可传 `target_message_id`。省略时，工具从最近 24 小时的消息中选最近一条真实的非机器人消息。贴表情受每会话冷却限制，查询可以连续调用。

### 表情回应通知翻译

群友对消息贴表情时，NapCat 推送 `group_msg_emoji_like` 通知，插件在 `chat.receive.before_process` Hook 中把它翻译为可读文本：

```text
[事件-群消息表情回应] {谁} 对消息(ID:{目标消息ID})表达了 {表情}
```

| 场景 | 示例 |
|------|------|
| 映射表含描述 | `...表达了 玫瑰：送一朵玫瑰，表达爱意、欣赏或感谢。` |
| 自定义映射只填名称 | `...表达了 [自定义表情]` |
| 未知表情（默认） | `...表达了 [未知表情999999]` |
| 未知表情（开启 `optimize_unknown_emoji`） | `...表达了 一个表情` |
| 多个表情 | `...表达了 流泪：默默掉眼泪…、[点赞]x2` |

补充规则：

- `{谁}` 优先取通知中的昵称，取不到时用通知里的操作者 QQ 号，再取不到显示「有人」；没有目标消息 ID 时显示「对一条消息」。
- 一条通知包含多个表情时，附上首个表情的描述，同时列出其余表情的名称。
- 机器人自己发起的表情回应通知会被跳过（避免与插件主动注入的记录重复入库）；群友的通知照常翻译。
- 昵称等用户可控文本拼入消息前会清理控制字符、压缩空白并限长（昵称 ≤64 字符），防止恶意昵称注入提示词或撑爆上下文。

### 记录注入

贴表情成功后，插件将动作追加到 Planner 上下文。开启「补录表情通知」时，还会在 WebUI 聊天记录显示这次贴表情：

```text
emoji_like / 群友是🐷
  ├─ adapter.napcat.action.call → set_msg_emoji_like（真实 QQ 表情回应）
  └─ 追加 Planner 上下文，按配置补录到 WebUI
```

- LLM 工具调用的记录使用 `[事件-群消息表情回应]` 前缀；「群友是🐷」概率自动贴表情使用 `[事件-插件概率事件（聊天中用户未直接提及该行为则忽视该信息，如果提及该行为则回应为随手贴的）]` 前缀，避免模型把概率行为当成主动行为回应。
- 合成记录是否触发 LLM 回复由 MaiBot 对通知类消息的处理策略决定。
- 注入前会反查流信息；取不到机器人 `self_id` 时放弃聊天流注入（Planner 上下文追加仍会尝试），避免写入身份不明的记录。机器人昵称通过 `get_login_info` 查询并缓存 1 小时，失败时用 QQ 号兜底。
- 插件不保存持久化用户数据；冷却/频控状态只保存在进程内存中，重启即清空（开启「群友是🐷」时每小时清理一次过期状态）。

### 群友是🐷（自动贴表情）

默认关闭。开启 `[pig_friends] enabled = true` 后，用户发送普通消息时按以下顺序判定：

1. 只处理普通用户入站消息（跳过通知、指令、机器人自己）；
2. 命中 `pig_users` 的🐷用户直接走🐷分支，不再看名单与概率；
3. 普通用户先过群名单（仅群聊），再过用户名单，然后按 `normal_probability` 判定；
4. 命中后贴 `auto_emoji_id` 并注入记录（带「插件概率事件」标签）。

- **普通用户**：概率命中 → 贴表情 → 全局冷却 `normal_cooldown_seconds`（默认 600 秒，所有普通用户共享）。
- **🐷用户**：冷却过即贴（每个 QQ 独立冷却，默认 1800 秒，不看名单与概率）；贴后按 `pig_chain_skip_cooldown_probability`（默认 0.25）进入免冷却连贴链——链内下一条消息直接贴，不再判冷却/概率，直到概率未命中或达到 `pig_max_chain` 上限。

连贴链计数表示「已获得几次免冷却连贴资格」，因此一轮最多贴 `pig_max_chain + 1` 条（首条 + N 次链内连贴）。以默认 `N = 3`、每次连贴概率都命中为例：

| 消息 | 动作 |
|------|------|
| 第 1 条 | 冷却过，贴出；进入链（计数 1） |
| 第 2 条 | 链内直接贴；计数 2 |
| 第 3 条 | 链内直接贴；计数 3 |
| 第 4 条 | 链内直接贴；已达上限，退出链并恢复正常冷却 |

中途概率未命中会提前结束并恢复正常冷却。

## 常见问题排查

- **插件没有加载**：确认已安装并启用 `maibot-team.snowluma-adapter`（`>=1.0.0,<2.0.0`），宿主与 SDK 版本满足「环境与依赖」一节；仅装旧版 NapCat 适配器的环境请升级适配器，或改用本插件 0.2.3。
- **群友贴表情后没有翻译记录**：确认通知是 `group_msg_emoji_like` 且不是机器人自己发起的；检查映射表是否有该 ID（未知 ID 显示 `[未知表情<id>]`，可按 [扩展指南](emoji_map/EXTENSION_GUIDE.md) 添加），并确认 `emoji.optimize_unknown_emoji` 符合预期。
- **贴表情失败：目标是系统通知**：自动定位会跳过合成通知；显式传 `target_message_id` 时请确认是真实 QQ 消息 ID（可解析为整数）。
- **提示「贴表情太频繁」**：等待后重试；不需要频控可把 `tool_cooldown_seconds` 设为 `0`。
- **同一动作出现两条记录**：插件已跳过机器人自身的通知；若仍重复，检查适配器是否正确提供 `self_id`，并优先升级合并版适配器（旧版有已知去重键问题）。
- **负消息 ID 是否合法**：合法。QQ 消息 ID 是带符号整数，插件原样传递，请勿自行取绝对值。

## 目录结构

```
cateye_set_msg_emoji_like_api_modify/
├── _manifest.json              # 插件元信息（Manifest v2）
├── plugin.py                   # 插件主体（配置 / 工具 / Hook / 网关 / 群友是🐷）
├── notice_translator.py        # 表情回应通知翻译核心逻辑
├── emoji_reaction_replacer.py  # 贴表情参数、合成通知、冷却状态机
├── emoji_map/                  # 表情名称、描述与情绪标签映射表
│   ├── qq_emoji_resolver.py    # 解析器（分层加载：内置合并 + JSON 覆盖）
│   ├── qq_face_merged.json     # 多源合并映射
│   ├── qq_face_napcat.json     # NapCat 表
│   ├── qq_face_official.json   # QQ 官方文档表（摘录）
│   ├── qq_face_snowluma.json   # SnowLuma 表（含错位标注）
│   ├── emoji_reaction_extra.json  # 表情回应扩展 ID 手动维护表
│   ├── emoji_reaction_custom.json # 用户自定义映射
│   ├── merge_emoji_maps.py     # 多源合并工具（开发期使用）
│   ├── README.md               # 映射数据说明
│   └── EXTENSION_GUIDE.md      # 映射扩展指南
├── assets/
│   └── emoji-like-demo.jpg     # 效果演示截图
├── CHANGELOG.md                # 历史版本更新记录
└── LICENSE                     # MIT 许可证
```

## 免责声明

- 本插件仅用于个人学习与自动化交互用途，请遵守腾讯 QQ 与 NapCat / SnowLuma 的相关服务条款。
- 贴表情、自动贴表情等行为可能对群聊造成打扰，请合理配置冷却与名单，谨慎启用「群友是🐷」。

## 致谢与来源

- **`TAIY2020/smart_poke_plugin`**（[GitHub](https://github.com/TAIY2020/smart_poke_plugin)）：参考其「机器人自戳通知自动入库」机制，实现本插件的 MessageGateway 合成通知注入。
- **MaiBot-SnowLuma-Adapter（合并版）**：提供 `adapter.napcat.action.call`、`set_msg_emoji_like`、`get_login_info` 等公开接口与 `group_msg_emoji_like` 通知格式；本插件未修改其代码。
- **[Undefined 项目](https://github.com/69gg/Undefined)**：`qq_emoji.py` 的 JSON 覆盖扩展机制，本插件 `emoji_map/` 沿用该思路（反向 id → 名称）。
- **QQ 官方机器人文档**（[Emoji 列表](https://bot.q.qq.com/wiki/develop/nodesdk/model/emoji.html)）：系统表情 ID 的参考来源。
- 插件基于 [MaiBot 插件开发文档](https://docs.mai-mai.org/plugin/) 与 [maibot-plugin-sdk](https://github.com/Mai-with-u/maibot-plugin-sdk) 开发。
