# -*- coding: utf-8 -*-
"""
i18n.py -- 中英文文案表。

界面文字、运行日志、解析报错统一走这里，切语言时只需 set_lang()。

用法：
    from i18n import tr, set_lang, get_lang
    tr("btn.scan")                       # -> "扫描源" / "Scan Sources"
    tr("log.scan_done", count=40)        # -> "扫描完成：40 个 tpac"

规则：
  * 带参数的文案一律用 **命名占位符** %(name)s，因为 tr() 内部是 text % kwargs。
  * 新增文案要给 zh 和 en 两份；缺哪门语言会自动回退到中文，不会把 key 丢给用户。
"""
from __future__ import annotations

import json
import locale
import os
import threading

LANGS = ("zh", "en")

_LANG = "zh"
_LOCK = threading.RLock()

CONFIG_NAME = "ui_config.json"

STRINGS = {
    # -------------------------------------------------------------- 界面
    "app.title": {"zh": "Bannerlord TPAC 批量迁移工具",
                  "en": "Bannerlord TPAC Batch Migrator"},
    "app.subtitle": {"zh": "把 .tpac 资源包迁移到别的 mod，自动重映射包内被锁死的路径引用",
                     "en": "Move .tpac packages to another mod and remap their locked asset paths"},
    "app.lang": {"zh": "界面语言：", "en": "Language:"},

    "sec.sources": {"zh": "1. 源与目标", "en": "1. Source & Target"},
    "lbl.sources": {"zh": "源（mod 目录 / 单个 .tpac）",
                    "en": "Source (mod folder / single .tpac)"},
    "btn.add_dir": {"zh": "添加目录…", "en": "Add Folder…"},
    "btn.add_files": {"zh": "添加文件…", "en": "Add Files…"},
    "btn.remove": {"zh": "移除选中", "en": "Remove Selected"},
    "btn.clear": {"zh": "清空", "en": "Clear"},
    "btn.find_game": {"zh": "查找游戏目录…", "en": "Locate Game Folder…"},
    "lbl.target": {"zh": "目标模块目录", "en": "Target module folder"},
    "btn.browse": {"zh": "浏览…", "en": "Browse…"},
    "lbl.module": {"zh": "目标模块名", "en": "Target module name"},
    "lbl.module_hint": {"zh": "（用于生成 $BASE/Modules/<模块名>/ 替换规则）",
                        "en": "(used to build $BASE/Modules/<name>/ rules)"},
    "btn.scan": {"zh": "扫描源", "en": "Scan Sources"},
    "lbl.scan_hint": {"zh": "扫描后会自动建议重映射规则",
                      "en": "Remap rules are suggested after scanning"},

    "sec.results": {"zh": "2. 扫描结果（点击首列勾选要迁移的包）",
                    "en": "2. Scan Results (click the first column to select)"},
    "col.sel": {"zh": "✓", "en": "✓"},
    "col.module": {"zh": "源模块", "en": "Source Module"},
    "col.path": {"zh": "文件", "en": "File"},
    "col.size": {"zh": "大小", "en": "Size"},
    "col.items": {"zh": "条目", "en": "Items"},
    "col.ext": {"zh": "包外依赖", "en": "External Deps"},
    "col.types": {"zh": "内容", "en": "Contents"},
    "btn.toggle_all": {"zh": "全选 / 全不选", "en": "Select All / None"},

    "sec.rules": {"zh": "3. 路径重映射规则", "en": "3. Path Remap Rules"},
    "col.on": {"zh": "启用", "en": "On"},
    "col.old": {"zh": "原字符串", "en": "Original"},
    "col.new": {"zh": "替换为", "en": "Replace With"},
    "col.note": {"zh": "说明", "en": "Note"},
    "types.sep": {"zh": "，", "en": ", "},
    "btn.suggest": {"zh": "自动建议", "en": "Suggest"},
    "btn.add": {"zh": "添加…", "en": "Add…"},
    "btn.edit": {"zh": "编辑…", "en": "Edit…"},
    "btn.del": {"zh": "删除", "en": "Delete"},
    "lbl.rule_safety": {"zh": "长度可变的替换只会在带长度前缀的字符串上执行，安全",
                        "en": "Variable-length rewrites only apply to length-prefixed strings — safe"},

    "sec.options": {"zh": "4. 选项", "en": "4. Options"},
    "chk.backup": {"zh": "覆盖前备份原文件", "en": "Back up before overwriting"},
    "chk.relative": {"zh": "保留相对目录结构", "en": "Keep relative folder structure"},
    "chk.verify": {"zh": "写盘后结构自检", "en": "Verify structure after write"},
    "lbl.conflict": {"zh": "同名冲突：", "en": "On conflict:"},

    "btn.run": {"zh": "开始迁移", "en": "Start Migration"},
    "btn.dry": {"zh": "预演（只看不改）", "en": "Dry Run (no writes)"},
    "btn.rollback": {"zh": "回滚上次迁移", "en": "Rollback Last Migration"},

    "status.ready": {"zh": "就绪", "en": "Ready"},
    "status.scanning": {"zh": "扫描中…", "en": "Scanning…"},
    "status.scan_progress": {"zh": "扫描中 %(a)d/%(b)d", "en": "Scanning %(a)d/%(b)d"},
    "status.scan_done": {"zh": "扫描完成：%(count)d 个包",
                         "en": "Scan complete: %(count)d packages"},
    "status.migrating": {"zh": "迁移中…", "en": "Migrating…"},
    "status.done": {"zh": "迁移完成", "en": "Migration complete"},
    "status.error": {"zh": "出错了", "en": "Error"},
    "status.finding_game": {"zh": "正在查找游戏目录…", "en": "Locating game folder…"},

    # -------------------------------------------------------------- 弹窗
    "dlg.title": {"zh": "提示", "en": "Notice"},
    "dlg.add_dir": {"zh": "选择包含 .tpac 的目录", "en": "Choose a folder containing .tpac files"},
    "dlg.add_files": {"zh": "选择 .tpac 文件", "en": "Choose .tpac files"},
    "filetype.tpac": {"zh": "TPAC 资源包", "en": "TPAC package"},
    "filetype.all": {"zh": "所有文件", "en": "All files"},
    "dlg.target": {"zh": "选择目标模块目录", "en": "Choose target module folder"},
    "dlg.no_modules_title": {"zh": "未找到模块", "en": "No Modules Folder"},
    "dlg.no_modules": {"zh": "该目录下没有 Modules 文件夹",
                       "en": "There is no Modules folder under that directory"},
    "dlg.pick_module": {"zh": "选择模块", "en": "Select Module"},
    "dlg.pick_module_hint": {"zh": "双击一个模块，把它作为迁移源",
                             "en": "Double-click a module to use it as a migration source"},
    "btn.ok": {"zh": "确定", "en": "OK"},
    "btn.save": {"zh": "保存", "en": "Save"},
    "dlg.rule_add": {"zh": "添加规则", "en": "Add Rule"},
    "dlg.rule_edit": {"zh": "编辑规则", "en": "Edit Rule"},
    "dlg.rule_old": {"zh": "原字符串（包内实际存在的内容）",
                     "en": "Original string (must actually exist inside the package)"},
    "dlg.rule_new": {"zh": "替换为", "en": "Replace with"},
    "warn.empty_old": {"zh": "原字符串不能为空", "en": "The original string cannot be empty"},
    "dlg.not_found": {"zh": "未找到", "en": "Not Found"},
    "dlg.game_not_found": {"zh": "没有在常见位置找到游戏安装目录，请手动选择",
                           "en": "Game folder not found in the usual locations; please pick it manually"},
    "dlg.rollback_title": {"zh": "确认", "en": "Confirm"},
    "dlg.rollback_msg": {"zh": "将删除上次迁移写入的文件，并还原被覆盖的备份。继续？",
                         "en": "This deletes files written by the last migration and restores backups. Continue?"},

    "msg.no_source": {"zh": "请先添加源目录或 .tpac 文件",
                      "en": "Add a source folder or .tpac file first"},
    "msg.need_scan": {"zh": "请先扫描，工具会依据包内真实出现的路径来建议规则",
                      "en": "Scan first — rules come from paths actually found inside the packages"},
    "msg.need_module_suggest": {"zh": "请先填写目标模块名",
                                "en": "Enter the target module name first"},
    "msg.need_module": {"zh": "请填写目标模块名", "en": "Enter the target module name"},
    "msg.need_select": {"zh": "请在扫描结果里勾选要迁移的包",
                        "en": "Select the packages to migrate in the scan results"},
    "msg.need_target": {"zh": "请先选择目标模块目录",
                        "en": "Choose the target module folder first"},

    # -------------------------------------------------------------- 日志
    "log.no_tpac": {"zh": "没有找到任何 .tpac 文件", "en": "No .tpac files found"},
    "log.scan_done": {"zh": "扫描完成：%(count)d 个 tpac",
                      "en": "Scan complete: %(count)d tpac"},
    "log.externals": {"zh": "发现 %(count)d 个指向包外的依赖引用；这类依赖需要目标环境同样能解析到",
                      "en": "Found %(count)d references pointing outside the package; the target must be able to resolve them"},
    "log.suggest_none": {"zh": "没有发现需要重映射的模块路径（可能包内没有 $BASE/Modules/… 形式的引用）",
                         "en": "No module paths need remapping (packages may hold no $BASE/Modules/… references)"},
    "log.suggest_done": {"zh": "已建议 %(total)d 条规则（新增 %(added)d）",
                         "en": "Suggested %(total)d rules (%(added)d new)"},
    "log.dry_header": {"zh": "预演模式：仅列出将要写入的位置，不改动任何文件",
                       "en": "Dry run: listing destinations only, nothing is written"},
    "log.dry_total": {"zh": "共 %(count)d 个包待迁移", "en": "%(count)d packages pending"},
    "log.migrate_done": {"zh": "迁移完成", "en": "Migration complete"},
    "log.rollback_done": {"zh": "回滚完成", "en": "Rollback complete"},
    "log.parse_failed": {"zh": "解析失败：%(err)s", "en": "Parse failed: %(err)s"},
    "log.lang_switched": {"zh": "界面语言已切换为%(name)s",
                          "en": "Interface language switched to %(name)s"},

    # -------------------------------------------------------------- 自检
    "smoke.not_found": {"zh": "自检：未找到游戏目录，跳过",
                        "en": "Smoke: game folder not found, skipping"},
    "smoke.start": {"zh": "自检：开始迁移", "en": "Smoke: starting migration"},
    "smoke.cleanup": {"zh": "自检：已清理临时产物 %(path)s",
                      "en": "Smoke: cleaned temp output %(path)s"},
    "smoke.cleanup_fail": {"zh": "自检：清理失败 %(err)s",
                           "en": "Smoke: cleanup failed %(err)s"},

    # -------------------------------------------------------------- 规则来源
    "note.occurrences": {"zh": "出现在 %(count)d 处", "en": "occurs in %(count)d places"},
    "note.manual": {"zh": "手动添加", "en": "Manual"},

    # -------------------------------------------------------------- 迁移日志
    "mig.skip_exists": {"zh": "[%(a)d/%(b)d] 跳过（已存在）：%(name)s",
                        "en": "[%(a)d/%(b)d] Skipped (exists): %(name)s"},
    "mig.backup_fail": {"zh": "  备份失败：%(err)s", "en": "  Backup failed: %(err)s"},
    "mig.result": {"zh": "   -> %(name)s（%(items)d 条目，改写 %(rewrites)d 处，"
                        "%(before)s -> %(after)s 字节）",
                   "en": "   -> %(name)s (%(items)d items, %(rewrites)d rewritten, "
                         "%(before)s -> %(after)s bytes)"},
    "mig.ext_refs": {"zh": "   注意：存在 %(count)d 个包外依赖 GUID，需确认目标模块能解析",
                     "en": "   Note: %(count)d dependencies point outside the package; "
                           "make sure the target module can resolve them"},
    "mig.failed": {"zh": "   失败：%(err)s", "en": "   Failed: %(err)s"},
    "mig.warn": {"zh": "   警告：%(msg)s", "en": "   Warning: %(msg)s"},
    "mig.journal": {"zh": "迁移记录：%(path)s", "en": "Migration journal: %(path)s"},
    "mig.journal_fail": {"zh": "无法写入迁移记录：%(err)s",
                         "en": "Cannot write migration journal: %(err)s"},
    "mig.no_journal": {"zh": "没有找到迁移记录，无法回滚",
                       "en": "No migration journal found; cannot roll back"},
    "mig.rollback_fail": {"zh": "回滚失败 %(path)s：%(err)s",
                          "en": "Rollback failed %(path)s: %(err)s"},
    "mig.rollback_done": {"zh": "已回滚 %(count)d 个文件", "en": "Rolled back %(count)d files"},
    "mig.skipped_reason": {"zh": "目标已存在，按策略跳过",
                           "en": "Target exists; skipped by policy"},
    "mig.err_seg_len": {"zh": "段解压长度不符：%(name)s",
                        "en": "Decompressed size mismatch: %(name)s"},
    "mig.err_item_count": {"zh": "条目数不一致：源 %(before)d -> 产物 %(after)d",
                           "en": "Item count mismatch: source %(before)d -> output %(after)d"},

    # -------------------------------------------------------------- 命令行
    "cli.desc": {"zh": "批量迁移 Bannerlord .tpac 资源包",
                 "en": "Batch-migrate Bannerlord .tpac asset packages"},
    "cli.source": {"zh": "源目录或 .tpac 文件（可多个；--rollback 时不需要）",
                   "en": "Source folder or .tpac files (repeatable; not needed with --rollback)"},
    "cli.target": {"zh": "目标模块目录", "en": "Target module folder"},
    "cli.from": {"zh": "源模块名（用于生成替换规则）",
                 "en": "Source module name (used to build replace rules)"},
    "cli.to": {"zh": "目标模块名（默认取目标目录名）",
               "en": "Target module name (defaults to the folder name)"},
    "cli.rule": {"zh": "自定义规则，格式 旧串=新串，可重复",
                 "en": "Custom rule as OLD=NEW, repeatable"},
    "cli.flat": {"zh": "不保留相对目录结构", "en": "Do not keep relative folder structure"},
    "cli.rollback": {"zh": "回滚最近一次迁移", "en": "Roll back the last migration"},
    "cli.lang": {"zh": "输出语言：zh 或 en", "en": "Output language: zh or en"},
    "cli.need_source": {"zh": "请用 --source 指定要迁移的目录或 .tpac 文件",
                        "en": "Specify folders or .tpac files with --source"},
    "cli.no_files": {"zh": "没有找到 .tpac 文件", "en": "No .tpac files found"},
    "cli.scanning": {"zh": "发现 %(count)d 个 tpac，扫描中...",
                     "en": "Found %(count)d tpac, scanning..."},
    "cli.rules_header": {"zh": "\n重映射规则：", "en": "\nRemap rules:"},
    "cli.rules_none": {"zh": "  （无）", "en": "  (none)"},
    "cli.dry_header": {"zh": "\n预演模式，不写盘。目标路径示例：",
                       "en": "\nDry run, nothing will be written. Example destinations:"},
    "cli.summary": {"zh": "\n完成：成功 %(ok)d / 共 %(total)d",
                    "en": "\nDone: %(ok)d succeeded / %(total)d total"},

    # -------------------------------------------------------------- 解析报错
    "err.lz4_offset0": {"zh": "LZ4 数据损坏：match offset 为 0",
                        "en": "Corrupt LZ4 data: match offset is 0"},
    "err.lz4_offset_oob": {"zh": "LZ4 数据损坏：match offset 越界",
                           "en": "Corrupt LZ4 data: match offset out of range"},
    "err.lz4_len": {"zh": "LZ4 解压长度不符：期望 %(a)d，实际 %(b)d",
                    "en": "LZ4 decompressed size mismatch: expected %(a)d, got %(b)d"},
    "err.src_truncated": {"zh": "源文件在 %(path)s 处提前结束",
                          "en": "Source file ended early at %(path)s"},
    "err.str_oob": {"zh": "读取字符串越界（偏移 %(pos)d）",
                    "en": "String read out of bounds (offset %(pos)d)"},
    "err.str_len": {"zh": "字符串长度异常：%(length)d（偏移 %(pos)d）",
                    "en": "Invalid string length: %(length)d (offset %(pos)d)"},
    "err.file_small": {"zh": "文件过小，不是有效的 tpac",
                       "en": "File too small to be a valid tpac"},
    "err.magic": {"zh": "不是 tpac 文件（magic=0x%(magic)08X）",
                  "en": "Not a tpac file (magic=0x%(magic)08X)"},
    "err.version": {"zh": "不支持的 tpac 版本：%(version)d",
                    "en": "Unsupported tpac version: %(version)d"},
    "err.toc_trunc": {"zh": "TOC 在偏移 %(pos)d 处提前结束（需要 %(need)d 字节，实得 %(got)d）",
                      "en": "TOC ended early at offset %(pos)d (need %(need)d bytes, got %(got)d)"},
    "err.meta_len": {"zh": "metadata 长度异常：%(length)d",
                     "en": "Invalid metadata length: %(length)d"},
    "err.seg_count": {"zh": "segment 数量异常：%(count)d",
                      "en": "Invalid segment count: %(count)d"},
    "err.seg_oob": {"zh": "segment 数据越界：offset=%(offset)d size=%(size)d，文件 %(total)d 字节",
                    "en": "Segment out of bounds: offset=%(offset)d size=%(size)d, "
                          "file is %(total)d bytes"},
    "err.dep_count": {"zh": "dependence 数量异常：%(count)d",
                      "en": "Invalid dependence count: %(count)d"},
    "err.rewrite_abort": {"zh": "%(where)s：替换次数过多，已中断",
                          "en": "%(where)s: too many replacements, aborted"},
    "err.decompress_fail": {"zh": "%(where)s[%(name)s] 解压失败：%(err)s",
                            "en": "%(where)s[%(name)s] decompression failed: %(err)s"},
}

