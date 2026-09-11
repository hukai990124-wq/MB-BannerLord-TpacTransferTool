# -*- coding: utf-8 -*-
"""运行时缓存（RuntimeDataCache）的定位与搬运。

背景：网格 / 贴图的真实数据不在 .tpac 里，而在模块根目录的
`RuntimeDataCache/<GUID>.rdc`，文件名 GUID = tpac 头部第 8~24 字节。
只搬包不搬缓存，结果是装备能进游戏、能装备、日志里也有渲染请求，
但模型一片空白且一句报错都没有——所以这条链路必须有回归锁住。

覆盖：
  [1] 头部 GUID -> 缓存文件名（.NET Guid 字节序 + 统一大写 + .rdc）
  [2] 在源模块里定位缓存（含扩展名大小写不一的兜底）
  [3] 缓存永远落目标模块**根目录**，不跟随 keep_relative
  [4] 真实模块（MCV）的命中规律：除材质包外全部命中
  [5] 端到端：迁移真的把 .rdc 搬过去，回滚能清干净
"""
from __future__ import annotations

import os
import shutil
import struct
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from migrator import (  # noqa: E402
    MigrateOptions, cache_target_path, find_runtime_cache, rollback, run_batch,
)
from tpac_core import cache_file_name, cache_guid_of  # noqa: E402

GAME_DIR = r"E:\SteamLibrary\steamapps\common\Mount & Blade II Bannerlord"
REAL_MOD = os.path.join(GAME_DIR, "Modules", "MercenaryVariety")

# 造一个合法头部：magic + version + 16 字节 package guid（.NET 小端布局）
RAW_GUID = bytes.fromhex("112233445566778899AABBCCDDEEFF00")
WANT_GUID = "44332211-6655-8877-99AA-BBCCDDEEFF00"


def norm(p: str) -> str:
    return os.path.normcase(os.path.normpath(p))


def make_tpac(path: str, guid: bytes = RAW_GUID) -> None:
    """写一个只够解析头部的假 tpac（本测试不解析 TOC）。"""
    with open(path, "wb") as fh:
        fh.write(struct.pack("<II", 0x43415054, 2))
        fh.write(guid)
        fh.write(struct.pack("<II", 0, 0))
        fh.write(struct.pack("<I", 0))
        fh.write(b"\x00" * 64)


def make_module(root: str, module_id: str = "") -> None:
    os.makedirs(os.path.join(root, "Assets", "grp"), exist_ok=True)
    os.makedirs(os.path.join(root, "RuntimeDataCache"), exist_ok=True)
    if module_id:
        with open(os.path.join(root, "SubModule.xml"), "w", encoding="utf-8") as fh:
            fh.write("<Module><Id value=\"%s\"/></Module>" % module_id)


