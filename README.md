# 🐷！表情回应（MaiBot 插件）

为麦麦（MaiBot）框架的插件，让机器人可以对聊天消息**贴 QQ 表情回应（reaction）**，并把收到/发起的表情回应翻译成可读文本显示在 WebUI 聊天记录中。

- **LLM 工具 `emoji_like`**：让模型在聊天中自然决定对消息贴表情回应（如表达赞同、开心、无奈、可爱，或与群友互动），可作为 `send_emoji` 的轻量替代。
- **表情回应通知翻译**：拦截 NapCat 的 `group_msg_emoji_like` 通知，翻译为「谁 对哪条消息 贴了 什么表情」，注入框架内部。
- **群友是🐷**：用户发消息时按概率/规则自动贴表情（可配置黑白名单、冷却、猪友专属连贴机制）。

本插件依赖 **NapCat 适配器**（`maibot-team.napcat-adapter`）提供 `set_msg_emoji_like` API，已实测兼容 **SnowLuma 适配器**（本体 + 官方 NapCat 插件）环境。

## 功能特性

- **贴表情（`emoji_like` 工具）**：模型可对聊天中的某条消息贴 QQ 表情回应，默认贴到最近一条非机器人消息。支持从「描述库」按描述选择表情，或直接给表情 ID；未指定时使用默认表情（点赞）。
- **动作入库显示**：贴表情动作会以 `[事件-群消息表情回应] 机器人名 对消息(ID:xxx)贴了表情：描述` 的合成通知形式**注入聊天流**（WebUI 可见、不真发到群里、不触发 LLM 回复）。
- **表情回应通知翻译**：群友贴表情时，插件把原始通知翻译为 `[事件-群消息表情回应] 群友名 对消息(ID:xxx)表达了 表情名` 并注入框架：
  - 表情名来自内置对照表（QQ 官方 / NapCat / SnowLuma 多源合并，含 JSON 自定义扩展）；
  - 若该表情 ID 同时在**配置文件描述库**中有具体含义，则显示 `表达了 表情名：具体描述`（如 `表达了 玫瑰：鲜花`）。
- **群友是🐷**：自动贴表情功能（默认关闭），支持：
  - 群名单（白/黑名单）与用户名单（白/黑名单）过滤；
  - **普通用户**：每次发消息按概率（默认 5%）贴一次，全局冷却；
  - **猪友（pig_users）**：无视黑白名单、无视概率，冷却过即贴；每次贴后按概率免冷却连贴下一条消息（最多 `pig_max_chain` 条）。
- **消息 ID 兼容**：QQ 的 `message_id` 是**带符号 int32，负数为合法值**，插件原样透传，不转换符号。

## 安装方式

1. 将本插件目录（含 `_manifest.json`、`plugin.py`、`notice_translator.py`、`emoji_reaction_replacer.py`、`emoji_map/` 等文件）放入 MaiBot 的 `plugins/` 目录。
2. 重启 MaiBot，或在 WebUI 插件中心安装。
3. 插件依赖 NapCat 适配器（`maibot-team.napcat-adapter`），请确保其已启用且能连接到 NapCat / SnowLuma 本体。

> 兼容性声明：`host_application` `1.0.0 ~ 1.99.99`，`sdk` `2.0.0 ~ 2.99.99`（Manifest v2）。

## 配置说明

插件加载后由 Runner 在插件目录生成 `config.toml`，可在 WebUI 修改：

```toml
[plugin]
enabled = true
config_version = "0.1.0"

[emoji]
optimize_unknown_emoji = false   # 未知表情优化：true=显示「一个表情」；false=显示「未知表情<id>」

[emoji_reaction]
description_library = [
    "12951: 该回应表情等效网络流行的猪猪表情包，表达群友可爱又有点笨的样子",
]

[pig_friends]
enabled = false                       # 「群友是🐷」总开关
group_list_mode = "whitelist"         # 群名单模式：whitelist / blacklist
group_list = []                       # 群名单（群号）
user_list_mode = "blacklist"          # 用户名单模式：whitelist / blacklist
user_list = []                        # 用户名单（QQ 号）
normal_probability = 0.05             # 普通用户自动贴表情概率（0~1）
normal_cooldown_seconds = 600         # 普通用户贴后全局冷却（秒）
pig_users = []                        # 猪友 QQ 号列表（无视黑白名单与概率）
pig_cooldown_seconds = 1800           # 猪友独立冷却（秒，每个 QQ 独立）
pig_chain_skip_cooldown_probability = 0.25  # 猪友贴后免冷却连贴概率（0~1）
pig_max_chain = 3                     # 猪友最多连贴条数
```

- `emoji.optimize_unknown_emoji`：未知表情的显示方式。开启后未知表情显示为「一个表情」；关闭时显示「未知表情<id>」（与 SnowLuma 一致，默认关闭）。
- `emoji_reaction.description_library`：**描述库**，每行一条 `emoji_id: 描述`。作用有二：
  1. 供 `emoji_like` 工具按描述选表情（如「猪猪表情」→ 12951）；
  2. 表情回应通知翻译时，若该 ID 命中描述库，则显示 `表达了 表情名：描述`（表情名来自对照表）。**兼容旧格式**：也接受 JSON 字符串（`"{\"12951\": \"...\"}"`）或字典（旧配置自动迁移）。
