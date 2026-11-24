# QQ 表情映射

映射表为 `emoji_like` 提供名称、描述和情绪标签，也用于翻译收到的表情回应通知。多份映射中的同一个 ID 在检索时合并为一条。

| 文件 | 条目数 | 用途 |
|------|--------|------|
| `qq_face_merged.json` | 265 | 运行时基础映射。NapCat 为基础，官方摘录校正，SnowLuma 补充缺失 ID。 |
| `qq_face_napcat.json` | 219 | NapCat `QQ_FACE` 快照。 |
| `qq_face_official.json` | 73 | QQ 官方机器人文档摘录。 |
| `qq_face_snowluma.json` | 143 | SnowLuma `QQ_FACE_DESCRIPTIONS` 快照。 |
| `emoji_reaction_extra.json` | 5 | 扩展回应映射。包括 12951「祝(猪)」、379「点赞」和三枚默认精选表情。 |
| `emoji_reaction_custom.json` | 默认 0 | 用户自定义映射。 |

运行时依次加载合并表、扩展表、自定义表、`extra_paths` 指定的文件、环境变量 `QQ_EMOJI_EXTRA` 指向的文件。后加载的同 ID 条目可以更新名称、描述和标签，未提供的字段沿用前一层。旧配置 `description_library` 可以继续覆盖描述。

<a id="json-formats"></a>
## JSON 格式

以表情 ID 为键。推荐为每个条目填写 `name`、`description` 和 `emotion_tags`，可选填 `aliases`。

```json
{
  "379": {
    "name": "点赞",
    "description": "给对方一个赞，肯定想法或表现。",
    "emotion_tags": ["认可", "赞同", "鼓励"],
    "aliases": ["赞"]
  }
}
```

兼容旧的 `{"379": "点赞"}`、`{"emojis": [{"id": 379, "name": "点赞"}]}` 和纯列表 `[{"id": 379, "name": "点赞"}]`。

## 更新来源数据

`python merge_emoji_maps.py --merge` 读取同级工作区中的 `MaiBot-Napcat-Adapter-main/qq_emoji_list.py`、`MaiBot-SnowLuma-Adapter-main/qq_face_map.py` 和脚本中的官方摘录，重建三个来源快照及合并表。脚本根据 ID 和名称保留现有描述和情绪标签。遇到新增或改名的表情时，先在对应来源快照添加完整条目再重跑。

- 本地添加表情或修改描述，可参照 [扩展指南](EXTENSION_GUIDE.md)。
- SnowLuma 的部分经典 ID 与合并表的名称有差异。[SnowLuma 映射差异](SNOWLUMA_ISSUE_DRAFT.md)
