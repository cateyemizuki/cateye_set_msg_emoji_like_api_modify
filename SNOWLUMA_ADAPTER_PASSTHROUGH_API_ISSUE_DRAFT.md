# Issue 草稿：为 MaiBot-SnowLuma-Adapter 增加通用 action 透传 API

> 整理日期：2026-09-03。供向 MaiBot-SnowLuma-Adapter 仓库提交 Feature Issue 使用。
> 仓库：https://github.com/Mai-with-u/MaiBot-SnowLuma-Adapter
> 提交入口：https://github.com/Mai-with-u/MaiBot-SnowLuma-Adapter/issues

---

## 标题建议

**feat: 增加 NapCat 风格通用 action 透传 API（`adapter.napcat.action.call`），打通生态插件对 SnowLuma 本体已实现动作的调用**

---

## Issue 正文（以下内容可直接粘贴）

### TL;DR

SnowLuma 本体已实现大量 OneBot/NapCat 扩展动作（如 `set_msg_emoji_like`），但适配器只注册了固定清单的 `@API`，下游插件无法触达。请求增加一个通用透传入口 `adapter.napcat.action.call`（与 NapCat 适配器同名同签名），内部直接委托给现有的 `_call_action()`，实现成本约 10 行，可一次性打通所有「面向 NapCat 适配器编写」的生态插件。

### 功能概述

在 `SnowLumaAdapterPlugin` 中注册一个公开 API：

```python
@API("adapter.napcat.action.call", description="调用任意 OneBot 动作", version="1", public=True)
async def api_action_call(self, action_name: str = "", params: Any = None) -> Dict[str, Any]:
    """透传调用 SnowLuma OneBot 风格动作（与 NapCat 适配器同名入口行为对齐）。"""
    normalized_action = str(action_name or "").strip()
    if not normalized_action:
        raise ValueError("action_name 不能为空")
    raw_params = params if isinstance(params, Mapping) else {}
    return await self._call_action(normalized_action, dict(raw_params))
```

要点：

- **签名与返回值与 NapCat 适配器完全对齐**（`MaiBot-Napcat-Adapter/apis/support.py:241-255` 的 `api_call_action(action_name, params)`，返回原始响应字典），调用方插件无需区分后端；
- 内部复用现有 `_call_action()`（`core.py:1077`，echo/future 机制与超时重连逻辑均已完善），无新增网络代码；
- 透传不做参数改写：`message_id` 等由 SnowLuma 本体校验（其 `f.messageId()` 明确允许负数 ID，见下方验证证据），适配器侧不要用 `_normalize_positive_id` 拦截。

### 动机与使用场景

1. **生态插件已存在对透传入口的硬依赖**。表情回应插件（`github.cateye.set-msg-emoji-like`，cateye_set_msg_emoji_like）的贴表情功能通过 `ctx.api.call("adapter.napcat.action.call", action_name="set_msg_emoji_like", params=...)` 下发（其 `plugin.py:53`、`plugin.py:470-492`）。该插件在 SnowLuma 环境下因入口缺失而无法发送表情回应。
2. **SnowLuma 本体能力 > 适配器注册面**。适配器当前注册 45 个固定 `@API`；SnowLuma 本体另实现了 `set_msg_emoji_like`、`set_essence_msg`、`fetch_emoji_like_users`、`fetch_emoji_like_summary` 等动作，逐个注册需持续发版，透传入口可一次性解决同类需求。
3. **与适配器自身定位一致**。`core.py:113-117` 注释已表明部分公开 API 是「供 ai_draw_plugin 等插件通过 SDK passthrough 调用，避免插件直连 NapCat」——通用透传是该思路的自然延伸。

### 现状分析

- MaiBot 的 `ctx.api.call` 按名称在全局 API 注册表精确解析（官方插件文档《组件装饰器》：注册表键为 `{plugin_id}.{name}@{version}`，唯一短名要求恰好命中 1 个候选）。未注册名称在 Host 层即失败，不会触达适配器。
- `adapter.napcat.*` 前缀是命名惯例而非路由规则；SnowLuma 适配器虽复用 NapCat 风格命名，但每个名字都必须显式 `@API` 注册。
- 适配器内部的 `_call_action()` 是私有方法，外部插件无法调用。

### 可行性验证证据（以 set_msg_emoji_like 为例，SnowLuma 本体 commit fb5f9b2）

