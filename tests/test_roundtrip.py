# -*- coding: utf-8 -*-
"""字节级 round-trip 校验：解析真实 tpac -> 原样重建 -> 与原文件逐字节比对。

这一步用于证明格式理解正确。如果不一致，说明容器布局还有未知字段，
工具就不能安全改写文件。
"""
from __future__ import annotations

import glob
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tpac_core import build_tpac, load_tpac, parse_tpac, TpacError  # noqa: E402

GAME_DIR = r"E:\SteamLibrary\steamapps\common\Mount & Blade II Bannerlord"


MIN_SIZE = 2 * 1024      # 跳过几乎空的包
MAX_SIZE = 200 * 1024 * 1024  # 跳过 GB 级包，避免测试过慢


def find_samples(limit: int = 40) -> list:
    """按大小挑选有代表性的样本：覆盖多个模块，避开超大与空包。"""
    if not os.path.isdir(GAME_DIR):
        return []
    found = glob.glob(os.path.join(GAME_DIR, "Modules", "*", "**", "*.tpac"),
                      recursive=True)
    candidates = []
    for path in found:
        try:
            size = os.path.getsize(path)
        except OSError:
            continue
        if MIN_SIZE <= size <= MAX_SIZE:
            candidates.append((size, path))
    candidates.sort()

    picked, per_module = [], {}
    for size, path in candidates:
        rel = os.path.relpath(path, GAME_DIR)
        module = rel.split(os.sep)[1] if len(rel.split(os.sep)) > 1 else "?"
        if per_module.get(module, 0) >= 3:
            continue
        per_module[module] = per_module.get(module, 0) + 1
        picked.append(path)
        if len(picked) >= limit:
            break
    return picked


def first_diff(a: bytes, b: bytes) -> int:
    """分块定位首个差异字节，避免逐字节 Python 循环。"""
    n = min(len(a), len(b))
    lo = 0
    step = 1 << 20
    while lo < n:
        hi = min(lo + step, n)
        if a[lo:hi] == b[lo:hi]:
            lo = hi
            continue
        if step == 1:
            return lo
        step = max(1, step // 16)
    if len(a) != len(b):
        return n
    return -1


def main() -> int:
    samples = find_samples()
    if not samples:
        print("未找到样本，跳过（游戏目录不存在）")
        return 0

    ok = fail = 0
    print("样本数：%d\n" % len(samples))
    print("%-58s %10s %10s  %s" % ("文件", "原始大小", "重建大小", "结果"))
    print("-" * 100)

    for path in samples:
        rel = os.path.relpath(path, GAME_DIR)
        try:
            with open(path, "rb") as fh:
                original = fh.read()
            pkg = parse_tpac(original, path)
            rebuilt = build_tpac(pkg)
        except TpacError as exc:
            print("%-58s %10s %10s  ERROR %s" % (rel[:58], "-", "-", exc))
            fail += 1
            continue
        except Exception as exc:  # noqa: BLE001
            print("%-58s  UNEXPECTED %r" % (rel[:58], exc))
            fail += 1
            continue

        if rebuilt == original:
            ok += 1
            print("%-58s %10d %10d  OK" % (rel[:58], len(original), len(rebuilt)))
        else:
            fail += 1
            pos = first_diff(original, rebuilt)
            print("%-58s %10d %10d  MISMATCH @%d (0x%X)" %
                  (rel[:58], len(original), len(rebuilt), pos, pos))
            lo = max(0, pos - 16)
            print("      orig: %s" % original[lo:pos + 16].hex())
            print("      new : %s" % rebuilt[lo:pos + 16].hex())

    print("-" * 100)
    print("一致 %d / 不一致 %d" % (ok, fail))
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
