# -*- coding: utf-8 -*-
"""
test_i18n.py -- 语言表自检。

不依赖真实 tpac，纯静态检查，跑得很快。防的是两种低级错误：
  1. 加了文案只给了一门语言（另一门会静悄悄回退成中文，很难发现）
  2. 中英文的占位符对不上（运行时才会炸 TypeError / KeyError）
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import i18n  # noqa: E402

PLACEHOLDER = re.compile(r"%\((\w+)\)")


def placeholders(text: str):
    return tuple(sorted(PLACEHOLDER.findall(text)))


def main() -> int:
    problems = []

    for key, table in sorted(i18n.STRINGS.items()):
        for lang in i18n.LANGS:
            if not table.get(lang):
                problems.append("%s 缺少 %s 文案" % (key, lang))
        zh, en = table.get("zh", ""), table.get("en", "")
        if placeholders(zh) != placeholders(en):
            problems.append("%s 中英文占位符不一致：%s vs %s"
                            % (key, placeholders(zh), placeholders(en)))
        # 混用命名占位符和 %s/%d 会在运行时报错，这里直接拦掉
        for lang, text in (("zh", zh), ("en", en)):
            stripped = PLACEHOLDER.sub("", text)
            if re.search(r"%[sd]", stripped):
                problems.append("%s(%s) 混用了匿名占位符：%s" % (key, lang, text))

    # 每种语言下逐条渲染一遍，确保 % 格式化不会抛异常
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

    if problems:
        print("发现问题 %d 处：" % len(problems))
        for item in problems:
            print("  -", item)
        return 1

    print("语言表检查通过：%d 条文案 × %d 门语言，占位符一致且均可渲染"
          % (len(i18n.STRINGS), len(i18n.LANGS)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