| 验证点 | 结论 | 出处（SnowLuma 本体源码） |
|---|---|---|
| action 已实现 | ✅ `set_msg_emoji_like`，params `{message_id, emoji_id: string, set: bool=true}` | `packages/onebot/src/actions/extended.ts:956-967` |
| message_id 允许负数 | ✅ 注释明确「NEGATIVES ARE VALID（signed int32 hash）」 | `packages/onebot/src/action-kit.ts:225-229` |
| 真实协议调用（非空壳） | ✅ `ctx.setMsgEmojiLike` → `bridge.apis.interaction.setReaction(...)`，并本地记录回执 | `packages/onebot/src/instance-context.ts:125-137` |
| 返回结构 | ✅ `okResponse()` = `{status:'ok', retcode:0, data}` | `packages/onebot/src/types.ts:161-167` |
| 通知回推与 NapCat 同构 | ✅ `group_msg_emoji_like` 事件 payload 含 `likes:[{emoji_id,count}]`、`message_id`、`user_id` | `packages/onebot/src/event-converter/to-notice.ts:245-259` |

接收侧适配器已就绪：`group_msg_emoji_like` 通知已支持（`settings.py:502` 开关、`core.py:1719` 翻译函数），且原始 payload 已按 NapCat 兼容字段名 `napcat_notice_payload` 透传（`core.py:1459-1462`）。即：**接收链路已通，仅发送侧缺一个入口**。

### 兼容性与命名考量（请维护者定夺）

1. **与 NapCat 适配器同名的歧义风险**：MaiBot 短名解析要求「恰好命中 1 个候选」。若用户同时安装 NapCat 与 SnowLuma 两个适配器，短名 `adapter.napcat.action.call` 会命中 2 个候选而解析失败。两个选项：
   - **A（推荐）**：仍用同名 `adapter.napcat.action.call`。现有 NapCat 系插件零改动即可工作；双适配器共存的部署本就少见，且现状下双适配器也无法共用同一账号的消息 ID 命名空间（两边 message_id 哈希算法不同源，跨适配器贴表情本就无效）。
   - **B**：改用独立命名（如 `adapter.snowluma.action.call`）。彻底无歧义，但现有插件需增加回退逻辑。
2. **安全面**：`public=True` 与 NapCat 适配器行为对齐。如担心任意 action 暴露，可增加可选配置（如 `plugin.action_call_allowlist`，空 = 全放行）。
3. **错误传播**：SnowLuma 本体对未支持动作返回 `failedResponse(retcode, wording)`，透传后调用方可按 `status`/`retcode` 自行判定，与 NapCat 行为一致。

### 验收标准

1. `await ctx.api.call("adapter.napcat.action.call", action_name="set_msg_emoji_like", params={"message_id": <可为负的int>, "emoji_id": "12951", "set": True})` 返回 `{"status":"ok","retcode":0,...}`，且群内目标消息出现表情回应；
2. 负数 `message_id` 可正常使用；
3. WebSocket 未连接时抛出与现有 API 一致的 `RuntimeError("SnowLuma WebSocket 尚未连接")`；
4. 对本体未实现的 action，错误信息（wording）原样透传给调用方。

### 备选方案（若不接受通用透传）

仅注册专用 API，最小改动面：

```python
@API("adapter.napcat.message.set_msg_emoji_like", description="设置消息表情回应", version="1", public=True)
async def api_set_msg_emoji_like(self, **kwargs: Any) -> Dict[str, Any]:
    params = self._api_params(kwargs)  # core.py:130-138，已兼容 params 包装
    return await self._call_action("set_msg_emoji_like", {
        "message_id": self._normalize_int(params.get("message_id"), "message_id"),
        "emoji_id": str(params.get("emoji_id") or "").strip(),
        "set": bool(params.get("set", True)),
    })
```

但每增加一个能力都需发版；通用透传可一次覆盖 `set_essence_msg`、`fetch_emoji_like_*` 等尚未注册的全部动作。

### 环境

- 适配器：MaiBot-SnowLuma-Adapter manifest 0.9.0（`_manifest.json`）
- MaiBot 宿主：1.2.x（manifest `min_version: 1.2.0`）
- SnowLuma 本体：含 `set_msg_emoji_like` 的当前 main（验证时 commit fb5f9b2）
- 关联插件：cateye_set_msg_emoji_like 0.2.1（`github.cateye.set-msg-emoji-like`）

### 相关 Issue

- `qq_face_map.py` 表情 ID 映射整体错位问题（影响表情回应通知的表情名显示）将另行提交 Issue。

---

## 使用说明（提交前删除本节）

1. 复制「Issue 正文」以上内容到 GitHub Issue，标题用「标题建议」；
2. 若仓库有 Issue 模板（Bug/Feature 分表），选择 Feature 模板并把正文填入；
3. 「兼容性与命名考量」第 1 点是维护者最可能追问的决策点，建议在 Issue 中主动列出 A/B 选项；
4. 证据表格中的行号基于 SnowLuma 本体 commit `fb5f9b2` 与适配器 0.9.0 源码，提交时若版本更新请复核；
5. 可附截图：SnowLuma WebUI 调试台手动调用 `set_msg_emoji_like` 成功、群内表情回应生效的效果图，说服力更强。
