# QQ 表情 ID 映射汇总与扩展机制

> 收集整理 MaiBot 生态可查到的 QQ 表情 ID → 名称映射，供插件解析表情回应
> （`group_msg_emoji_like` 通知的 `likes[].emoji_id`）使用。
> 整理日期：2026-08-27。数据来源见文末「来源与可信度」。

---

## 1. 表情 ID 体系概述

QQ 表情 ID 分三类：

| 体系 | ID 范围 | 说明 | 是否能被「表情回应」使用 |
|------|---------|------|--------------------------|
| 系统表情（face） | 0 ~ 400+ | QQ 自带经典表情，如 76=赞、66=爱心 | ✅ 是（官方文档确认，如 👍=76） |
| Unicode 表情 | 127000+（码点） | 如 127801=🌹、128077=👍 | ✅ 是（NapCat/SnowLuma 表均有收录） |
| 扩展/大表情 | 五位数（如 12951） | QQ 手机客户端表情回应专用扩展 ID | ⚠️ 是（实测可贴），但**无公开名称映射** |

> **12951 实测**：通过 `set_msg_emoji_like(message_id, emoji_id=12951, set=true)` 可成功给消息贴表情，
> QQ 端显示为「点赞」类表情。但它不在任何公开映射表中（官方 0-326、Unicode、适配器表均无）。
> 属于 QQ 客户端私有的表情回应扩展 ID，只能通过「对消息贴表情后用 QQ 端确认显示名」反向建表。

---

## 2. 系统表情映射（face，0~400）

### 2.1 权威版本：QQ 官方机器人文档（[Emoji 列表](https://bot.q.qq.com/wiki/develop/nodesdk/model/emoji.html)）

> 仅列官方文档明确给出的部分（EmojiType=1 系统表情）；完整版见 `qq_face_official.json`。

| ID | 含义 | | ID | 含义 | | ID | 含义 |
|----|------|-|----|------|-|----|------|
| 1 | 惊讶 | | 14 | 微笑 | | 76 | 赞 |
| 4 | 得意 | | 15 | 难过 | | 78 | 握手 |
| 5 | 流泪 | | 16 | 酷 | | 79 | 胜利 |
| 6 | 害羞 | | 18 | 睡 | | 85 | 飞吻 |
| 7 | 闭嘴 | | 19 | 大哭 | | 89 | 西瓜 |
| 8 | 睡 | | 21 | 可爱 | | 96 | 冷汗 |
| 9 | 大哭 | | 23 | 傲慢 | | 97 | 擦汗 |
| 10 | 尴尬 | | 24 | 饥饿 | | 98 | 抠鼻 |
| 11 | 发怒 | | 25 | 困 | | 99 | 鼓掌 |
| 12 | 调皮 | | 26 | 惊恐 | | 100 | 糗大了 |
| 13 | 呲牙 | | 27 | 流汗 | | 101 | 坏笑 |
| 63 | 玫瑰 | | 28 | 憨笑 | | 106 | 委屈 |
| 66 | 爱心 | | 29 | 悠闲 | | 109 | 左亲亲 |
| 67 | 心碎 | | 30 | 奋斗 | | 111 | 可怜 |
| 74 | 太阳 | | 32 | 疑问 | | 118 | 抱拳 |
| 75 | 月亮 | | 33 | 嘘 | | 120 | 拳头 |
| 201 | 点赞 | | 34 | 晕 | | 122 | 爱你 |
| 212 | 托腮 | | 38 | 敲打 | | 123 | NO |
| 262 | 脑阔疼 | | 39 | 再见 | | 124 | OK |
| 264 | 捂脸 | | 41 | 发抖 | | 125 | 转圈 |
| 268 | 问号脸 | | 42 | 爱情 | | 129 | 挥手 |
| 269 | 暗中观察 | | 43 | 跳跳 | | 320 | 庆祝 |
| 271 | 吃瓜 | | 49 | 拥抱 | | 326 | 生气 |
| 277 | 汪汪 | | 53 | 蛋糕 | | | |
| 319 | 比心 | | 60 | 咖啡 | | | |

> 官方文档注明：列表不完整且可能变动，建议只对已知系统表情做逻辑。

### 2.2 NapCat 适配器映射（`qq_emoji_list.py` 的 `QQ_FACE`，220 条）

> 与官方文档一致（63=玫瑰、66=爱心、76=赞、201=点赞）。覆盖 0-395 + Unicode。
> **这是推荐的基础映射源**（MaiBot 插件可直接 import）。完整见 `qq_face_napcat.json`。

关键条目示例：
```python
QQ_FACE = {
    "0": "[表情：惊讶]", "1": "[表情：撇嘴]", "2": "[表情：色]",
    "63": "[表情：玫瑰]", "66": "[表情：爱心]", "76": "[表情：赞]",
    "201": "[表情：点赞]", "320": "[表情：庆祝]", "326": "[表情：生气]",
    # Unicode 表情
    "127801": "[表情：玫瑰]", "128077": "[表情：厉害]", "128513": "[表情：呲牙]",
}
```

### 2.3 SnowLuma 适配器映射（`qq_face_map.py` 的 `QQ_FACE_DESCRIPTIONS`）

