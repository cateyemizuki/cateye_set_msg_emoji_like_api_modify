# Issue 草稿：MaiBot-Napcat-Adapter 表情回应通知去重键错误（NapCat 插件 + SnowLuma 本体场景）

> 整理日期：2026-08-27。供向 MaiBot-Napcat-Adapter 仓库提交 Issue 使用。
> 仓库：https://github.com/Mai-with-u/MaiBot-Napcat-Adapter
>
> ⚠️ 实测环境：**NapCat 插件（maibot-team.napcat-adapter）连接 SnowLuma 适配器本体**（127.0.0.1:3001），
> 即「SnowLuma 本体 + NapCat 插件」组合。SnowLuma 插件（maibot-team.snowluma-adapter）已禁用。

---

## 标题建议

**bug: group_msg_emoji_like 通知去重键误用被回应消息 message_id，同一条消息 300 秒内多次贴表情被忽略**

## 问题描述

对**同一条消息**多次贴/取消表情回应时，只有第一次的通知能进入 MaiBot，后续全部被「忽略重复入站消息」丢弃。换一条新消息贴表情也一样：第一次成功，对该新消息再次贴表情（300 秒内）又被忽略。

复现步骤：
1. 对一条消息贴表情 A → 通知正常进入；
2. 对**同一条消息**改贴表情 B 或取消（300 秒内）→ 日志出现 `忽略重复入站消息: dedupe_key=gateway:maibot-team.napcat-adapter:napcat_gateway:<被回应消息ID>`，通知被丢弃；
3. 换群对**另一条消息**贴表情 → 第一次正常，再对该消息贴表情（300 秒内）同样被忽略。

日志示例：
```
[平台接入管理] 忽略重复入站消息: dedupe_key=gateway:maibot-team.napcat-adapter:napcat_gateway:-453293849
[平台接入管理] 忽略重复入站消息: dedupe_key=gateway:maibot-team.napcat-adapter:napcat_gateway:1140693177
```

## 根因分析

MaiBot 平台接入层（`src/platform_io/manager.py:480-484`）用 `dedupe_key` 做入站去重（TTL 300 秒），
NapCat 适配器在 `route_notice_payload` 中传 `dedupe_key`（`runtime/router.py:198-204`），
去重键由 `build_notice_dedupe_key` 构造（`codecs/notice/message_codec.py:92-103`）：

```python
def build_notice_dedupe_key(self, payload):
    external_message_id = str(payload.get("message_id") or "").strip()
    if external_message_id:
        return external_message_id        # ← 问题：表情回应通知的 message_id 是被回应消息的 ID
    ...
```

**`group_msg_emoji_like` 通知的 `payload["message_id"]` 是被回应消息的 ID**（如 `-453293849`），
不是「一次表情回应事件」的唯一标识。因此：
- 同一条被回应消息的多次表情回应事件（不同表情、取消/重贴、不同用户）产生**相同的去重键**；
- 在 300 秒 TTL 窗口内，除第一次外的所有表情回应通知都被框架误判为「重复入站」而丢弃。

普通消息的 `message_id` 每条唯一，不受影响；但**通知（尤其表情回应）的 `message_id` 复用了被引用消息的 ID**，语义不同。

## 补充观察（为何早期正常、后期才触发）

同一环境早期（双插件并存：NapCat 插件 + SnowLuma 插件都注入通知）时无此问题：
- SnowLuma 插件的通知去重键是 **payload 摘要**（`snowluma_adapter/core.py:1500-1508`，
  `notice:{type}:{sub_type}:{sha256[:16]}`），不同表情摘要不同 → 不被误去重；
- 禁用 SnowLuma 插件、仅剩 NapCat 插件后，去重键退化为**被回应消息 ID** → 问题暴露。

说明：**通知去重键应能区分「同一消息上的不同表情回应事件」**，NapCat 插件当前实现不满足。

## 建议修复

`build_notice_dedupe_key` 对 `group_msg_emoji_like`（及语义类似的 notice）不应使用
`payload["message_id"]`，应改用能唯一标识「一次表情回应事件」的键，例如：

```python
# 方案 A：notice_type + sub_type + payload 摘要（参考 SnowLuma 插件实现）
import hashlib
import json

def build_notice_dedupe_key(self, payload):
    notice_type = str(payload.get("notice_type") or "").strip()
    if notice_type == "group_msg_emoji_like":
        stable = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
        digest = hashlib.sha256(stable.encode("utf-8")).hexdigest()[:16]
        sub_type = str(payload.get("sub_type") or "event").strip()
        return f"notice:{notice_type}:{sub_type}:{digest}"
    external_message_id = str(payload.get("message_id") or "").strip()
    if external_message_id:
        return external_message_id
    ...
```

或对**所有通知事件统一使用 `notice:{type}:{sub_type}:{payload_digest}`**
（`build_payload_digest` 已在 `codecs/notice/helpers.py` 提供），避免任何通知复用消息 ID 导致误去重。

## 环境

- MaiBot 1.2.3
- MaiBot-Napcat-Adapter（当前版本）；**连接 SnowLuma 适配器本体**（127.0.0.1:3001）
- 影响文件：
  - `codecs/notice/message_codec.py`（`build_notice_dedupe_key`，L92-103）
  - `runtime/router.py:198-204`（`route_notice_payload` 传 dedupe_key）
- 框架去重：`MaiBot/src/platform_io/manager.py:480-484`（TTL 300s，`MessageDeduplicator`）
- 参考（正确做法）：`MaiBot-SnowLuma-Adapter/snowluma_adapter/core.py:1500-1508`（摘要去重键）