def main() -> int:
    failures = 0
    tmp = tempfile.mkdtemp(prefix="tpac_cache_")
    try:
        src_mod = os.path.join(tmp, "Modules", "FakeSrc")
        make_module(src_mod, "FakeSrc")
        tpac = os.path.join(src_mod, "Assets", "grp", "a_geo.tpac")
        make_tpac(tpac)

        # --- [1] GUID -> 文件名 ---
        print("[1] 头部 GUID -> 缓存文件名")
        got = cache_file_name(tpac)
        print("    期望: %s.rdc" % WANT_GUID)
        print("    实际: %s" % got)
        if got != WANT_GUID + ".rdc":
            print("    !! 文件名规则不对（大小写 / 字节序 / 扩展名）")
            failures += 1
        if cache_guid_of(tpac) != WANT_GUID:
            print("    !! GUID 字节序不对（.NET Guid 前 3 段是小端）")
            failures += 1

        # --- [2] 源模块里的定位 ---
        print("[2] 在源模块 RuntimeDataCache/ 里定位")
        if find_runtime_cache(tpac) != "":
            print("    !! 缓存还不存在，却报告找到了")
            failures += 1
        cache_path = os.path.join(src_mod, "RuntimeDataCache", WANT_GUID + ".rdc")
        with open(cache_path, "wb") as fh:
            fh.write(b"RDC-BODY" * 128)
        got = find_runtime_cache(tpac)
        print("    期望: %s" % norm(cache_path))
        print("    实际: %s" % norm(got or "(空)"))
        if norm(got) != norm(cache_path):
            print("    !! 没能定位到缓存，迁移会漏搬")
            failures += 1

        # 扩展名大小写不一的兜底：历史版本的工具曾写出 .rDC
        os.rename(cache_path, cache_path[:-4] + ".rDC")
        if norm(find_runtime_cache(tpac)) != norm(cache_path):
            print("    !! 扩展名大小写变体未能识别")
            failures += 1
        os.rename(cache_path[:-4] + ".rDC", cache_path)

        # --- [3] 目标路径固定在模块根 ---
        print("[3] 缓存落点必须是目标模块根目录，不跟随 keep_relative")
        nested_target = os.path.join(tmp, "Modules", "Dst", "Assets", "grp")
        want = os.path.join(tmp, "Modules", "Dst", "RuntimeDataCache",
                            WANT_GUID + ".rdc")
        got = cache_target_path(tpac, nested_target)
        print("    期望: %s" % norm(want))
        print("    实际: %s" % norm(got))
        if norm(got) != norm(want):
            print("    !! 缓存被塞进 Assets 层里，引擎按模块根去查是查不到的")
            failures += 1

        # --- [4] 真实模块的命中规律 ---
        print("[4] 真实模块命中规律：%s" % REAL_MOD)
        if os.path.isdir(REAL_MOD):
            hits = misses_by_mtl = unexpected = total = 0
            mtl_total = 0
            for dirpath, _dirs, files in os.walk(os.path.join(REAL_MOD, "Assets")):
                for name in files:
                    if not name.lower().endswith(".tpac"):
                        continue
                    total += 1
                    found = find_runtime_cache(os.path.join(dirpath, name))
                    is_mtl = "mtl" in name.lower()
                    if found:
                        hits += 1
                        if is_mtl:
                            mtl_total += 1
                    elif is_mtl:
                        misses_by_mtl += 1
                    else:
                        unexpected += 1
                        print("    !! 非材质包却没有缓存：%s" % name)
            print("    共 %d 个包：命中 %d，材质包无缓存 %d，非材质包缺缓存 %d"
                  % (total, hits, misses_by_mtl, unexpected))
            if not total:
                print("    !! 一个 tpac 都没扫到，路径可能不对")
                failures += 1
            if unexpected:
                print("    !! 有非材质包缺缓存，说明判据或路径有问题")
                failures += 1

            # --- [5] 端到端：搬 + 回滚 ---
            print("[5] 端到端搬运与回滚")
            sample = os.path.join(REAL_MOD, "Assets", "vaegir_items",
                                  "vaegir_lord_helm_geo.tpac")
            if os.path.isfile(sample) and find_runtime_cache(sample):
                dst_mod = os.path.join(tmp, "Modules", "Dst2")
                os.makedirs(dst_mod, exist_ok=True)
                res = run_batch([sample], dst_mod, [],
                                MigrateOptions(target_module="Dst2", verify=False),
                                log=lambda _m: None)[0]
                print("    状态=%s 缓存状态=%s" % (res.status, res.cache_status))
                if res.status != "ok" or res.cache_status != "copied":
                    print("    !! 迁移没把缓存搬过去")
                    failures += 1
                dst_cache = os.path.join(dst_mod, "RuntimeDataCache",
                                         os.path.basename(res.cache_dst))
                if not os.path.isfile(dst_cache):
                    print("    !! 目标模块里没有缓存文件：%s" % norm(dst_cache))
                    failures += 1
                else:
                    print("    已落盘：%s（%d 字节）"
                          % (norm(dst_cache), os.path.getsize(dst_cache)))

                # 回滚必须连缓存一起清掉，否则目标模块里会攒一堆没人认领的 .rdc
                rollback(dst_mod, log=lambda _m: None)
                if os.path.exists(dst_cache):
                    print("    !! 回滚后缓存还留着")
                    failures += 1
                leftovers = [n for n in os.listdir(
                    os.path.join(dst_mod, "Assets", "vaegir_items"))
                    if n.startswith("vaegir_lord_helm_geo")]
                if leftovers:
                    print("    !! 回滚后 tpac 还留着：%s" % leftovers)
                    failures += 1
                if not os.path.exists(dst_cache) and not leftovers:
                    print("    回滚干净：缓存与 tpac 都已清理")

                # 重复迁移：缓存内容一致时应当直接判定"已存在"，不重复拷几十 MB。
                # 这里换个独立目录，免得 journal 被第二次运行覆盖后影响上面的回滚断言。
                dst_mod2 = os.path.join(tmp, "Modules", "Dst3")
                os.makedirs(dst_mod2, exist_ok=True)
                for run in (1, 2):
                    again = run_batch(
                        [sample], dst_mod2, [],
                        MigrateOptions(target_module="Dst3", verify=False),
                        log=lambda _m: None)[0]
                    print("    第 %d 次迁移：缓存状态=%s" % (run, again.cache_status))
                    want = "copied" if run == 1 else "same"
                    if again.cache_status != want:
                        print("    !! 期望 %s，实际 %s" % (want, again.cache_status))
                        failures += 1
            else:
                print("    跳过：找不到 MCV 的 vaegir_lord_helm_geo 样本")
        else:
            print("[4] 跳过：本机没有装 MCV 模块")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n失败项：%d" % failures)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
