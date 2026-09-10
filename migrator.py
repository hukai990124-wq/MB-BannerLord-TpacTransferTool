# -*- coding: utf-8 -*-
"""
migrator.py -- 迁移执行层（与界面无关，可单独用命令行调用）。

职责：
  * 发现 .tpac 文件
  * 根据扫描结果建议重映射规则
  * 计算目标路径、处理冲突、备份与回滚
  * 执行迁移并在写盘后做结构自检

用法（命令行）：
    python migrator.py --source <目录或文件> --target <目标模块目录> \
        --from MercenaryVariety --to MyMod [--dry-run] [--on-conflict rename]
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from dataclasses import dataclass, field, asdict
from typing import Callable, Dict, List, Optional, Sequence, Set

from i18n import LANGS, init_lang, tr
from tpac_core import (
    MappingRule, PackageReport, Remapper, ScanOptions, TpacError,
    build_dependency_graph, guid_str, load_tpac, save_tpac, scan_package,
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
    """返回 .../Modules/<ModuleName> 这样的模块根目录；不在 Modules 下则返回空串。"""
    norm = os.path.abspath(path).replace("\\", "/")
    marker = "/Modules/"
    pos = norm.rfind(marker)
    if pos < 0:
        return ""
    parts = norm[pos + len(marker):].split("/")
    if not parts:
        return ""
    return norm[:pos + len(marker)] + parts[0]


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


def migrate_one(source: str, target: str, rules: Sequence[MappingRule],
                options: MigrateOptions,
                progress: Optional[Callable[[int, int], None]] = None
                ) -> MigrateResult:
    """迁移单个 tpac。target 为最终输出文件路径。"""
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
    return result


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
        result = migrate_one(source, target, rules, options, progress)
        results.append(result)

        if result.status == "ok":
            journal.append({"target": target, "backup": backup, "created": not backup})
            log(tr("mig.result", name=os.path.relpath(target, target_module_dir),
                    items=result.items_after, rewrites=result.rewrites,
                    before=result.size_before, after=result.size_after))
            if result.external_refs:
                log(tr("mig.ext_refs", count=len(result.external_refs)))
        else:
            log(tr("mig.failed", err=result.message))
        for warn in result.warnings:
            log(tr("mig.warn", msg=warn))

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
    parser.add_argument("--flat", action="store_true", help=tr("cli.flat"))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--rollback", action="store_true", help=tr("cli.rollback"))
    parser.add_argument("--lang", default="", choices=list(LANGS),
                        help=tr("cli.lang"))
    args = parser.parse_args(argv)

    if args.rollback:
        rollback(args.target)
        return 0

    target_dir = os.path.abspath(args.target)
    dst_module = args.dst_module or os.path.basename(target_dir)

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

    options = MigrateOptions(
        target_module=dst_module,
        on_conflict=args.on_conflict,
        backup=not args.no_backup,
        keep_relative=not args.flat,
    )

    if args.dry_run:
        print(tr("cli.dry_header"))
        for f in files[:20]:
            print("  %s -> %s" % (f, compute_target_path(f, target_dir,
                                                         options.keep_relative)))
        return 0

    results = run_batch(files, target_dir, rules, options)
    ok = sum(1 for r in results if r.status == "ok")
    print(tr("cli.summary", ok=ok, total=len(results)))
    return 0 if ok == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
