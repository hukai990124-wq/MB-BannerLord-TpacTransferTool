# -*- coding: utf-8 -*-
"""模块根定位与目标路径计算。

重点回归：来源模组不在 .../Modules/ 下时（例如直接放在桌面），
module_root_of 必须仍能定位模块根，否则 compute_target_path 会退化成
"只取文件名"，把 Assets/<子文件夹>/ 拍平到目标根目录——引擎只预载资源
目录下的根子文件夹，拍平后资源包一个都加载不到。
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from migrator import (  # noqa: E402
    compute_target_path, module_folder_name, module_root_of, name_alignment,
)

TARGET = r"E:\SteamLibrary\steamapps\common\Mount & Blade II Bannerlord\Modules\test_transe"
REAL_DESKTOP_MOD = r"C:\Users\75729\OneDrive\桌面\Vaegir Armoury"


def norm(p: str) -> str:
    return os.path.normcase(os.path.normpath(p))


def main() -> int:
    failures = 0
    tmp = tempfile.mkdtemp(prefix="tpac_paths_")
    try:
        # --- 造一棵"不在 Modules 下、但有 SubModule.xml"的模组树 ---
        root = os.path.join(tmp, "MyMod")
        os.makedirs(os.path.join(root, "Assets", "grp"))
        with open(os.path.join(root, "SubModule.xml"), "w", encoding="utf-8") as fh:
            fh.write("<Module><Id value=\"MyMod\"/></Module>")
        src = os.path.join(root, "Assets", "grp", "a_geo.tpac")
        open(src, "wb").close()

        got = module_root_of(src)
        print("[1] 非 Modules 来源的模块根")
        print("    期望: %s" % norm(root))
        print("    实际: %s" % norm(got or "(空)"))
        if norm(got) != norm(root):
            print("    !! 没能定位模块根，会被拍平")
            failures += 1

        rel = compute_target_path(src, TARGET, True)
        want_rel = os.path.join(TARGET, "Assets", "grp", "a_geo.tpac")
        print("[2] keep_relative=True 应保留层级")
        print("    期望: %s" % norm(want_rel))
        print("    实际: %s" % norm(rel))
        if norm(rel) != norm(want_rel):
            print("    !! 目录结构被拍平")
            failures += 1

        flat = compute_target_path(src, TARGET, False)
        want_flat = os.path.join(TARGET, "a_geo.tpac")
        print("[3] keep_relative=False 应只取文件名")
        print("    期望: %s" % norm(want_flat))
        print("    实际: %s" % norm(flat))
        if norm(flat) != norm(want_flat):
            print("    !! --flat 行为异常")
            failures += 1

        # --- 没有 SubModule.xml：按老行为退化，不应抛异常 ---
        lone = os.path.join(tmp, "Lone", "b_geo.tpac")
        os.makedirs(os.path.dirname(lone))
        open(lone, "wb").close()
        print("[4] 无 SubModule.xml 时安全退化")
        got2 = module_root_of(lone)
        print("    实际: %r" % got2)
        if got2 != "":
            print("    !! 期望空串")
            failures += 1
        if norm(compute_target_path(lone, TARGET, True)) != norm(
                os.path.join(TARGET, "b_geo.tpac")):
            print("    !! 退化路径不对")
            failures += 1

        # --- Modules 下的来源：老行为必须一字不变 ---
        mod_src = os.path.join(REAL_DESKTOP_MOD, "Assets", "va_norselord",
                               "Va_NorseLord_geo.tpac")
        if os.path.isfile(mod_src):
            got3 = module_root_of(mod_src)
            print("[5] 真实桌面模组 %s" % REAL_DESKTOP_MOD)
            print("    实际根: %s" % norm(got3 or "(空)"))
            if norm(got3) != norm(REAL_DESKTOP_MOD):
                print("    !! 真实场景定位失败")
                failures += 1
            real_rel = compute_target_path(mod_src, TARGET, True)
            want = os.path.join(TARGET, "Assets", "va_norselord",
                                "Va_NorseLord_geo.tpac")
            if norm(real_rel) != norm(want):
                print("    !! 真实场景未保留层级：%s" % norm(real_rel))
                failures += 1
        else:
            print("[5] 跳过：桌面 Vaegir Armoury 不在原位")

        # --- 文件夹名 vs 模块 Id 的一致性判定 ---
        # 背景：包内写死 `$BASE/Modules/<X>/AssetSources/...`，X 只能对上文件夹名或 Id
        # 之一。实测文件夹 test / Id test_transe 时，装备能进游戏、能装备，但模型一片
        # 空白且日志无报错 —— 所以不一致必须被判成"有问题"。
        bad = os.path.join(tmp, "folderA")
        os.makedirs(os.path.join(bad, "Assets", "grp"))
        with open(os.path.join(bad, "SubModule.xml"), "w", encoding="utf-8") as fh:
            fh.write("<Module><Id value=\"idB\"/></Module>")
        print("[6] 文件夹名 != Id 应判定为不一致")
        folder, declared, mismatch = name_alignment(bad)
        print("    文件夹=%r Id=%r 不一致=%s" % (folder, declared, mismatch))
        if not (folder == "folderA" and declared == "idB" and mismatch):
            print("    !! 未能识别名字冲突，用户会踩到无声失败")
            failures += 1
        if module_folder_name(bad) != "folderA":
            print("    !! 改写目标应取文件夹名，实际 %r" % module_folder_name(bad))
            failures += 1
        # 子目录也要能回溯到模块根
        if module_folder_name(os.path.join(bad, "Assets", "grp")) != "folderA":
            print("    !! 子目录回溯模块根失败")
            failures += 1

        same = os.path.join(tmp, "folderSame")
        os.makedirs(same)
        with open(os.path.join(same, "SubModule.xml"), "w", encoding="utf-8") as fh:
            fh.write("<Module><Id value=\"folderSame\"/></Module>")
        print("[7] 文件夹名 == Id 不应告警；无 SubModule.xml 也不应告警")
        if name_alignment(same)[2]:
            print("    !! 同名被误报为不一致")
            failures += 1
        if name_alignment(os.path.join(tmp, "Lone"))[2]:
            print("    !! 无 SubModule.xml 的纯资源目录被误报")
            failures += 1
        if module_folder_name(os.path.join(tmp, "Lone")) != "Lone":
            print("    !! 无 SubModule.xml 时应退化成文件夹名")
            failures += 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n失败项：%d" % failures)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
