# -*- coding: utf-8 -*-
"""
migrator.py -- 迁移执行层（与界面无关，可单独用命令行调用）。

职责：
  * 发现 .tpac 文件
  * 根据扫描结果建议重映射规则
  * 计算目标路径、处理冲突、备份与回滚
  * 执行迁移并在写盘后做结构自检
  * 把每个 tpac 对应的 RuntimeDataCache/<GUID>.rdc 一并搬过去

用法（命令行）：
    python migrator.py --source <目录或文件> --target <目标模块目录> \
        --from MercenaryVariety --to MyMod [--dry-run] [--on-conflict rename]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import time
from dataclasses import dataclass, field, asdict
from typing import Callable, Dict, List, Optional, Sequence, Set

from i18n import LANGS, init_lang, tr
from tpac_core import (
    CACHE_DIR_NAME, MappingRule, PackageReport, Remapper, ScanOptions, TpacError,
    build_dependency_graph, cache_file_name, guid_str, load_tpac,
    needs_runtime_cache, save_tpac, scan_package,
)

JOURNAL_NAME = "_migration_journal.json"


# --------------------------------------------------------------------------
# 发现文件
# --------------------------------------------------------------------------

def discover_tpac(roots: Sequence[str]) -> List[str]:
    """从目录（递归）或文件路径收集 .tpac。"""
    found: List[str] = []
    for root in roots:
        root = os.path.abspath(root)
        if os.path.isdir(root):
            for dirpath, _dirs, files in os.walk(root):
                for name in files:
                    if name.lower().endswith(".tpac"):
                        found.append(os.path.join(dirpath, name))
        elif os.path.isfile(root) and root.lower().endswith(".tpac"):
            found.append(root)
    return sorted(set(found))


def module_root_of(path: str) -> str:
    """返回模块根目录；定位不到则返回空串。

    先按 .../Modules/<ModuleName> 惯例切分。来源不在 Modules 下时（例如模组直接
    放在桌面上），退化为向上查找 SubModule.xml 来定位模块根——否则调用方只能
    取文件名，会把源目录结构静默拍平，迁移出来的资源包层级就不对了。
    """
    norm = os.path.abspath(path).replace("\\", "/")
    marker = "/Modules/"
    pos = norm.rfind(marker)
    if pos >= 0:
        parts = norm[pos + len(marker):].split("/")
        if not parts:
            return ""
        return norm[:pos + len(marker)] + parts[0]

    cur = os.path.dirname(norm)
    while cur and cur != os.path.dirname(cur):
        if os.path.isfile(os.path.join(cur, "SubModule.xml")):
            return cur
        cur = os.path.dirname(cur)
    return ""


def module_id_of(path: str) -> str:
    """读取该路径所属模块在 SubModule.xml 里声明的 <Id>；读不到返回空串。

    为什么不能用文件夹名：引擎解析包内的 `$BASE/Modules/<X>/...` 时用的是模块
    声明的 Id，而不是它所在的文件夹。实测样本——创意工坊模块文件夹叫
    `2859238197`，Id 是 `Bannerlord.MBOptionScreen`，它包内写的就是后者。
    所以规则的目标模块名必须等于 Id，写文件夹名会让包内路径指向一个不存在
    的模块。
    """
    root = module_root_of(os.path.join(path, "x"))
    if not root:
        return ""
    xml = os.path.join(root, "SubModule.xml")
    if not os.path.isfile(xml):
        return ""
    try:
        import xml.etree.ElementTree as ET
        node = ET.parse(xml).getroot().find("Id")
        if node is not None and (node.get("value") or "").strip():
            return node.get("value").strip()
    except Exception:  # noqa: BLE001  原 mod 的 SubModule.xml 可能有笔误
        pass
    try:
        text = open(xml, encoding="utf-8-sig", errors="replace").read()
    except OSError:
        return ""
    found = re.search(r"<Id\s+value\s*=\s*\"([^\"]+)\"", text)
    return found.group(1).strip() if found else ""


def module_folder_name(path: str) -> str:
    """该路径所属模块的**文件夹名**（不是 Id）。"""
    root = module_root_of(os.path.join(path, "x"))
    if root:
        return os.path.basename(root.rstrip("\\/"))
    return os.path.basename(os.path.abspath(path).rstrip("\\/"))


def name_alignment(target_dir: str) -> tuple:
    """检查目标模块的文件夹名与声明 Id 是否一致。

    为什么这条必须查：包内写死的 `$BASE/Modules/<X>/AssetSources/...` 要么按文件夹名
    解析、要么按 Id 解析，`X` 只可能是其中一个。一旦两者不同名，**必有一边解析不到**
    （实测：文件夹 `test` / Id `test_transe`，装备能进游戏但模型一片空白，
    日志全无报错——典型的无声失败）。所以两者相等是唯一稳妥状态。

    返回 (文件夹名, 声明的 Id, 是否不一致)。读不到 Id 时视为一致（纯资源模块）。
    """
    folder = module_folder_name(target_dir)
    declared = module_id_of(target_dir)
    return folder, declared, bool(declared) and declared != folder


# --------------------------------------------------------------------------
# 运行时缓存（RuntimeDataCache）
#
# 引擎把资源包对应的网格 / 贴图真实数据缓存在模块根目录的 RuntimeDataCache/<GUID>.rdc，
# tpac 里只有引用。只搬 tpac 不搬缓存 = 装备能进游戏但模型空白且不报错。所以缓存必须
# 跟着包一起走，且必须落在**目标模块根目录**下。
# --------------------------------------------------------------------------

def runtime_cache_dir(module_dir: str) -> str:
    """模块的运行时缓存目录（固定在模块根目录，不随 Assets 的层级别走）。"""
    return os.path.join(module_dir, CACHE_DIR_NAME)


def find_runtime_cache(tpac_path: str) -> str:
    """在**源模块根目录**的 RuntimeDataCache/ 里找该 tpac 对应的 .rdc；没有返回 ""。

    文件名比较大小时不区分大小写（Windows 磁盘本来也不区分，但别的地方产出的
    目录可能把扩展名写成 `.RDC`）。

    材质包（`*_mtl.tpac`）天生没有运行时缓存，所以"找不到"是完全正常的结果，
    **绝不能报成错误**——实测 MCV 的 78 个包里，命中规律正好是"除材质包外全部命中"。
    """
    root = module_root_of(tpac_path)
    if not root:
        return ""
    name = cache_file_name(tpac_path)
    if not name:
        return ""
    cache_dir = runtime_cache_dir(os.path.normpath(root))
    exact = os.path.join(cache_dir, name)
    if os.path.isfile(exact):
        return exact
    try:
        entries = os.listdir(cache_dir)
    except OSError:
        return ""
    low = name.lower()
    for entry in entries:
        if entry.lower() == low:
            return os.path.join(cache_dir, entry)
    return ""


def cache_target_path(tpac_path: str, target_module_dir: str) -> str:
    """缓存的目标路径：**目标模块根目录**下的 RuntimeDataCache/<GUID>.rdc。

    两个都不能想当然：
      * 不跟随 keep_relative —— 引擎查的是 `Modules/<X>/RuntimeDataCache/<GUID>.rdc`，
        把缓存塞进 Assets/<子目录>/ 里等于没搬，模型照样空白。
      * 目标目录可能被填成 `.../Modules/<X>/Assets` 而不是模块根，所以这里按模块根
        归位；定位不到（新模块还没有 SubModule.xml）才退回按字面处理。

    顺带把文件名规范成"大写 GUID + 小写 .rdc"，避免历史遗留的 `.rDC` 那种写法。
    """
    name = cache_file_name(tpac_path)
    if not name:
        return ""
    root = module_root_of(target_module_dir) or target_module_dir
    return os.path.join(runtime_cache_dir(root), name)


def _same_content(a: str, b: str) -> bool:
    """两个文件是否完全相同（先比大小，省掉大文件无谓的哈希）。"""
    try:
        if os.path.getsize(a) != os.path.getsize(b):
            return False
    except OSError:
        return False
    try:
        digest = []
        for path in (a, b):
            h = hashlib.md5()
            with open(path, "rb") as fh:
                for chunk in iter(lambda: fh.read(1 << 20), b""):
                    h.update(chunk)
            digest.append(h.digest())
    except OSError:
        return False
    return digest[0] == digest[1]


def attach_cache_info(report: PackageReport) -> PackageReport:
    """给扫描报告补上"源模块里有没有对应运行时缓存"（就地改并返回）。

    放在扫描阶段做：迁移之前就能看出哪些包会把缓存一起带走。
    同时填上 `cache_expected`（这个包是否应该有缓存），材质包会标 False。
    """
    report.cache_path = find_runtime_cache(report.path)
    report.cache_expected = needs_runtime_cache(report)
    return report


# --------------------------------------------------------------------------
# 缓存完整性审计
#
# 跟"搬运"分开：完整性只回答"该有的都有吗"，绝不阻断迁移。目标有二：
#   1. 扫描结束后告诉用户，迁之前有几份缓存是"该有但源里也没"的。
#      这正是之前把 MCV 复制进 test_transe 才发现的关键信息——多了这一栏
#      后续调试省一次往返。
#   2. 迁移落盘后做一次目标侧校验，确认复制动作真的成功了（磁盘满 / 权限
#      不足 / 文件被占都会在这里显形）。
# --------------------------------------------------------------------------

@dataclass
class CacheAuditResult:
    expected: int = 0        # 应带缓存的包数（已剔除材质包）
    material: int = 0        # 材质包数（不需要缓存）
    present_source: int = 0  # 源模块里能找到对应 .rdc 的个数
    missing_source: List[str] = field(default_factory=list)  # 源里缺哪些（GUID.rdc）
    present_target: int = 0  # 迁移后目标模块里齐全的个数
    missing_target: List[str] = field(default_factory=list)  # 目标里缺哪些
    target_checked: bool = False

    @property
    def missing_source_count(self) -> int: return len(self.missing_source)
    @property
    def missing_target_count(self) -> int: return len(self.missing_target)
    @property
    def is_complete_source(self) -> bool:
        return self.expected > 0 and self.missing_source_count == 0
    @property
    def is_complete_target(self) -> bool:
        return (self.target_checked and self.expected > 0
                and self.missing_target_count == 0)


def cache_audit(sources: Sequence[str], target_module_dir: str = ""
                ) -> CacheAuditResult:
    """对一组 tpac 做缓存完整性审计。

    对每个源：
      * 扫描拿 `types`，判定是否材质包 → 不计缓存期望
      * 算 GUID，源模块 RuntimeDataCache/ 里找 → 计入 `present_source` 或 `missing_source`
    若传了 `target_module_dir`，再对"应带且源里有"的那部分校验目标模块的同位置文件
    是否就位（这批是我们刚搬过去要保住的；源里就缺的，目标里无从谈起，不查）。
    """
    audit = CacheAuditResult()
    cache_dir_target = ""
    if target_module_dir:
        root = module_root_of(target_module_dir) or target_module_dir
        cache_dir_target = runtime_cache_dir(root)
    target_entries: Set[str] = set()
    if cache_dir_target:
        try:
            target_entries = {e.lower() for e in os.listdir(cache_dir_target)}
        except OSError:
            target_entries = set()
        audit.target_checked = True

    for src in sources:
        try:
            report = scan_package(src)
        except (TpacError, OSError):
            # 解不开的包保守按"应带 + 源里也没有"算，提示用户复查
            name = cache_file_name(src)
            if name:
                audit.expected += 1
                audit.missing_source.append(name)
            continue
        report.cache_path = find_runtime_cache(src)
        report.cache_expected = needs_runtime_cache(report)
        if not report.cache_expected:
            audit.material += 1
            continue
        audit.expected += 1
        name = cache_file_name(src)
        if report.cache_path:
            audit.present_source += 1
            if audit.target_checked and name:
                if name.lower() in target_entries:
                    audit.present_target += 1
                else:
                    audit.missing_target.append(name)
        else:
            if name:
                audit.missing_source.append(name)
    return audit


def _log_cache_audit(audit: CacheAuditResult,
                     log: Callable[[str], None]) -> None:
    """把 cache_audit 结果按"整齐→警告"的顺序打日志，不阻断。"""
    if audit.expected == 0 and audit.material == 0:
        return
    if audit.expected == 0:
        log(tr("log.cache_audit_only_material", material=audit.material))
        return
    if audit.missing_source_count == 0:
        log(tr("log.cache_audit_ok",
               expected=audit.expected, material=audit.material))
    else:
        log(tr("log.cache_audit_missing",
               expected=audit.expected, ok=audit.present_source,
               miss=audit.missing_source_count, material=audit.material))
        for name in audit.missing_source[:8]:
            log("    " + name)
        if audit.missing_source_count > 8:
            log(tr("log.cache_audit_more", n=audit.missing_source_count - 8))
    if audit.target_checked:
        if audit.missing_target_count == 0:
            log(tr("log.cache_audit_target_ok", ok=audit.present_target))
        else:
            log(tr("log.cache_audit_target_missing",
                   ok=audit.present_target, miss=audit.missing_target_count))
            for name in audit.missing_target[:8]:
                log("    " + name)


# --------------------------------------------------------------------------
# 规则建议
# --------------------------------------------------------------------------

def collect_locked_paths(reports: Sequence[PackageReport]) -> Dict[str, int]:
    """统计扫描结果里出现的"被锁死"路径前缀：$BASE/Modules/<X>/ 形式。"""
    counter: Dict[str, int] = {}
    for report in reports:
        for _where, text in report.strings:
            marker = "Modules/"
            idx = text.find(marker)
            if idx < 0:
                continue
            rest = text[idx + len(marker):]
            module = rest.split("/")[0]
            if not module:
                continue
            prefix = text[:idx + len(marker)] + module + "/"
            counter[prefix] = counter.get(prefix, 0) + 1
    return counter


def suggest_rules(reports: Sequence[PackageReport], target_module: str) -> List[MappingRule]:
    """根据真实扫描到的路径前缀生成规则，而不是凭空猜模块名。"""
    rules: List[MappingRule] = []
    if not target_module:
        return rules
    for prefix, count in sorted(collect_locked_paths(reports).items(),
                                key=lambda kv: -kv[1]):
        module = prefix.rstrip("/").split("/")[-1]
        if module == target_module:
            continue
        new_prefix = prefix[:prefix.rfind(module)] + target_module + "/"
        # 存 key + 参数而不是成品文案，这样切换界面语言时规则表也能跟着变
        rules.append(MappingRule(prefix, new_prefix, True,
                                 "note.occurrences|%d" % count))
    return rules


# --------------------------------------------------------------------------
# 任务与结果
# --------------------------------------------------------------------------

@dataclass
class MigrateOptions:
    target_module: str = ""
    on_conflict: str = "rename"       # overwrite | skip | rename
    backup: bool = True
    keep_relative: bool = True
    verify: bool = True
    scan_segments: bool = True
    max_segment_size: int = 4 << 20


@dataclass
class MigrateResult:
    source: str
    target: str = ""
    status: str = "pending"           # ok | skipped | failed | planned
    message: str = ""
    items_before: int = 0
    items_after: int = 0
    rewrites: int = 0
    size_before: int = 0
    size_after: int = 0
    external_refs: Set[str] = field(default_factory=set)
    warnings: List[str] = field(default_factory=list)

    # 运行时缓存（RuntimeDataCache）的搬运情况
    cache_src: str = ""
    cache_dst: str = ""
    cache_status: str = ""            # copied | overwritten | same | skipped
                                      # | missing | failed
    cache_bytes: int = 0
    # 供回滚用的记录（{"target","backup","created"}），没搬缓存时为 None
    cache_entry: Optional[Dict] = None


def compute_target_path(source: str, target_module_dir: str,
                        keep_relative: bool) -> str:
    if keep_relative:
        root = module_root_of(source)
        if root:
            return os.path.join(target_module_dir,
                                os.path.relpath(source, root))
        return os.path.join(target_module_dir, os.path.basename(source))
    return os.path.join(target_module_dir, os.path.basename(source))


def resolve_conflict(path: str, on_conflict: str) -> str:
    if not os.path.exists(path):
        return path
    if on_conflict == "overwrite":
        return path
    if on_conflict == "skip":
        return ""
    base, ext = os.path.splitext(path)
    idx = 1
    while os.path.exists("%s_%d%s" % (base, idx, ext)):
        idx += 1
    return "%s_%d%s" % (base, idx, ext)


def _backup(path: str) -> str:
    stamp = time.strftime("%Y%m%d-%H%M%S")
    backup = "%s.bak-%s" % (path, stamp)
    if os.path.exists(backup):
        os.remove(backup)
    shutil.copy2(path, backup)
    return backup


def _migrate_cache(source: str, target_module_dir: str, options: MigrateOptions,
                   result: MigrateResult) -> Optional[Dict]:
    """把源模块 RuntimeDataCache 里对应的 .rdc 一并搬到目标模块。

    返回可写进回滚记录的 {"target","backup","created"}；没搬任何东西时返回 None。

    落点固定在**目标模块根目录**的 RuntimeDataCache/，绝不跟随 keep_relative ——
    引擎就是按 `Modules/<X>/RuntimeDataCache/<GUID>.rdc` 查的。

    冲突处理有个和 tpac 不一样的地方：文件名本身就是引擎的查找键，所以
    on_conflict=rename 对缓存毫无意义（改成 `<GUID>_1.rdc` 等于没搬），一律按覆盖处理，
    覆盖前照常备份。
    """
    src = find_runtime_cache(source)
    result.cache_src = src
    if not src:
        # 材质包天生没有缓存，属正常情况；不在日志里逐条刷屏，最后统一汇总
        result.cache_status = "missing"
        return None

    dst = cache_target_path(source, target_module_dir)
    result.cache_dst = dst
    try:
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        existed = os.path.exists(dst)
        backup = ""
        if existed:
            if _same_content(src, dst):
                result.cache_status = "same"
                result.cache_bytes = os.path.getsize(dst)
                return None
            if options.on_conflict == "skip":
                result.cache_status = "skipped"
                return None
            if options.backup:
                try:
                    backup = _backup(dst)
                except OSError as exc:
                    result.warnings.append(tr("mig.cache_backup_fail", err=exc))
        shutil.copy2(src, dst)
        result.cache_status = "overwritten" if existed else "copied"
        result.cache_bytes = os.path.getsize(dst)
        return {"target": dst, "backup": backup, "created": not existed}
    except OSError as exc:
        result.cache_status = "failed"
        result.warnings.append(tr("mig.cache_fail", err=exc))
        return None


def migrate_one(source: str, target: str, rules: Sequence[MappingRule],
                options: MigrateOptions,
                progress: Optional[Callable[[int, int], None]] = None,
                target_module_dir: str = ""
                ) -> MigrateResult:
    """迁移单个 tpac。target 为最终输出文件路径。

    target_module_dir 为目标**模块根目录**，用于安放 RuntimeDataCache；留空则跳过
    缓存搬运（只搬包不搬缓存会得到"能装备但模型空白"的废包，所以正常调用都要传）。
    """
    result = MigrateResult(source=source, target=target)
    result.size_before = os.path.getsize(source)

    pkg = load_tpac(source)
    try:
        result.items_before = len(pkg.items)

        remapper = Remapper(rules, ScanOptions(
            scan_metadata=True,
            max_segment_size=options.max_segment_size if options.scan_segments else 0,
        ))
        result.rewrites = remapper.rewrite_package(pkg)
        result.warnings.extend(remapper.skipped)

        build_dependency_graph(pkg)
        result.external_refs = {guid_str(g)
                                for item in pkg.items
                                for g in item.external_refs}

        os.makedirs(os.path.dirname(os.path.abspath(target)), exist_ok=True)
        save_tpac(pkg, target, progress=progress)

        if options.verify:
            check = load_tpac(target)
            result.items_after = len(check.items)
            for item in check.items:
                for seg in item.segments:
                    data = seg.get_data()
                    if len(data) != seg.actual_size:
                        raise TpacError(tr("mig.err_seg_len", name=item.name))
            if result.items_after != result.items_before:
                result.warnings.append(
                    tr("mig.err_item_count", before=result.items_before,
                       after=result.items_after))
            check.close()
    except Exception as exc:  # noqa: BLE001
        result.status = "failed"
        result.message = "%s: %s" % (type(exc).__name__, exc)
        return result
    finally:
        pkg.close()

    result.size_after = os.path.getsize(target) if os.path.exists(target) else 0
    if result.items_after == 0:
        result.items_after = result.items_before
    result.status = "ok"

    # tpac 落盘成功之后才搬缓存：包写失败了就不该往目标模块里塞缓存。
    if target_module_dir:
        result.cache_entry = _migrate_cache(source, target_module_dir, options, result)
    return result


def _fmt_size(num: int) -> str:
    value = float(num)
    if value < 1024:
        return "%.0f B" % value
    for unit in ("KB", "MB", "GB"):
        value /= 1024.0
        if value < 1024.0 or unit == "GB":
            return "%.1f %s" % (value, unit)
    return "%.1f TB" % (value / 1024.0)


def _log_cache_summary(results: Sequence[MigrateResult],
                       log: Callable[[str], None]) -> None:
    """一条汇总说清缓存去向——逐条刷屏没人看得下去。"""
    counts: Dict[str, int] = {}
    for res in results:
        if res.status == "ok" and res.cache_status:
            counts[res.cache_status] = counts.get(res.cache_status, 0) + 1
    if not counts:
        return
    log(tr("mig.cache_summary",
           copied=counts.get("copied", 0),
           overwritten=counts.get("overwritten", 0),
           same=counts.get("same", 0),
           skipped=counts.get("skipped", 0),
           missing=counts.get("missing", 0),
           failed=counts.get("failed", 0)))


def run_batch(sources: Sequence[str], target_module_dir: str,
              rules: Sequence[MappingRule], options: MigrateOptions,
              log: Callable[[str], None] = print,
              progress: Optional[Callable[[int, int], None]] = None
              ) -> List[MigrateResult]:
    results: List[MigrateResult] = []
    journal: List[Dict] = []

    os.makedirs(target_module_dir, exist_ok=True)

    for index, source in enumerate(sources, 1):
        wanted = compute_target_path(source, target_module_dir,
                                     options.keep_relative)
        target = resolve_conflict(wanted, options.on_conflict)
        if not target:
            results.append(MigrateResult(source, wanted, "skipped",
                                  tr("mig.skipped_reason")))
            log(tr("mig.skip_exists", a=index, b=len(sources),
                    name=os.path.basename(source)))
            continue

        backup = ""
        if os.path.exists(target) and options.backup:
            try:
                backup = _backup(target)
            except OSError as exc:
                log(tr("mig.backup_fail", err=exc))

        log("[%d/%d] %s" % (index, len(sources), os.path.basename(source)))
        result = migrate_one(source, target, rules, options, progress,
                             target_module_dir=target_module_dir)
        results.append(result)

        if result.status == "ok":
            journal.append({"target": target, "backup": backup, "created": not backup})
            if result.cache_entry:
                # 缓存也要进回滚记录，否则回滚会留下一堆没人认领的 .rdc
                journal.append(result.cache_entry)
            log(tr("mig.result", name=os.path.relpath(target, target_module_dir),
                    items=result.items_after, rewrites=result.rewrites,
                    before=result.size_before, after=result.size_after))
            if result.cache_status in ("copied", "overwritten"):
                log(tr("mig.cache_copied" if result.cache_status == "copied"
                       else "mig.cache_overwritten",
                       name=os.path.basename(result.cache_dst),
                       size=_fmt_size(result.cache_bytes)))
            if result.external_refs:
                log(tr("mig.ext_refs", count=len(result.external_refs)))
        else:
            log(tr("mig.failed", err=result.message))
        for warn in result.warnings:
            log(tr("mig.warn", msg=warn))

    _log_cache_summary(results, log)
    _log_cache_audit(cache_audit(sources, target_module_dir), log)

    if journal:
        path = os.path.join(target_module_dir, JOURNAL_NAME)
        try:
            with open(path, "w", encoding="utf-8") as fh:
                json.dump({"time": time.strftime("%Y-%m-%d %H:%M:%S"),
                           "target_module": target_module_dir,
                           "entries": journal}, fh, ensure_ascii=False, indent=2)
            log(tr("mig.journal", path=path))
        except OSError as exc:
            log(tr("mig.journal_fail", err=exc))

    return results


def rollback(target_module_dir: str, log: Callable[[str], None] = print) -> int:
    """撤销最近一次迁移：删除新增文件，还原被覆盖文件的备份。"""
    path = os.path.join(target_module_dir, JOURNAL_NAME)
    if not os.path.exists(path):
        log(tr("mig.no_journal"))
        return 0
    with open(path, "r", encoding="utf-8") as fh:
        journal = json.load(fh)
    count = 0
    for entry in reversed(journal.get("entries", [])):
        target = entry.get("target", "")
        backup = entry.get("backup", "")
        try:
            if backup and os.path.exists(backup):
                if os.path.exists(target):
                    os.remove(target)
                shutil.move(backup, target)
            elif os.path.exists(target):
                os.remove(target)
            count += 1
        except OSError as exc:
            log(tr("mig.rollback_fail", path=target, err=exc))
    try:
        os.remove(path)
    except OSError:
        pass
    log(tr("mig.rollback_done", count=count))
    return count


# --------------------------------------------------------------------------
# 命令行
# --------------------------------------------------------------------------

def main(argv: Optional[Sequence[str]] = None) -> int:
    # 先探一次 --lang，好让后面的帮助文本也是用户要的语言
    raw = list(argv) if argv is not None else sys.argv[1:]
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("--lang", default="", choices=list(LANGS))
    init_lang(pre.parse_known_args(raw)[0].lang)

    parser = argparse.ArgumentParser(description=tr("cli.desc"))
    parser.add_argument("--source", nargs="*", default=[],
                        help=tr("cli.source"))
    parser.add_argument("--target", required=True, help=tr("cli.target"))
    parser.add_argument("--from", dest="src_module", default="",
                        help=tr("cli.from"))
    parser.add_argument("--to", dest="dst_module", default="",
                        help=tr("cli.to"))
    parser.add_argument("--rule", action="append", default=[],
                        help=tr("cli.rule"))
    parser.add_argument("--on-conflict", default="rename",
                        choices=["overwrite", "skip", "rename"])
    parser.add_argument("--no-backup", action="store_true")
    parser.add_argument("--flat", action="store_true",
                        help=tr("cli.flat"))  # 兼容旧写法；现在默认就是直投
    parser.add_argument("--keep-relative", action="store_true",
                        help=tr("cli.keep_relative"))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--rollback", action="store_true", help=tr("cli.rollback"))
    parser.add_argument("--lang", default="", choices=list(LANGS),
                        help=tr("cli.lang"))
    args = parser.parse_args(argv)

    if args.rollback:
        rollback(args.target)
        return 0

    target_dir = os.path.abspath(args.target)
    # 目标模块名取目标模块的**文件夹名**：包内写死的 `$BASE/Modules/<X>/...` 是编辑器
    # 烘焙时记下的字面路径，X 就是当时的文件夹名（工坊 mod 也会被 Steam 改名成数字 ID，
    # 而包内仍留着作者原本的文件夹名）。用 Id 会指向一个不存在的目录。
    dst_module = (args.dst_module or module_folder_name(target_dir)
                  or os.path.basename(target_dir))

    # 文件夹名与声明 Id 不一致 → 两种解析规则里必有一边坏掉，必须显式告警。
    _folder, _declared, _mismatch = name_alignment(target_dir)
    if _mismatch:
        print(tr("cli.name_mismatch", folder=_folder, id=_declared))

    if not args.source:
        print(tr("cli.need_source"))
        return 1

    files = discover_tpac(args.source)
    if not files:
        print(tr("cli.no_files"))
        return 1

    print(tr("cli.scanning", count=len(files)))
    reports = [scan_package(f) for f in files]
    rules = suggest_rules(reports, dst_module)
    if args.src_module:
        rules.append(MappingRule("$BASE/Modules/%s/" % args.src_module,
                                 "$BASE/Modules/%s/" % dst_module))
    for pair in args.rule:
        if "=" in pair:
            old, new = pair.split("=", 1)
            rules.append(MappingRule(old, new))

    print(tr("cli.rules_header"))
    for rule in rules:
        print("  %s  ->  %s" % (rule.old, rule.new))
    if not rules:
        print(tr("cli.rules_none"))
        print(tr("cli.rules_none_warn"))

    options = MigrateOptions(
        target_module=dst_module,
        on_conflict=args.on_conflict,
        backup=not args.no_backup,
        keep_relative=args.keep_relative,
    )

    if args.dry_run:
        print(tr("cli.dry_header"))
        for f in files[:20]:
            print("  %s -> %s" % (f, compute_target_path(f, target_dir,
                                                         options.keep_relative)))
            src_cache = find_runtime_cache(f)
            if src_cache:
                print("      " + tr("cli.cache_line",
                                    name=os.path.basename(src_cache),
                                    dst=cache_target_path(f, target_dir)))
            else:
                print("      " + tr("cli.cache_none"))
        print(tr("cli.cache_hint"))
        return 0

    results = run_batch(files, target_dir, rules, options)
    ok = sum(1 for r in results if r.status == "ok")
    print(tr("cli.summary", ok=ok, total=len(results)))
    return 0 if ok == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
