# -*- coding: utf-8 -*-
"""QQ 表情映射合并工具。

功能：
1. 把 NapCat `qq_emoji_list.py` 的 QQ_FACE 转成 JSON（qq_face_napcat.json）；
2. 把 SnowLuma `qq_face_map.py` 的 QQ_FACE_DESCRIPTIONS 转成 JSON（qq_face_snowluma.json）；
3. 生成合并后的基础映射（以 NapCat 表为主，标注 SnowLuma 差异）；
4. 提供 JSON 覆盖加载函数（id -> 名称，Undefined 机制反向版），供插件使用。

用法：
    python merge_emoji_maps.py            # 生成各 JSON 文件
    python merge_emoji_maps.py --merge    # 生成合并映射 qq_face_merged.json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
NAPCAT_LIST = HERE.parent.parent / "MaiBot-Napcat-Adapter-main" / "qq_emoji_list.py"
SNOWLUMA_MAP = HERE.parent.parent / "MaiBot-SnowLuma-Adapter-main" / "qq_face_map.py"


def _extract_py_dict(text: str, dict_name: str) -> dict[str, str]:
    """从 Python 源码中提取名为 dict_name 的 dict 字面量（仅支持简单 str->str 项）。"""
    # 定位 dict 开始：兼容 "NAME: Dict[str, str] = {" / "NAME = {" 等写法
    patterns = [
        re.compile(rf"{re.escape(dict_name)}\s*:\s*(?:Dict|dict)\[[^\]]*\]\s*=\s*\{{"),
        re.compile(rf"{re.escape(dict_name)}\s*=\s*\{{"),
        re.compile(rf"{re.escape(dict_name)}\s*:\s*\{{"),
    ]
    start = -1
    for pat in patterns:
        m = pat.search(text)
        if m:
            start = m.start()
            brace = m.end() - 1  # 定位到 {
            break
    if start < 0:
        raise ValueError(f"未找到 {dict_name}")
    # 括号匹配
    depth = 0
    for i in range(brace, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                body = text[brace : i + 1]
                break
    else:
        raise ValueError(f"{dict_name} 括号不闭合")

    result: dict[str, str] = {}
    # 匹配 "key": "value"（key 可能带引号，value 可能是中文/符号）
    pattern = re.compile(r'"(\d+)"\s*:\s*"([^"]*)"')
    for m in pattern.finditer(body):
        key, value = m.group(1), m.group(2)
        result[key] = value
    return result


def load_napcat() -> dict[str, str]:
    text = NAPCAT_LIST.read_text(encoding="utf-8")
    face = _extract_py_dict(text, "QQ_FACE")
    # 去掉 "[表情：xxx]" 前缀，只留名称
    clean = {k: re.sub(r"^\[表情：", "", v).rstrip("]") for k, v in face.items()}
    return clean


def load_snowluma() -> dict[str, str]:
    text = SNOWLUMA_MAP.read_text(encoding="utf-8")
    return _extract_py_dict(text, "QQ_FACE_DESCRIPTIONS")


def load_official() -> dict[str, str]:
    """QQ 官方文档列表（手维护，来源 bot.q.qq.com Emoji 列表）。"""
    return {
        "1": "惊讶", "4": "得意", "5": "流泪", "6": "害羞", "7": "闭嘴",
        "8": "睡", "9": "大哭", "10": "尴尬", "11": "发怒", "12": "调皮",
        "13": "呲牙", "14": "微笑", "15": "难过", "16": "酷", "18": "睡",
        "19": "大哭", "21": "可爱", "23": "傲慢", "24": "饥饿", "25": "困",
        "26": "惊恐", "27": "流汗", "28": "憨笑", "29": "悠闲", "30": "奋斗",
        "32": "疑问", "33": "嘘", "34": "晕", "38": "敲打", "39": "再见",
        "41": "发抖", "42": "爱情", "43": "跳跳", "49": "拥抱", "53": "蛋糕",
        "60": "咖啡", "63": "玫瑰", "66": "爱心", "67": "心碎", "74": "太阳",
        "75": "月亮", "76": "赞", "78": "握手", "79": "胜利", "85": "飞吻",
        "89": "西瓜", "96": "冷汗", "97": "擦汗", "98": "抠鼻", "99": "鼓掌",
        "100": "糗大了", "101": "坏笑", "106": "委屈", "109": "左亲亲",
        "111": "可怜", "118": "抱拳", "120": "拳头", "122": "爱你", "123": "NO",
        "124": "OK", "125": "转圈", "129": "挥手", "201": "点赞", "212": "托腮",
        "262": "脑阔疼", "264": "捂脸", "268": "问号脸", "269": "暗中观察",
        "271": "吃瓜", "277": "汪汪", "319": "比心", "320": "庆祝", "326": "生气",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="QQ 表情映射合并工具")
    parser.add_argument("--merge", action="store_true", help="同时生成合并映射")
    args = parser.parse_args()

    napcat = load_napcat()
    snowluma = load_snowluma()
    official = load_official()

    (HERE / "qq_face_napcat.json").write_text(
        json.dumps(napcat, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (HERE / "qq_face_snowluma.json").write_text(
        json.dumps(snowluma, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (HERE / "qq_face_official.json").write_text(
        json.dumps(official, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"已生成：qq_face_napcat.json（{len(napcat)} 条）、qq_face_snowluma.json（{len(snowluma)} 条）、"
          f"qq_face_official.json（{len(official)} 条）")

    if args.merge:
        # 合并：NapCat 为主，官方校正，SnowLuma 仅补 NapCat 缺失的（且官方未否定的）
        merged = dict(napcat)
        for k, v in official.items():
            merged[k] = v  # 官方覆盖
        conflicts: dict[str, tuple[str, str]] = {}
        for k, v in snowluma.items():
            if k not in merged:
                merged[k] = v
            elif merged[k] != v:
                conflicts[k] = (merged[k], v)
        (HERE / "qq_face_merged.json").write_text(
            json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"已生成合并映射 qq_face_merged.json（{len(merged)} 条）")
        if conflicts:
            print(f"⚠️ 发现 {len(conflicts)} 处 SnowLuma 与权威不一致（已以权威为准）：")
            for k, (a, b) in sorted(conflicts.items(), key=lambda x: int(x[0])):
                print(f"  {k}: 权威={a!r} vs SnowLuma={b!r}")


if __name__ == "__main__":
    sys.exit(main())
