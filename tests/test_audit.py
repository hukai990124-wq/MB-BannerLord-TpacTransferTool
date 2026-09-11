"""缓存完整性审计 (cache_audit) 的回归测试。

跑前会自动构造一个临时源模块：含 4 个 tpac + 1 个 mtl 包 + 1 个故意缺缓存的
"数据完整但缓存缺失"包；并对 `cache_audit` 在源/目标两侧的判定都做校验。

测试不依赖游戏 Modules 目录，**隔离**运行；只读取 MCV 的真实 tpac 作为内容素材
（避免再造假包——tpac 头部 GUID 必须是真实 16 字节），写进 %TEMP%。
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import struct

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import migrator
from migrator import (
    CacheAuditResult, MigrateOptions, cache_audit, find_runtime_cache,
    runtime_cache_dir, run_batch,
)
from tpac_core import scan_package, needs_runtime_cache


REAL_MOD = r"E:\SteamLibrary\steamapps\common\Mount & Blade II Bannerlord\Modules\MercenaryVariety"
REAL_SRC = os.path.join(REAL_MOD, "Assets", "vaegir_items")
REAL_CACHE = os.path.join(REAL_MOD, "RuntimeDataCache")

failures = 0


def _norm(p: str) -> str:
    return os.path.normcase(os.path.normpath(p))


def _copytree(src: str, dst: str) -> None:
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copy2(src, dst)


def _write_submodule_xml(mod_dir: str, mod_id: str) -> None:
    with open(os.path.join(mod_dir, "SubModule.xml"), "w", encoding="utf-8") as fh:
        fh.write(
            f'<?xml version="1.0"?><Module>'
            f'<Id value="{mod_id}"/><Name value="{mod_id}"/>'
            f'<Version value="v1.0.0"/><ModuleCategory value="Singleplayer"/>'
            f'<DependedModules/><SubModules/></Module>'
        )


def setup():
    """建一个临时源模块：含 vaegir_items 全部 10 包 + 对应 .rdc + 一个空 .rdc。"""
    tmp = tempfile.mkdtemp(prefix="tpac_audit_")
    mod = os.path.join(tmp, "Modules", "Src")
    sub_assets = os.path.join(mod, "Assets", "vaegir_items")
    sub_cache = runtime_cache_dir(mod)
    os.makedirs(sub_assets, exist_ok=True)
    os.makedirs(sub_cache, exist_ok=True)
    _write_submodule_xml(mod, "Src")

    if not os.path.isdir(REAL_SRC):
        print("  ! 跳过：找不到真实 MCV 资源 %s" % REAL_SRC)
        return tmp, False

    # 全部 10 个 tpac + 全部 8 个真实 .rdc
    import glob
    for tpac in sorted(glob.glob(os.path.join(REAL_SRC, "*.tpac"))):
        _copytree(tpac, os.path.join(sub_assets, os.path.basename(tpac)))
    for rdc in sorted(glob.glob(os.path.join(REAL_CACHE, "*.rdc"))):
        _copytree(rdc, os.path.join(sub_cache, os.path.basename(rdc)))

    # 删掉其中一个 rdc，模拟"该有却没有"
    deleted = os.path.join(sub_cache, "0566A1FC-A449-4DAD-9443-1D54BE030C9E.rdc")
    if os.path.isfile(deleted):
        os.remove(deleted)
    return tmp, True


def teardown(tmp: str) -> None:
    shutil.rmtree(tmp, ignore_errors=True)


# ---------- 1) 基础审计：齐全 vs 缺失 vs 材质包 ----------
def test_audit_basics(tmp: str) -> None:
    global failures
    print("[1] cache_audit 基础判定")
    sources = [os.path.join(tmp, "Modules", "Src", "Assets", "vaegir_items", n)
               for n in os.listdir(os.path.join(tmp, "Modules", "Src", "Assets", "vaegir_items"))]
    sources = sorted(sources)
    audit = cache_audit(sources, "")
    print("  expected=%d material=%d present=%d miss=%d"
          % (audit.expected, audit.material, audit.present_source, audit.missing_source_count))
    if audit.material != 2:
        print("  !! 材质包数应为 2（vaegir_lord_helm_mtl + vaegir_captain_armor_material_mtl）"
              "，实得 %d" % audit.material); failures += 1
    if audit.expected != 8:
        print("  !! 应带缓存数应为 8，实得 %d" % audit.expected); failures += 1
    # 我们故意删掉了 0566A1FC 的 rdc
    if audit.missing_source_count != 1:
        print("  !! 源里应缺 1 个，实得 %d" % audit.missing_source_count); failures += 1
    if "0566A1FC-A449-4DAD-9443-1D54BE030C9E.rdc" not in audit.missing_source:
        print("  !! 缺失清单里没有 0566A1FC-… 实得 %s" % audit.missing_source); failures += 1
    if audit.present_source != 7:
        print("  !! 源里应齐全 7 个，实得 %d" % audit.present_source); failures += 1
    if not audit.is_complete_source == (audit.missing_source_count == 0):
        print("  !! is_complete_source 与 missing_source_count 不一致"); failures += 1


# ---------- 2) 目标侧校验：源里缺的，目标里无从谈起 ----------
def test_audit_target(tmp: str) -> None:
    global failures
    print("[2] 目标模块校验（不查源里就缺的）")
    src_mod = os.path.join(tmp, "Modules", "Src")
    dst_mod = os.path.join(tmp, "Modules", "Dst")
    # 先把目标也"预放"一份相同的 rdc（模拟"目标模块本来就有"）
    shutil.copytree(runtime_cache_dir(src_mod), runtime_cache_dir(dst_mod))
    sources = sorted([os.path.join(src_mod, "Assets", "vaegir_items", n)
                      for n in os.listdir(os.path.join(src_mod, "Assets", "vaegir_items"))])
    audit = cache_audit(sources, dst_mod)
    print("  target_checked=%s present_target=%d miss_target=%d"
          % (audit.target_checked, audit.present_target, audit.missing_target_count))
    if not audit.target_checked:
        print("  !! target_checked 应为 True"); failures += 1
    # 7 个源有 + 1 个源缺(0566A1FC) → 目标侧只查 7 个；7 个都应到位
    if audit.present_target != 7:
        print("  !! 目标应齐 7 个，实得 %d" % audit.present_target); failures += 1
    if audit.missing_target_count != 0:
        print("  !! 目标应缺 0 个（0566A1FC 是源里就缺的，不计入目标），实得 %d"
              % audit.missing_target_count); failures += 1


# ---------- 3) 真实跑批 + 完整性日志 ----------
def test_audit_logged(tmp: str) -> None:
    global failures
    print("[3] run_batch 后日志含完整性汇总行")
    src_mod = os.path.join(tmp, "Modules", "Src")
    dst_mod = os.path.join(tmp, "Modules", "Dst")
    if os.path.isdir(dst_mod):
        shutil.rmtree(dst_mod, ignore_errors=True)
    sources = sorted([os.path.join(src_mod, "Assets", "vaegir_items", n)
                      for n in os.listdir(os.path.join(src_mod, "Assets", "vaegir_items"))])
    captured = []
    results = run_batch(sources, dst_mod, [], MigrateOptions(verify=False, backup=False),
                        log=captured.append)
    if not any("缓存完整性" in line for line in captured):
        print("  !! 日志缺『缓存完整性』行"); failures += 1
    if not any("缺失 1" in line for line in captured):
        print("  !! 日志缺『缺失 1』行：")
        for l in captured: print("    " + l)
        failures += 1
    # 10 个包全应 ok（不阻断）
    if not all(r.status == "ok" for r in results):
        print("  !! 迁移没全部 ok：%s" % [r.status for r in results]); failures += 1


# ---------- 4) needs_runtime_cache 判定 ----------
def test_needs_cache() -> None:
    global failures
    print("[4] needs_runtime_cache 判定")
    from tpac_core import PackageReport
    cases = [
        ("mtl-only", {"Material": 1}, False),
        ("tex", {"c974cbcb-5f1c-49f6-9a32-2b5b6c92c2e8": 1}, True),
        ("geo", {"3eba3679-debd-4c7a-8634-f121f6325e33": 1, "Metamesh": 1}, True),
        ("empty", {}, True),
        ("mtl+geo", {"Material": 1, "Metamesh": 1}, True),
    ]
    for label, types, expected in cases:
        r = PackageReport(path="x", module="", size=0, version=2,
                          item_count=1, types=dict(types))
        got = needs_runtime_cache(r)
        if got != expected:
            print("  !! %s: expected %s, got %s" % (label, expected, got)); failures += 1


def main():
    print("=== test_audit.py ===")
    tmp, ok = setup()
    try:
        if not ok:
            print("未准备真实样本，跳过前 3 项")
        else:
            test_audit_basics(tmp)
            test_audit_target(tmp)
            test_audit_logged(tmp)
        test_needs_cache()
    finally:
        teardown(tmp)
    print()
    if failures:
        print("FAILED: %d 处" % failures)
        sys.exit(1)
    print("OK: 全部通过")


if __name__ == "__main__":
    main()