_FALLBACK = "zh"


def tr(key: str, **kwargs) -> str:
    """取当前语言的文案；kwargs 走命名占位符 %(name)s。"""
    with _LOCK:
        table = STRINGS.get(key)
        if not table:
            return key
        text = table.get(_LANG) or table.get(_FALLBACK) or key
        return text % kwargs if kwargs else text


def get_lang() -> str:
    with _LOCK:
        return _LANG


def set_lang(code: str) -> None:
    global _LANG
    with _LOCK:
        if code in LANGS:
            _LANG = code


def config_path() -> str:
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), CONFIG_NAME)


def load_saved_lang() -> str:
    """读取上次选择的语言；没有记录就按系统语言猜。"""
    try:
        with open(config_path(), "r", encoding="utf-8") as fh:
            code = json.load(fh).get("lang", "")
        if code in LANGS:
            return code
    except Exception:
        pass
    return detect_lang()


def save_lang(code: str) -> None:
    try:
        with open(config_path(), "w", encoding="utf-8") as fh:
            json.dump({"lang": code}, fh, ensure_ascii=False, indent=2)
    except OSError:
        pass  # 存不下就算了，不影响使用


def detect_lang() -> str:
    """按系统界面语言猜一个默认值。"""
    try:
        import ctypes
        # 中文系 UI 语言的低字节都是 0x04（zh-CN/TW/HK/SG/MO）
        if ctypes.windll.kernel32.GetUserDefaultUILanguage() & 0xFF == 0x04:
            return "zh"
    except Exception:
        pass
    try:
        if (locale.getdefaultlocale()[0] or "").lower().startswith("zh"):
            return "zh"
    except Exception:
        pass
    return "en"


def init_lang(explicit: str = "") -> str:
    """启动时定语言：命令行指定 > 上次保存 > 系统猜测。"""
    code = explicit if explicit in LANGS else load_saved_lang()
    set_lang(code)
    return code


set_lang(load_saved_lang())
