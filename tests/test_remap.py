# -*- coding: utf-8 -*-
"""端到端迁移校验：真实 tpac -> 路径重映射 -> 落盘 -> 重新解析并检查结构完整。"""
from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tpac_core import (  # noqa: E402
    MappingRule, Remapper, TpacError, load_tpac, save_tpac,
    scan_strings, looks_like_path,
)

GAME_DIR = r"E:\SteamLibrary\steamapps\common\Mount & Blade II Bannerlord"
SAMPLE = os.path.join(
    GAME_DIR, "Modules", "MercenaryVariety", "Assets", "rome_items",
    "mv_armor_coat_geo.tpac",
)
OTHER = os.path.join(
    GAME_DIR, "Modules", "KotK_GT_CarbonBody", "Assets", "body_parts_geo.tpac",
)


def show_strings(pkg, tag):
    hits = []
    for item in pkg.items:
        for _s, text in scan_strings(item.metadata):
            if "$BASE" in text or looks_like_path(text):
                hits.append((item.name, text))
    print("  [%s] 命中的路径串：%d" % (tag, len(hits)))
    for name, text in hits[:6]:
        print("      %-28s %s" % (name[:28], text))
    return hits


def verify(path):
    """重新解析并验证结构可用。"""
    pkg = load_tpac(path)
    for item in pkg.items:
        for seg in item.segments:
            data = seg.get_data()
            if len(data) != seg.actual_size:
                raise TpacError("段解压长度不符：%s" % item.name)
    n = len(pkg.items)
    pkg.close()
    return n


def main():
    failures = 0
    with tempfile.TemporaryDirectory() as tmp:
        for src in (SAMPLE, OTHER):
            if not os.path.exists(src):
                print("跳过（不存在）：%s" % src)
                continue
            print("\n=== %s ===" % os.path.relpath(src, GAME_DIR))

            pkg = load_tpac(src)
            before = show_strings(pkg, "迁移前")
            original_items = len(pkg.items)

            # 变长规则：换掉被锁死的模块路径
            rules = [
                MappingRule("$BASE/Modules/MercenaryVariety/", "$BASE/Modules/TargetMod/"),
                MappingRule("$BASE/Modules/GT_CarbonBody/", "$BASE/Modules/TargetMod/"),
            ]
            remapper = Remapper(rules)
            changed = remapper.rewrite_package(pkg)
            show_strings(pkg, "迁移后")
            print("  改写处数：%d" % changed)
            for stat in remapper.stats:
                print("      %-12s %-10s %s" % (stat.kind, stat.item[:10], stat.rule))
            for msg in remapper.skipped:
                print("      [跳过] %s" % msg)

            out = os.path.join(tmp, os.path.basename(src))
            save_tpac(pkg, out)
            pkg.close()

            n = verify(out)
            print("  重新解析：items=%d（原 %d），大小 %d -> %d"
                  % (n, original_items, os.path.getsize(src), os.path.getsize(out)))
            if n != original_items:
                print("  !! item 数量不一致")
                failures += 1
            if not before:
                print("  !! 源文件里没找到可重映射的路径，规则未生效属正常")
            elif changed == 0:
                print("  !! 期望有改写，实际为 0")
                failures += 1

    print("\n失败项：%d" % failures)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
