# Issue 草稿：MaiBot-SnowLuma-Adapter 表情映射表（qq_face_map.py）存在整体错位

> 整理日期：2026-08-27。供向 MaiBot-SnowLuma-Adapter 仓库提交 Issue 使用。
> 仓库：https://github.com/Mai-with-u/MaiBot-SnowLuma-Adapter

---

## 标题建议

**bug: qq_face_map.py 的 QQ_FACE_DESCRIPTIONS 表情 ID 映射整体错位，导致表情回应通知显示错误表情名**

## 问题描述

`snowluma_adapter/qq_face_map.py` 的 `QQ_FACE_DESCRIPTIONS` 字典中，**大量经典 QQ 表情的 ID 映射存在整体偏移**，与 QQ 官方标准不一致。这会导致：
1. `_build_emoji_like_notice_text()`（`core.py:1731`）把表情回应通知里的 `emoji_id` 解析成**错误的表情名**；
2. 例如对一条消息贴「赞」（正确 ID=76），通知却显示为「示爱」等错误表情。

## 复现方式

1. 在 `qq_face_map.py` 中对比 `QQ_FACE_DESCRIPTIONS` 与 QQ 官方表情 ID：
   - 官方：`76` = 赞、`66` = 爱心、`63` = 玫瑰、`78` = 握手、`79` = 胜利
   - SnowLuma：`76` = 示爱、`66` = 礼物、`63` = 凋谢、`78` = 抱拳、`79` = 勾引
2. 或直接调用：`QQ_FACE_DESCRIPTIONS.get("76")` → 返回「示爱」（应为「赞」）。

## 影响范围

- 表情回应通知（`group_msg_emoji_like`）的表情名显示错误；
- 依赖 `QQ_FACE_DESCRIPTIONS` 的其它功能（如 `core.py:2044` 的 face 描述解析）同样受影响。

## 根因分析

`QQ_FACE_DESCRIPTIONS` 的 key 与标准 QQ face ID 存在**系统性偏移**。经与 [QQ 官方机器人文档 Emoji 列表](https://bot.q.qq.com/wiki/develop/nodesdk/model/emoji.html) 和 NapCat 适配器 `qq_emoji_list.py` 比对，SnowLuma 表的常见错位模式：
- **整体偏移约 1~2 位**：如标准 63=玫瑰，SnowLuma 却在 62=玫瑰、63=凋谢；
- **部分区间完全错位**：标准 96-109 区间（冷汗/擦汗/抠鼻/鼓掌/糗大了/坏笑/左哼哼/右哼哼/哈欠/鄙视/委屈/快哭了/阴险/左亲亲/吓/可怜）在 SnowLuma 中整体提前，如标准 96=冷汗 → SnowLuma 96=鼓掌、标准 97=擦汗 → SnowLuma 97=糗大了。
- 标准 116-125（示爱/抱拳/勾引/拳头/差劲/NO/OK/转圈）在 SnowLuma 中错位为 116=拳头…125=挥手。

## 错误明细（50 处，以官方/NapCat 为权威）

| ID | 正确（官方/NapCat） | SnowLuma 当前值 |
|----|---------------------|-----------------|
| 1 | 惊讶 | 撇嘴 |
| 18 | 睡 | 抓狂 |
| 19 | 大哭 | 吐 |
| 63 | 玫瑰 | 凋谢 |
| 64 | 凋谢 | 爱心 |
| 66 | 爱心 | 礼物 |
| 67 | 心碎 | 右哼哼 |
| 74 | 太阳 | 篮球 |
| 75 | 月亮 | 乒乓 |
| 76 | 赞 | 示爱 |
| 77 | 踩 | 瓢虫 |
| 78 | 握手 | 抱拳 |
| 79 | 胜利 | 勾引 |
| 96 | 冷汗 | 鼓掌 |
| 97 | 擦汗 | 糗大了 |
| 98 | 抠鼻 | 坏笑 |
| 99 | 鼓掌 | 左哼哼 |
| 100 | 糗大了 | 哈欠 |
| 101 | 坏笑 | 鄙视 |
| 102 | 左哼哼 | 委屈 |
| 103 | 右哼哼 | 快哭了 |
| 104 | 哈欠 | 阴险 |
| 105 | 鄙视 | 亲亲 |
| 106 | 委屈 | 吓 |
| 107 | 快哭了 | 可怜 |
| 108 | 阴险 | 菜刀 |
| 109 | 左亲亲 | 啤酒 |
| 116 | 示爱 | 拳头 |
| 118 | 抱拳 | 爱你 |
| 119 | 勾引 | 不 |
| 120 | 拳头 | 好 |
| 121 | 差劲 | 转圈 |
| 122 | 爱你 | 磕头 |
| 123 | NO | 回头 |
| 124 | OK | 跳绳 |
| 125 | 转圈 | 挥手 |
| 129 | 挥手 | 左太极 |
| 137 | 鞭炮 | 邮件 |
| 144 | 喝彩 | 下面 |
| 146 | 爆筋 | 飞机 |
| 147 | 棒棒糖 | 开车 |
| 169 | 手枪 | 无奈 |
| 171 | 茶 | 小纠结 |
| 172 | 眨眼睛 | 喷血 |
| 173 | 泪奔 | 斜眼笑 |
| 174 | 无奈 | doge |
| 175 | 卖萌 | 惊喜 |
| 176 | 小纠结 | 骚扰 |
| 177 | 喷血 | 笑哭 |
| 178 | 斜眼笑 | 我最美 |

> 另有部分 ID 两个表都缺失或名称不同（如 119/121/122/123/124/125 官方为 NO/OK/爱你/转圈等）。

## 建议修复

1. 以 [QQ 官方机器人文档 Emoji 列表](https://bot.q.qq.com/wiki/develop/nodesdk/model/emoji.html) 为准重写 `QQ_FACE_DESCRIPTIONS`（0~400 经典 face），可参考 NapCat 适配器的 `qq_emoji_list.py`（`QQ_FACE`，220 条，与官方一致）；
2. 增加 Unicode 表情映射（如 127801=玫瑰、128077=厉害），避免表情回应通知把 Unicode 表情当未知；
3. 建议补充单元测试，用「已知 ID → 期望名称」的样例防止回归。

## 环境

- MaiBot-SnowLuma-Adapter 仓库当前版本（manifest 0.9.0）
- 影响文件：`snowluma_adapter/qq_face_map.py`
- 复现相关：`snowluma_adapter/core.py:1731`（`_build_emoji_like_notice_text`）