> ⚠️ **注意：该表存在整体错位（旧版/错误版本）**。示例：
> - SnowLuma: 62=玫瑰、63=凋谢、64=爱心、66=礼物、76=示爱
> - 正确（官方/NapCat）: 63=玫瑰、66=爱心、76=赞
>
> 经典 face 的 ID 以**官方文档 + NapCat 表**为准；SnowLuma 表**不要直接用于 face ID 解析**。
> 但其 `QQ_FACE_EMOJIS`（ID → emoji 字符）可作参考。

### 2.4 Undefined 项目映射（`qq_emoji.py`，常用别名）

> 仅常用表情（微笑/呲牙/点赞 76/爱心 66 等），与官方一致。亮点是**支持外部 JSON 覆盖**（见 §4）。

---

## 3. 已知的「表情回应」专用 ID（实测/社区）

| emoji_id | 含义 | 来源 |
|----------|------|------|
| 12951 | 点赞（大表情版），实测可贴 | 本插件实测（QQ 端显示点赞类） |
| 379 | 点赞（另一变体），测试中出现 | 本插件实测（DB 记录） |
| 76 | 赞（经典） | 官方文档（Reaction 示例 👍=76） |

> 12951/379 这类 ID 只能靠实测积累。建议建立 `emoji_reaction_extra.json` 维护（见 §4.3）。

---

## 4. JSON 扩展映射机制（收集自 Undefined 项目）

[Undefined 项目的 qq_emoji.py](https://github.com/69gg/Undefined/blob/8fe61c4a/src/Undefined/utils/qq_emoji.py)
提供了**内置映射 + 外部 JSON 覆盖**的分层机制，非常适合 MaiBot 插件复用。

### 4.1 机制原理

```python
# 外部映射文件路径（相对项目根）
_MAP_PATHS = (
    Path("data/qq_emoji_map.json"),
    Path("config/qq_emoji_map.json"),
)

def get_emoji_alias_map() -> dict[str, int]:
    """alias -> emoji_id 映射。优先级：内置 < 外部（后加载覆盖前加载）。"""
    merged = dict(_DEFAULT_ALIAS_TO_ID)          # 1. 内置默认
    for path in _MAP_PATHS:                       # 2. 外部覆盖
        if path.exists():
            merged.update(_load_external_map(path))
    return merged
```

### 4.2 三种 JSON 格式（`_load_external_map` 支持）

**格式 A：简单字典**（alias → id）
```json
{ "点赞": 76, "👍": 76, "大赞": 12951, "牛啊": 299 }
```

**格式 B：emojis 列表**（id + aliases）
```json
{
  "emojis": [
    { "id": 12951, "aliases": ["大赞", "点赞表情"] },
    { "id": 379, "aliases": ["赞", "👍"] }
  ]
}
```

**格式 C：纯列表**
```json
[ { "id": 12951, "aliases": ["大赞"] } ]
```

### 4.3 反向查询（id → 名称）的实现建议

Undefined 只实现了 alias→id，**MaiBot 场景需要反向（id→名称）**，可这样扩展：

```python
def build_id_to_name(map_data: dict) -> dict[str, str]:
    """把 alias->id 映射反转为 id->名称（取第一个别名）。"""
    by_id: dict[int, str] = {}
    for alias, emoji_id in map_data.items():
        by_id.setdefault(int(emoji_id), str(alias))
    return {str(k): v for k, v in by_id.items()}

# 用法：解析表情回应通知的 likes[].emoji_id
# payload["likes"] = [{"emoji_id": "12951", "count": 1}]
# name = id_to_name.get("12951", f"未知表情{emoji_id}")
```

### 4.4 建议的 MaiBot 插件接入方式

```
插件 data 目录:
  data/plugins/<plugin_id>/emoji_face.json      # 系统表情 id->名称（来自 NapCat 表）
  data/plugins/<plugin_id>/emoji_reaction_extra.json  # 扩展表情 id->名称（手动维护 12951 等）
```

加载优先级：内置 NapCat 表 < `emoji_face.json` < `emoji_reaction_extra.json`（后者覆盖前者）。

---

## 5. 来源与可信度

| 来源 | 类型 | 可信度 | 说明 |
|------|------|--------|------|
| [QQ 官方机器人文档 Emoji 列表](https://bot.q.qq.com/wiki/develop/nodesdk/model/emoji.html) | 官方 | ⭐⭐⭐ | 系统表情权威；不完整 |
| NapCat `qq_emoji_list.py`（`QQ_FACE`） | 适配器 | ⭐⭐⭐ | 与官方一致，220 条最全 |
| SnowLuma `qq_face_map.py` | 适配器 | ⭐⭐ | **face 表有错位**，勿用于 face ID |
| Undefined `qq_emoji.py` | 社区 | ⭐⭐⭐ | 机制参考（JSON 覆盖） |
| 本插件实测（12951/379） | 实测 | ⭐⭐⭐ | 表情回应扩展 ID 的唯一来源 |

---

## 6. 相关文件索引

| 文件 | 内容 |
|------|------|
| `qq_face_napcat.json` | NapCat 表转 JSON（220 条，推荐基础源） |
| `qq_face_snowluma.json` | SnowLuma 表转 JSON（含错位标注） |
| `qq_face_official.json` | QQ 官方文档列表转 JSON |
| `emoji_reaction_extra.json` | 表情回应扩展 ID（12951/379）手动维护表（示例） |
| `merge_emoji_maps.py` | 合并工具：多源合并 + id→名称反转 + JSON 覆盖加载 |
