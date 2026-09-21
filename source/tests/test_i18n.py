# -*- coding: utf-8 -*-
"""
test_i18n.py -- 语言表自检。

不依赖真实 tpac，纯静态检查，跑得很快。防的是几种低级错误：
  1. 加了文案只给了一门语言（另一门会静悄悄回退成中文，很难发现）
  2. 多语种之间的占位符对不上（运行时才会炸 TypeError / KeyError）
  3. detect_lang 在中文/日文/英文系统上选错语言（v1.2 修复回归点）

v1.1+ 适配三语（zh / en / ja）：所有 STRINGS key 都必须三语齐备、两两占位符一致。
"""
import os
import re
import sys
import ctypes
from itertools import combinations
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import i18n  # noqa: E402

PLACEHOLDER = re.compile(r"%\((\w+)\)")


def placeholders(text: str):
    return tuple(sorted(PLACEHOLDER.findall(text)))


def main() -> int:
    problems = []

    for key, table in sorted(i18n.STRINGS.items()):
        # 1. 三语齐备
        for lang in i18n.LANGS:
            text = table.get(lang, "").strip()
            if not text:
                problems.append("%s 缺少 %s 文案" % (key, lang))
                continue
            # 防占位：把 ja 写成 key 自身
            if text == key:
                problems.append("%s[%s] 未翻译（值等于 key）" % (key, lang))

        # 2. 占位符两两一致（zh-en、zh-ja、en-ja 全要验）
        sigs = {lang: placeholders(table.get(lang, "")) for lang in i18n.LANGS}
        for a, b in combinations(i18n.LANGS, 2):
            if sigs[a] != sigs[b]:
                problems.append("%s 占位符不一致：%s=%s, %s=%s"
                                % (key, a, sigs[a], b, sigs[b]))

        # 3. 混用命名占位符和 %s/%d 会在运行时报错
        for lang, text in table.items():
            stripped = PLACEHOLDER.sub("", text)
            if re.search(r"%[sd]", stripped):
                problems.append("%s(%s) 混用了匿名占位符：%s" % (key, lang, text))

    # 4. 每种语言下逐条渲染一遍，确保 % 格式化不会抛异常
    for lang in i18n.LANGS:
        i18n.set_lang(lang)
        for key, table in i18n.STRINGS.items():
            text = table[lang]
            args = {name: 1 for name in placeholders(text)}
            try:
                rendered = i18n.tr(key, **args)
            except Exception as exc:  # noqa: BLE001
                problems.append("%s[%s] 渲染失败：%s" % (key, lang, exc))
                continue
            if "%(" in rendered:
                problems.append("%s[%s] 占位符未替换：%s" % (key, lang, rendered))

    i18n.set_lang("zh")

    # 5. detect_lang 在各系统下选对语言（v1.2 回归点）
    #    历史教训：之前 zh-CN 被识别成 ja 是因为 Windows API 主语言判断方向反了。
    #    用 mock 注入 API 返回值，不依赖真实 OS。
    detect_cases = [
        # (Windows UI Language ID, 期望语言, 描述)
        (0x0804, "zh", "zh-CN 简体中文"),
        (0x0404, "zh", "zh-TW 繁体中文"),
        (0x0C04, "zh", "zh-HK 香港"),
        (0x1004, "zh", "zh-SG 新加坡"),
        (0x0411, "ja", "ja-JP 日本語"),
        (0x0409, "en", "en-US English"),
        (0x0809, "en", "en-GB British"),
        (0x0000, "en", "未知 ID 兜底到 en"),
    ]
    for lang_id, expected, desc in detect_cases:
        with mock.patch.object(ctypes.windll.kernel32,
                               "GetUserDefaultUILanguage",
                               return_value=lang_id):
            got = i18n.detect_lang()
        if got != expected:
            problems.append("detect_lang(WinAPI=0x%04X %s) -> %s，期望 %s"
                            % (lang_id, desc, got, expected))

    if problems:
        print("发现问题 %d 处：" % len(problems))
        for item in problems:
            print("  -", item)
        return 1

    print("语言表检查通过：%d 条文案 × %d 门语言，占位符一致且均可渲染" %
          (len(i18n.STRINGS), len(i18n.LANGS)))
    print("detect_lang 检测：%d 个系统 ID 全部选对" % len(detect_cases))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