- `pig_friends.*`：群友是🐷 的各项参数（见「功能特性」）。`pig_users` 中的 QQ 号**不受黑白名单与概率限制**，但群/用户黑白名单仍会先于猪友判定执行。

## 使用说明

### LLM 工具（自然语言触发）

| 工具 | 触发场景 | 参数 |
|------|---------|------|
| `emoji_like` | 模型想对某条消息贴表情回应表达情绪/互动时（可作为 `send_emoji` 的替代） | `emoji`（可选：描述库表达或表情 ID，留空用默认）、`target_message_id`（可选：目标消息 ID，留空自动定位最近一条非机器人消息） |

> 工具描述已引导模型：默认贴到最近一条非机器人消息（通常正在回复/讨论的那条）；调用后模型应在回复中自然提及这次贴表情，避免重复表达。

### 表情回应通知翻译格式

- 仅对照表命中：`[事件-群消息表情回应] 凯特艾 对消息(ID:-1683989482)表达了 [玫瑰]`
- 对照表 + 描述库命中：`[事件-群消息表情回应] 凯特艾 对消息(ID:-1683989482)表达了 玫瑰：<描述库中的具体含义>`
- 未知表情（`optimize_unknown_emoji=false`）：`...表达了 [未知表情999999]`

### 群友是🐷（自动贴表情）

- 普通用户：发消息 → 概率命中 → 贴 12951（猪猪表情）→ 全局冷却。
- 猪友：发消息 → 冷却过即贴（不看概率/黑白名单）→ 贴后按概率免冷却连贴下一条消息，最多 `pig_max_chain` 条。
- 黑白名单：`group_list_mode=whitelist` 表示仅名单内群生效；`blacklist` 表示名单内群不生效（用户名单同理）。

## 数据存储

- 本插件**不保存任何用户数据**，无持久化存储。
- 贴表情动作与翻译后的通知通过**注入聊天流**写入 MaiBot 数据库（`mai_messages`），显示在 WebUI，不真发消息。
- 机器人昵称通过 NapCat `get_login_info` 查询（缓存 1 小时），用于注入记录显示正确的机器人名。

## 目录结构

```
cateye_set_msg_emoji_like_api_modify/
├── _manifest.json              # 插件元信息（Manifest v2）
├── plugin.py                   # 插件主体（配置 / 工具 / Hook / 网关 / 群友是🐷）
├── notice_translator.py        # 表情回应通知翻译核心逻辑
├── emoji_reaction_replacer.py  # 贴表情核心逻辑（描述库 / 参数 / 聊天记录 / 冷却状态机）
├── emoji_map/                  # QQ 表情 ID → 名称映射表与解析器
│   ├── qq_emoji_resolver.py    # 解析器（分层加载：内置合并 + JSON 覆盖）
│   ├── qq_face_merged.json     # 多源合并映射
│   ├── qq_face_napcat.json     # NapCat 表（220 条，推荐基础源）
│   ├── qq_face_official.json   # QQ 官方文档表
│   ├── qq_face_snowluma.json   # SnowLuma 表（含错位标注）
│   ├── emoji_reaction_extra.json  # 表情回应扩展 ID 手动维护表
│   ├── merge_emoji_maps.py     # 多源合并工具
│   └── README.md               # 映射表说明与扩展指南
├── README.md                   # 本说明文档
└── LICENSE                     # MIT 许可证
```

## 免责声明

- 本插件仅用于个人学习与自动化交互用途，请遵守腾讯 QQ 与 NapCat / SnowLuma 的相关服务条款。
- 贴表情、自动贴表情等行为可能对群聊造成打扰，请合理配置冷却与名单，谨慎启用「群友是🐷」。

---

## 致谢与来源

- **`TAIY2020/smart_poke_plugin`**（[GitHub](https://github.com/TAIY2020/smart_poke_plugin)）：参考其「机器人自戳通知自动入库」机制，实现了本插件的 MessageGateway 注入合成通知（WebUI 显示不真发）。
- **`maibot-team.napcat-adapter`**（MaiBot 官方 NapCat 适配器插件）：提供 `adapter.napcat.action.call` 通用入口与 `set_msg_emoji_like` 动作、`get_login_info` 等 API，本插件只使用其公开接口，未修改官方代码。
- **MaiBot-SnowLuma-Adapter**（官方 SnowLuma 适配器）：表情回应通知格式（`group_msg_emoji_like`）与昵称错配排查的参考。
- **[Undefined 项目](https://github.com/69gg/Undefined)**：`qq_emoji.py` 的表情映射 JSON 覆盖扩展机制，本插件 `emoji_map/` 沿用该思路（反向 id→名称）。
- **QQ 官方机器人文档**（[Emoji 列表](https://bot.q.qq.com/wiki/develop/nodesdk/model/emoji.html)）：系统表情 ID 权威来源。
- 插件基于 [MaiBot 插件开发文档](https://docs.mai-mai.org/plugin/) 与 [maibot-plugin-sdk](https://github.com/Mai-with-u/maibot-plugin-sdk) 开发。
