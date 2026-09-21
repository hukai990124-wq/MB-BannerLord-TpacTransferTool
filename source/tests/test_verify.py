# -*- coding: utf-8 -*-
"""写盘后自检（verify_segments）必须是**流式**的——解压一段、验一段、丢一段。

为什么单独立一个测试：`Segment.get_data()` 会把解压结果永久缓存进 `seg._data`。
最初的自检直接循环调它，结果把整包的段全留在内存里：2.8 GB 的
`AssetPackages/core_game.tpac`（23109 段）实测进程峰值 **4.6 GB**。
校验本身只需要"看一眼每段解压长度对不对"，根本不需要同时持有全部段。

所以这个测试锁两件事：
  1. 校验结论正确（段数、长度不符时要报错、错误里带资源名）；
  2. 校验结束后**没有任何段还留着解压数据**——这是"内存恒定"的结构性保证。
"""
from __future__ import annotations

import glob
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tpac_core import (  # noqa: E402
    STORAGE_RAW, AssetItem, MemorySource, Segment, TpacPackage, load_tpac,
    verify_segments,
)

GAME_DIR = r"E:\SteamLibrary\steamapps\common\Mount & Blade II Bannerlord"


def item(guid_byte: int, name: str, segs) -> AssetItem:
    return AssetItem(guid=bytes([guid_byte]) * 16, name=name, segments=list(segs))


def raw_seg(payload: bytes, offset: int = 0) -> Segment:
    return Segment(actual_size=len(payload), storage_size=len(payload),
                   source=MemorySource(payload), src_offset=offset,
                   storage_format=STORAGE_RAW)


def main() -> int:
    failures = 0

    # --- [1] 三段全部合格：应报 3、无错、且事后不留数据 ---
    s1, s2, s3 = (raw_seg(b"A" * 100), raw_seg(b"B" * 200),
                  raw_seg(b"C" * 300))
    pkg = TpacPackage(version=2, guid=b"\x09" * 16,
                      items=[item(1, "a_geo", [s1, s2]),
                             item(2, "b_geo", [s3])])
    checked, err = verify_segments(pkg)
    print("[1] 三段合格的包")
    print("    期望: 段数=3，无错误")
    print("    实际: 段数=%d，错误=%r" % (checked, err))
    if checked != 3 or err:
        print("    !! 校验结论不对")
        failures += 1

    leaked = [seg for seg in (s1, s2, s3) if seg._data is not None]
    print("[2] 校验后不应有任何段残留解压数据（内存恒定的关键）")
    print("    期望: 残留 0 段")
    print("    实际: 残留 %d 段" % len(leaked))
    if leaked:
        print("    !! 解压结果被缓存住了——大包会因此吃满内存")
        failures += 1

    # --- [3] 段长不符要报错，且错误里带上出问题的资源名 ---
    bad = raw_seg(b"D" * 50)
    bad.actual_size = 51          # 声明 51 字节，实际只有 50
    pkg2 = TpacPackage(version=2, guid=b"\x0a" * 16,
                       items=[item(1, "ok_geo", [raw_seg(b"E" * 10)]),
                              item(2, "broken_geo", [bad])])
    checked2, err2 = verify_segments(pkg2)
    print("[3] 段长不符必须报错")
    print("    期望: 有错误，且错误里出现 broken_geo")
    print("    实际: 段数=%d，错误=%r" % (checked2, err2))
    if not err2 or "broken_geo" not in err2:
        print("    !! 损坏的段没有被识别出来（或错误信息缺资源名）")
        failures += 1

    # --- [4] 真实文件回归：拿游戏里小 tpac 走一遍，段数应与实际段数一致 ---
    print("[4] 真实文件校验（若本机装了游戏）")
    sample = ""
    for cand in sorted(glob.glob(os.path.join(
            GAME_DIR, "Modules", "*", "**", "*.tpac"), recursive=True)):
        try:
            if 4096 <= os.path.getsize(cand) <= 1 << 20:
                sample = cand
                break
        except OSError:
            continue
    if not sample:
        print("    跳过：未找到合适的样本（游戏目录不存在）")
    else:
        real = load_tpac(sample)
        try:
            total = sum(len(it.segments) for it in real.items)
            got, e = verify_segments(real)
            rel = os.path.relpath(sample, GAME_DIR)
            print("    文件: %s" % rel[:70])
            print("    期望: 段数=%d，无错误" % total)
            print("    实际: 段数=%d，错误=%r" % (got, e))
            if got != total or e:
                print("    !! 真实文件校验不通过")
                failures += 1
            left = [s for it in real.items for s in it.segments
                    if s._data is not None]
            if left:
                print("    !! 真实文件校验后有 %d 段残留数据" % len(left))
                failures += 1
        finally:
            real.close()

    print("\n失败项：%d" % failures)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
