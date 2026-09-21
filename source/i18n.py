# -*- coding: utf-8 -*-
"""
i18n.py -- 中 / 英 / 日三语文案表。

界面文字、运行日志、解析报错统一走这里，切语言时只需 set_lang()。

用法：
    from i18n import tr, set_lang, get_lang
    tr("btn.scan")                       # -> "扫描源" / "Scan Sources" / "ソースをスキャン"
    tr("log.scan_done", count=40)        # -> "扫描完成：40 个 tpac"

规则：
  * 带参数的文案一律用 **命名占位符** %(name)s，因为 tr() 内部是 text % kwargs。
  * 新增文案要给 zh / en / ja 三份；缺哪门语言会自动回退到中文，不会把 key 丢给用户。
"""
from __future__ import annotations

import json
import locale
import os
import sys
import threading

LANGS = ("zh", "en", "ja")

_LANG = "zh"
_LOCK = threading.RLock()

CONFIG_NAME = "ui_config.json"

STRINGS = {
    # -------------------------------------------------------------- 界面
    "app.title": {"zh": "Bannerlord TPAC 批量迁移工具",
                  "en": "Bannerlord TPAC Batch Migrator",
                  "ja": "Bannerlord TPAC 一括移行ツール"},
    "app.subtitle": {"zh": "把 .tpac 资源包迁移到别的 mod，自动重映射包内被锁死的路径引用",
                     "en": "Move .tpac packages to another mod and remap their locked asset paths",
                     "ja": ".tpac パッケージを別の mod に移行し、内部の固定パスを自動再マップ"},
    "app.lang": {"zh": "界面语言：", "en": "Language:", "ja": "表示言語："},

    "sec.sources": {"zh": "1. 源与目标", "en": "1. Source & Target", "ja": "1. ソースとターゲット"},
    "lbl.sources": {"zh": "源（mod 目录 / 单个 .tpac）",
                    "en": "Source (mod folder / single .tpac)",
                    "ja": "ソース（mod フォルダ / 単一の .tpac）"},
    "btn.add_dir": {"zh": "添加目录…", "en": "Add Folder…", "ja": "フォルダ追加…"},
    "btn.add_files": {"zh": "添加文件…", "en": "Add Files…", "ja": "ファイル追加…"},
    "btn.remove": {"zh": "移除选中", "en": "Remove Selected", "ja": "選択を削除"},
    "btn.clear": {"zh": "清空", "en": "Clear", "ja": "クリア"},
    "btn.find_game": {"zh": "查找游戏目录…", "en": "Locate Game Folder…", "ja": "ゲームフォルダを探す…"},
    "lbl.target": {"zh": "目标模块目录", "en": "Target module folder", "ja": "ターゲットモジュールフォルダ"},
    "lbl.subdir": {
        "zh": " 子文件夹",
        "en": " Subfolder",
        "ja": " サブフォルダ",
    },
    "lbl.subdir_hint": {
        "zh": "留空 = 按源分类自动放置（rome_items → Assets/rome_items/）",
        "en": "leave empty = mirror source folders (rome_items → Assets/rome_items/)",
        "ja": "空欄 = ソースの分類をそのまま再現（rome_items → Assets/rome_items/）",
    },
    "btn.browse": {"zh": "浏览…", "en": "Browse…", "ja": "参照…"},
    "lbl.module": {"zh": "目标模块名", "en": "Target module name", "ja": "ターゲットモジュール名"},
    "lbl.module_hint": {"zh": "（用于生成 $BASE/Modules/<模块名>/ 替换规则）",
                        "en": "(used to build $BASE/Modules/<name>/ rules)",
                        "ja": "（$BASE/Modules/<モジュール名>/ の置換ルール生成に使用）"},
    "btn.scan": {"zh": "扫描源", "en": "Scan Sources", "ja": "ソースをスキャン"},
    "btn.cancel_scan": {"zh": "取消扫描", "en": "Cancel Scan", "ja": "スキャンをキャンセル"},
    "lbl.scan_hint": {"zh": "扫描后会自动建议重映射规则",
                      "en": "Remap rules are suggested after scanning",
                      "ja": "スキャン後に再マップルールを自動提案します"},

    "sec.results": {"zh": "2. 扫描结果（点击首列勾选要迁移的包）",
                    "en": "2. Scan Results (click the first column to select)",
                    "ja": "2. スキャン結果（最初の列をクリックして移行対象を選択）"},
    "col.sel": {"zh": "✓", "en": "✓", "ja": "✓"},
    "col.module": {"zh": "源模块", "en": "Source Module", "ja": "ソースモジュール"},
    "col.path": {"zh": "文件", "en": "File", "ja": "ファイル"},
    "col.size": {"zh": "大小", "en": "Size", "ja": "サイズ"},
    "col.items": {"zh": "条目", "en": "Items", "ja": "アイテム"},
    "col.ext": {"zh": "包外依赖", "en": "External Deps", "ja": "外部依存"},
    "col.cache": {"zh": "缓存", "en": "Cache", "ja": "キャッシュ"},
    "col.cache_material": {"zh": "材质无需", "en": "Material (no cache)", "ja": "マテリアル（キャッシュ不要）"},
    "col.cache_missing": {"zh": "缺失", "en": "Missing", "ja": "欠落"},
    "col.cache_bundled": {
        "zh": "自包含",
        "en": "Self-contained",
        "ja": "自己完結",
    },
    "col.types": {"zh": "内容", "en": "Contents", "ja": "内容"},
    "btn.toggle_all": {"zh": "全选 / 全不选", "en": "Select All / None", "ja": "全選択 / 全解除"},

    "sec.rules": {"zh": "3. 路径重映射规则", "en": "3. Path Remap Rules", "ja": "3. パス再マップルール"},
    "col.on": {"zh": "启用", "en": "On", "ja": "有効"},
    "col.old": {"zh": "原字符串", "en": "Original", "ja": "元の文字列"},
    "col.new": {"zh": "替换为", "en": "Replace With", "ja": "置換先"},
    "col.note": {"zh": "说明", "en": "Note", "ja": "説明"},
    "types.sep": {"zh": "，", "en": ", ", "ja": "、"},
    "btn.suggest": {"zh": "自动建议", "en": "Suggest", "ja": "自動提案"},
    "btn.add": {"zh": "添加…", "en": "Add…", "ja": "追加…"},
    "btn.edit": {"zh": "编辑…", "en": "Edit…", "ja": "編集…"},
    "btn.del": {"zh": "删除", "en": "Delete", "ja": "削除"},
    "lbl.rule_safety": {"zh": "长度可变的替换只会在带长度前缀的字符串上执行，安全",
                        "en": "Variable-length rewrites only apply to length-prefixed strings — safe",
                        "ja": "可変長置換は長さプレフィックス付きの文字列のみに適用されるため安全です"},

    "sec.options": {"zh": "4. 选项", "en": "4. Options", "ja": "4. オプション"},
    "chk.backup": {"zh": "覆盖前备份原文件", "en": "Back up before overwriting", "ja": "上書き前に元ファイルをバックアップ"},
    "chk.relative": {
        "zh": "按源分类放置（推荐开）",
        "en": "Mirror source folders (recommended)",
        "ja": "ソースの分類を再現（推奨）",
    },
    "chk.deep_scan": {
        "zh": "深度扫描段（慢，通常不需要）",
        "en": "Deep-scan segments (slow, rarely needed)",
        "ja": "セグメントを深くスキャン（低速・通常不要）",
    },
    "chk.verify": {"zh": "写盘后结构自检", "en": "Verify structure after write", "ja": "書き込み後に構造を自己検証"},
    "lbl.conflict": {"zh": "同名冲突：", "en": "On conflict:", "ja": "ファイル名が重複した場合："},

    "btn.run": {"zh": "开始迁移", "en": "Start Migration", "ja": "移行を開始"},
    "btn.dry": {"zh": "预演（只看不改）", "en": "Dry Run (no writes)", "ja": "ドライラン（書き込みなし）"},
    "btn.rollback": {"zh": "回滚上次迁移", "en": "Rollback Last Migration", "ja": "前回の移行をロールバック"},

    "status.ready": {"zh": "就绪", "en": "Ready", "ja": "準備完了"},
    "status.scanning": {"zh": "扫描中…", "en": "Scanning…", "ja": "スキャン中…"},
    "status.discovering": {"zh": "正在列出 .tpac…", "en": "Listing .tpac files…", "ja": ".tpac ファイル一覧を作成中…"},
    "status.scan_count": {"zh": "扫描中，共 %(count)d 个包",
                          "en": "Scanning %(count)d packages",
                          "ja": "スキャン中、合計 %(count)d 個のパッケージ"},
    "status.cancelling": {"zh": "正在取消…", "en": "Cancelling…", "ja": "キャンセル中…"},
    "status.scan_cancelled": {"zh": "已取消扫描", "en": "Scan cancelled", "ja": "スキャンをキャンセルしました"},
    "status.scan_progress": {"zh": "扫描中 %(a)d/%(b)d", "en": "Scanning %(a)d/%(b)d", "ja": "スキャン中 %(a)d/%(b)d"},
    "status.scan_done": {"zh": "扫描完成：%(count)d 个包",
                         "en": "Scan complete: %(count)d packages",
                         "ja": "スキャン完了：%(count)d 個のパッケージ"},
    "status.migrating": {"zh": "迁移中…", "en": "Migrating…", "ja": "移行中…"},
    "status.done": {"zh": "迁移完成", "en": "Migration complete", "ja": "移行完了"},
    "status.error": {"zh": "出错了", "en": "Error", "ja": "エラーが発生しました"},
    "status.finding_game": {"zh": "正在查找游戏目录…", "en": "Locating game folder…", "ja": "ゲームフォルダを検索中…"},

    # -------------------------------------------------------------- 弹窗
    "dlg.title": {"zh": "提示", "en": "Notice", "ja": "通知"},
    "dlg.add_dir": {"zh": "选择包含 .tpac 的目录", "en": "Choose a folder containing .tpac files",
                    "ja": ".tpac を含むフォルダを選択"},
    "dlg.add_files": {"zh": "选择 .tpac 文件", "en": "Choose .tpac files", "ja": ".tpac ファイルを選択"},
    "filetype.tpac": {"zh": "TPAC 资源包", "en": "TPAC package", "ja": "TPAC パッケージ"},
    "filetype.all": {"zh": "所有文件", "en": "All files", "ja": "すべてのファイル"},
    "dlg.target": {"zh": "选择目标模块目录", "en": "Choose target module folder", "ja": "ターゲットモジュールフォルダを選択"},
    "dlg.no_modules_title": {"zh": "未找到模块", "en": "No Modules Folder", "ja": "Modules フォルダが見つかりません"},
    "dlg.no_modules": {"zh": "该目录下没有 Modules 文件夹",
                       "en": "There is no Modules folder under that directory",
                       "ja": "選択したディレクトリに Modules フォルダがありません"},
    "dlg.pick_module": {"zh": "选择模块", "en": "Select Module", "ja": "モジュールを選択"},
    "dlg.pick_module_hint": {"zh": "双击一个模块，把它作为迁移源",
                             "en": "Double-click a module to use it as a migration source",
                             "ja": "モジュールをダブルクリックして移行ソースとして使用"},
    "btn.ok": {"zh": "确定", "en": "OK", "ja": "OK"},
    "btn.save": {"zh": "保存", "en": "Save", "ja": "保存"},
    "dlg.rule_add": {"zh": "添加规则", "en": "Add Rule", "ja": "ルールを追加"},
    "dlg.rule_edit": {"zh": "编辑规则", "en": "Edit Rule", "ja": "ルールを編集"},
    "dlg.rule_old": {"zh": "原字符串（包内实际存在的内容）",
                     "en": "Original string (must actually exist inside the package)",
                     "ja": "元の文字列（パッケージ内に実際に存在する内容）"},
    "dlg.rule_new": {"zh": "替换为", "en": "Replace with", "ja": "置換先"},
    "warn.empty_old": {"zh": "原字符串不能为空", "en": "The original string cannot be empty",
                       "ja": "元の文字列を空にできません"},
    "dlg.not_found": {"zh": "未找到", "en": "Not Found", "ja": "見つかりません"},
    "dlg.game_not_found": {"zh": "没有在常见位置找到游戏安装目录，请手动选择",
                           "en": "Game folder not found in the usual locations; please pick it manually",
                           "ja": "一般的な場所にゲームフォルダが見つかりません。手動で選択してください"},
    "dlg.rollback_title": {"zh": "确认", "en": "Confirm", "ja": "確認"},
    "dlg.rollback_msg": {"zh": "将删除上次迁移写入的文件，并还原被覆盖的备份。继续？",
                         "en": "This deletes files written by the last migration and restores backups. Continue?",
                         "ja": "前回の移行で書き込まれたファイルを削除し、上書きされたバックアップを復元します。続行しますか？"},
    "dlg.name_mismatch_title": {"zh": "文件夹名与模块 Id 不一致",
                                "en": "Folder name differs from module Id",
                                "ja": "フォルダ名とモジュール Id が一致しません"},

    "msg.name_mismatch_confirm": {
        "zh": "目标模块的文件夹叫「%(folder)s」，但它在 SubModule.xml 里声明的 Id 是「%(id)s」。\n\n"
              "包内写死的 $BASE/Modules/〈名字〉/ 路径只能是两者之一，所以必有一边解析不到——"
              "实测表现是：装备能进游戏、能装备，但模型一片空白，日志里一句报错都没有。\n\n"
              "最省事的修法是把文件夹改名为 %(id)s，然后把「目标模块名」也填成 %(id)s。\n\n"
              "仍要按当前设置继续迁移吗？",
        "en": "The target module folder is named \"%(folder)s\", but the Id declared in its "
              "SubModule.xml is \"%(id)s\".\n\n"
              "The $BASE/Modules/〈name〉/ paths baked into the packages can only match one of "
              "them, so one side is guaranteed to fail — in practice the item shows up in game "
              "and can be equipped, but the model is blank and the log reports nothing.\n\n"
              "Easiest fix: rename the folder to %(id)s, then set the target module name to "
              "%(id)s as well.\n\n"
              "Continue the migration with the current settings anyway?",
        "ja": "ターゲットモジュールのフォルダ名は「%(folder)s」ですが、SubModule.xml に宣言された Id は「%(id)s」です。\n\n"
              "パッケージに書き込まれた $BASE/Modules/〈名前〉/ パスはどちらか一方にのみ一致するため、必ず一方が解決されません。"
              "実際はアイテムはゲームに表示され装備できますが、モデルは真っ白で、ログにはエラーが出力されません。\n\n"
              "最も簡単な修正方法は、フォルダ名を %(id)s に変更し、「ターゲットモジュール名」も %(id)s に設定することです。\n\n"
              "現在の設定で移行を続行しますか？",
    },

    "msg.no_source": {"zh": "请先添加源目录或 .tpac 文件",
                      "en": "Add a source folder or .tpac file first",
                      "ja": "先にソースフォルダまたは .tpac ファイルを追加してください"},
    "msg.need_scan": {"zh": "请先扫描，工具会依据包内真实出现的路径来建议规则",
                      "en": "Scan first — rules come from paths actually found inside the packages",
                      "ja": "先にスキャンしてください。ルールはパッケージ内から実際に見つかったパスから生成されます"},
    "msg.need_module_suggest": {"zh": "请先填写目标模块名",
                                "en": "Enter the target module name first",
                                "ja": "先にターゲットモジュール名を入力してください"},
    "msg.need_module": {"zh": "请填写目标模块名", "en": "Enter the target module name",
                        "ja": "ターゲットモジュール名を入力してください"},
    "msg.need_select": {"zh": "请在扫描结果里勾选要迁移的包",
                        "en": "Select the packages to migrate in the scan results",
                        "ja": "スキャン結果で移行対象のパッケージを選択してください"},
    "msg.need_target": {"zh": "请先选择目标模块目录",
                        "en": "Choose the target module folder first",
                        "ja": "先にターゲットモジュールフォルダを選択してください"},
    "msg.need_rules": {
        "zh": "规则列表是空的，迁移已被拦下。\n\n"
              "规则决定包内的 $BASE/Modules/〈模块名〉/ 路径要改成什么。没有规则，"
              "工具只会把文件原样复制，包内路径仍指向原模块——进游戏就是找不到模型和贴图，"
              "却看不出任何报错。\n\n"
              "另外两点容易踩坑：\n"
              "1. 目标模块的文件夹名和它 SubModule.xml 里的 Id 必须一致（例如都叫 test_transe）。"
              "包内路径只能对上其中一个，不一致就必然失效。\n"
              "2. 源模块若带 RuntimeDataCache/（只有用编辑器烘焙过资源的机器才有，"
              "下载来的 mod 通常没有），工具会把每个包对应的 <GUID>.rdc 一并搬过去；"
              "没有这个目录也完全正常，引擎会自己生成。\n\n"
              "请先点「自动建议」，或手动「添加」一条规则。",
        "en": "The rule list is empty, so the migration was blocked.\n\n"
              "Rules decide what the $BASE/Modules/〈module〉/ paths inside the packages "
              "become. Without any rule the tool would only copy files verbatim, leaving "
              "them pointing at the original module — the game then finds no meshes or "
              "textures, without reporting anything.\n\n"
              "Two things that are easy to get wrong:\n"
              "1. The target module's folder name and the Id in its SubModule.xml must be "
              "identical (e.g. both test_transe). Package paths can only match one of them, "
              "so any mismatch is guaranteed to fail.\n"
              "2. If the source module has RuntimeDataCache/ (only machines that baked "
              "assets in the editor have it; downloaded mods usually do not), the tool "
              "moves each package's <GUID>.rdc along; a missing folder is perfectly "
              "normal — the engine regenerates it on demand.\n\n"
              "Click \"Suggest\" first, or add a rule manually.",
        "ja": "ルールリストが空のため、移行はブロックされました。\n\n"
              "ルールは、パッケージ内の $BASE/Modules/〈モジュール名〉/ パスを何に置換するかを決定します。"
              "ルールがないと、ツールはファイルをそのままコピーするだけで、パッケージ内のパスは元のモジュールを指したままになります。"
              "ゲームはモデルやテクスチャを見つけられず、エラーも出力されません。\n\n"
              "よくある落とし穴が 2 つあります：\n"
              "1. ターゲットモジュールのフォルダ名と SubModule.xml 内の Id は必ず一致させてください（例：両方とも test_transe）。"
              "パッケージ内パスはどちらか一方にしか一致しないため、不一致は確実に失敗します。\n"
              "2. ソースモジュールに RuntimeDataCache/ がある場合（エディタでアセットをベイクした機体のみ。"
              "ダウンロードした MOD には通常ありません）、各パッケージに対応する <GUID>.rdc も一緒に移行します。"
              "このフォルダが無くても全く問題ありません（エンジンが自動生成します）。\n\n"
              "まず「自動提案」をクリックするか、手動で「追加…」からルールを追加してください。",
    },
    "warn.name_mismatch": {
        "zh": "⚠ 目标文件夹叫「%(folder)s」，模块 Id 是「%(id)s」，两者必须一致。"
              "包内路径只能对上其中一个，不一致时资源必然显示不出来（而且游戏不报错）。"
              "请把文件夹改名为 %(id)s，并把「目标模块名」也改成 %(id)s。",
        "en": "⚠ Target folder is \"%(folder)s\" but the module Id is \"%(id)s\" — these must "
              "match. Package paths can only match one of them, so resources are guaranteed "
              "to fail to load (silently, with no error in the log). Rename the folder to "
              "%(id)s and set the target module name to %(id)s.",
        "ja": "⚠ ターゲットフォルダは「%(folder)s」ですが、モジュール Id は「%(id)s」です。両者を一致させる必要があります。"
              "パッケージ内パスはどちらか一方にのみ一致するため、不一致の場合はリソースが確実に表示されません"
              "（しかもゲームはエラーを出力しません）。フォルダ名を %(id)s に変更し、「ターゲットモジュール名」も %(id)s に変更してください。",
    },

    # -------------------------------------------------------------- 日志
    "log.no_tpac": {"zh": "没有找到任何 .tpac 文件", "en": "No .tpac files found", "ja": ".tpac ファイルが見つかりません"},
    "log.discovering_done": {"zh": "已发现 %(count)d 个 .tpac，开始逐个解析",
                             "en": "Found %(count)d .tpac files, parsing them now",
                             "ja": "%(count)d 個の .tpac を検出しました。順次解析します"},
    "log.scan_cancelled": {"zh": "扫描已取消（已解析 %(count)d 个）",
                           "en": "Scan cancelled after %(count)d packages",
                           "ja": "スキャンをキャンセルしました（%(count)d 個解析済み）"},
    "log.scan_done": {"zh": "扫描完成：%(count)d 个 tpac",
                      "en": "Scan complete: %(count)d tpac",
                      "ja": "スキャン完了：%(count)d 個の tpac"},
    "log.externals": {"zh": "发现 %(count)d 个指向包外的依赖引用；这类依赖需要目标环境同样能解析到",
                      "en": "Found %(count)d references pointing outside the package; the target must be able to resolve them",
                      "ja": "パッケージ外を参照している依存関係を %(count)d 個検出しました。ターゲット環境でもこれらが解決できる必要があります"},
    "log.cache_scan": {
        "zh": "其中 %(count)d 个包在源模块的 RuntimeDataCache/ 里找到了对应缓存，迁移时会一并带走"
              "（材质包本来就没有缓存，列里显示「—」是正常的）",
        "en": "%(count)d packages have a matching cache in the source module's RuntimeDataCache/ and will "
              "be moved along (material packages never have one — a \"—\" in that column is normal)",
        "ja": "%(count)d 個のパッケージに対応するキャッシュがソースモジュールの RuntimeDataCache/ に見つかりました。"
              "これらも一緒に移行されます（マテリアルパッケージには元々キャッシュがないため、その列に「—」が表示されるのは正常です）",
    },
    "log.cache_none": {
        "zh": "没有任何包在源模块里找到运行时缓存。若这些包在游戏里本来就是正常显示的，"
              "说明缓存放在别处；否则请先确认源模块目录选对了。",
        "en": "None of the packages has a runtime cache in the source module. If these packages already "
              "render fine in game, the cache simply lives elsewhere; otherwise double-check the source.",
        "ja": "ソースモジュールにランタイムキャッシュが見つかりません。これらのパッケージがゲームで正常に表示される場合、"
              "キャッシュは別の場所にあります。そうでない場合はソースモジュールディレクトリが正しいか確認してください。",
    },
    "log.cache_audit_only_material": {
        "zh": "缓存完整性：共 %(material)d 个材质包，无需缓存（已自动跳过）",
        "en": "Cache audit: %(material)d material package(s) — no cache needed (auto-skipped)",
        "ja": "キャッシュ整合性：合計 %(material)d 個のマテリアルパッケージ、キャッシュ不要（自動スキップ済み）",
    },
    "log.cache_audit_bundled": {
        "zh": "%(bundled)d 个打包文件（AssetPackages/）数据自包含，不需要缓存，已从统计中排除",
        "en": "%(bundled)d bundle file(s) (AssetPackages/) are self-contained and need no cache — excluded from the audit",
        "ja": "%(bundled)d 個のバンドルファイル（AssetPackages/）は自己完結のためキャッシュ不要、集計から除外しました",
    },
    "log.layout_mirror": {
        "zh": "落点：按源分类镜像 —— 源里的 Assets/rome_items/ 会落到目标 Assets/rome_items/",
        "en": "Layout: mirror the source — Assets/rome_items/ lands at the target's Assets/rome_items/",
        "ja": "配置：ソースの分類を再現 —— ソースの Assets/rome_items/ はターゲットの Assets/rome_items/ に配置されます",
    },
    "log.layout_subdir": {
        "zh": "落点：全部归入 %(dst)s/",
        "en": "Layout: everything under %(dst)s/",
        "ja": "配置：すべて %(dst)s/ に格納",
    },
    "log.layout_flat": {
        "zh": "落点：平铺到模块根（不保留分类子文件夹）",
        "en": "Layout: flat into the module root (no category subfolders)",
        "ja": "配置：モジュールルートにフラット配置（分類フォルダなし）",
    },
    "log.cache_audit_ok": {
        "zh": "缓存完整性：应带 %(expected)d 个，源模块齐全；其中 %(material)d 个是材质包无需缓存",
        "en": "Cache audit: %(expected)d expected — source module has them all; "
              "%(material)d material package(s) need no cache",
        "ja": "キャッシュ整合性：%(expected)d 個が必要です。ソースモジュールにすべて揃っています。"
              "このうち %(material)d 個はマテリアルパッケージでキャッシュ不要",
    },
    "log.cache_audit_missing": {
        "zh": "缓存完整性：应带 %(expected)d 个，源模块仅齐 %(ok)d 个，缺失 %(miss)d 个；"
              "其中 %(material)d 个是材质包无需缓存（缺失会标红但**不阻止迁移**）",
        "en": "Cache audit: %(expected)d expected, source has %(ok)d, missing %(miss)d; "
              "%(material)d material package(s) need no cache (missing entries are flagged in red "
              "but do NOT block the migration)",
        "ja": "キャッシュ整合性：%(expected)d 個が必要ですが、ソースモジュールには %(ok)d 個しかなく、%(miss)d 個が欠落しています。"
              "このうち %(material)d 個はマテリアルパッケージでキャッシュ不要です（欠落は赤でマークされますが、移行はブロックされません）",
    },
    "log.cache_audit_more": {
        "zh": "    … 剩余 %(n)d 个未列出",
        "en": "    … %(n)d more not shown",
        "ja": "    … 残り %(n)d 個は表示されていません",
    },
    "log.cache_audit_target_ok": {
        "zh": "目标模块校验：%(ok)d 个缓存全部到位",
        "en": "Target module check: all %(ok)d caches in place",
        "ja": "ターゲットモジュール検証：%(ok)d 個のキャッシュはすべて配置済み",
    },
    "log.cache_audit_target_missing": {
        "zh": "目标模块校验：%(ok)d 个到位，缺失 %(miss)d 个（写入失败 / 文件被占 / 磁盘满）",
        "en": "Target module check: %(ok)d in place, missing %(miss)d (write failed / file locked / disk full)",
        "ja": "ターゲットモジュール検証：%(ok)d 個配置済み、%(miss)d 個欠落（書き込み失敗 / ファイルロック中 / ディスク満杯）",
    },
    "log.suggest_none": {"zh": "没有发现需要重映射的模块路径（可能包内没有 $BASE/Modules/… 形式的引用）",
                         "en": "No module paths need remapping (packages may hold no $BASE/Modules/… references)",
                         "ja": "再マップが必要なモジュールパスが見つかりません（パッケージに $BASE/Modules/… 形式の参照がない可能性があります）"},
    "log.suggest_done": {"zh": "已建议 %(total)d 条规则（新增 %(added)d）",
                         "en": "Suggested %(total)d rules (%(added)d new)",
                         "ja": "%(total)d 件のルールを提案しました（%(added)d 件新規）"},
    "log.no_rules": {"zh": "规则列表为空，已阻止迁移——否则只会把文件原样复制，包内路径不会被改写",
                     "en": "Rule list is empty; migration blocked — files would be copied verbatim with no path rewrite",
                     "ja": "ルールリストが空のため、移行をブロックしました — そうしないとファイルがそのままコピーされ、パスが書き換えられません"},
    "log.no_rules_dry": {"zh": "警告：规则列表为空，下面的预演结果仅供参考；实际迁移会被拦住",
                         "en": "Warning: rule list is empty; the preview below is informational only — a real run would be blocked",
                         "ja": "警告：ルールリストが空のため、以下のプレビューは参考用です。実際の移行はブロックされます"},
    "log.module_id_mismatch": {"zh": "提示：目标目录所属模块声明的 Id 是「%(want)s」，而你填的是「%(got)s」。两者必须一致，否则包内路径必有一边解析不到",
                               "en": "Note: the target module declares Id \"%(want)s\" but you entered \"%(got)s\". These must match, or one side of the package paths will fail to resolve",
                               "ja": "注意：ターゲットディレクトリが所属するモジュールの Id は「%(want)s」ですが、入力された値は「%(got)s」です。両者を一致させる必要があります。さもないとパッケージパスのどちらかが解決されません"},
    "log.dry_header": {"zh": "预演模式：仅列出将要写入的位置，不改动任何文件",
                       "en": "Dry run: listing destinations only, nothing is written",
                       "ja": "ドライランモード：書き込み先の一覧のみ表示し、ファイルは一切変更しません"},
    "log.dry_total": {"zh": "共 %(count)d 个包待迁移", "en": "%(count)d packages pending",
                      "ja": "合計 %(count)d 個のパッケージが移行待ち"},
    "log.plan_header": {
        "zh": "迁移落点（前 20 个示例，可事后到目标模块核对）",
        "en": "Destinations (first 20 shown — verify in the target module)",
        "ja": "移行先（先頭 20 件の例、ターゲットモジュールで確認できます）",
    },
    "log.plan_more": {
        "zh": "……其余 %(count)d 个包从略",
        "en": "…%(count)d more package(s) omitted",
        "ja": "…残り %(count)d 個は省略",
    },
    "log.migrate_done": {"zh": "迁移完成", "en": "Migration complete", "ja": "移行完了"},
    "log.rollback_done": {"zh": "回滚完成", "en": "Rollback complete", "ja": "ロールバック完了"},
    "log.parse_failed": {"zh": "解析失败：%(err)s", "en": "Parse failed: %(err)s", "ja": "解析失敗：%(err)s"},
    "log.lang_switched": {"zh": "界面语言已切换为%(name)s",
                          "en": "Interface language switched to %(name)s",
                          "ja": "表示言語を %(name)s に切り替えました"},

    # -------------------------------------------------------------- 自检
    "smoke.not_found": {"zh": "自检：未找到游戏目录，跳过",
                        "en": "Smoke: game folder not found, skipping",
                        "ja": "スモーク：ゲームフォルダが見つからないためスキップ"},
    "smoke.start": {"zh": "自检：开始迁移", "en": "Smoke: starting migration",
                    "ja": "スモーク：移行開始"},
    "smoke.cleanup": {"zh": "自检：已清理临时产物 %(path)s",
                      "en": "Smoke: cleaned temp output %(path)s",
                      "ja": "スモーク：一時ファイル %(path)s を削除しました"},
    "smoke.cleanup_fail": {"zh": "自检：清理失败 %(err)s",
                           "en": "Smoke: cleanup failed %(err)s",
                           "ja": "スモーク：クリーンアップ失敗 %(err)s"},

    # -------------------------------------------------------------- 规则来源
    "note.occurrences": {"zh": "出现在 %(count)d 处", "en": "occurs in %(count)d places",
                         "ja": "%(count)d 箇所に出現"},
    "note.manual": {"zh": "手动添加", "en": "Manual", "ja": "手動追加"},

    # -------------------------------------------------------------- 迁移日志
    "mig.skip_exists": {"zh": "[%(a)d/%(b)d] 跳过（已存在）：%(name)s",
                        "en": "[%(a)d/%(b)d] Skipped (exists): %(name)s",
                        "ja": "[%(a)d/%(b)d] スキップ（既に存在）：%(name)s"},
    "mig.backup_fail": {"zh": "  备份失败：%(err)s", "en": "  Backup failed: %(err)s",
                        "ja": "  バックアップ失敗：%(err)s"},
    "mig.result": {"zh": "   -> %(name)s（%(items)d 条目，改写 %(rewrites)d 处，"
                        "%(before)s -> %(after)s 字节）",
                   "en": "   -> %(name)s (%(items)d items, %(rewrites)d rewritten, "
                         "%(before)s -> %(after)s bytes)",
                   "ja": "   -> %(name)s（%(items)d アイテム、%(rewrites)d 箇所書き換え、"
                         "%(before)s -> %(after)s バイト）"},
    "mig.ext_refs": {"zh": "   注意：存在 %(count)d 个包外依赖 GUID，需确认目标模块能解析",
                     "en": "   Note: %(count)d dependencies point outside the package; "
                           "make sure the target module can resolve them",
                     "ja": "   注意：パッケージ外の依存 GUID が %(count)d 個あります。"
                           "ターゲットモジュールでこれらが解決できるか確認してください"},
    "mig.failed": {"zh": "   失败：%(err)s", "en": "   Failed: %(err)s", "ja": "   失敗：%(err)s"},
    "mig.warn": {"zh": "   警告：%(msg)s", "en": "   Warning: %(msg)s", "ja": "   警告：%(msg)s"},
    "mig.journal": {"zh": "迁移记录：%(path)s", "en": "Migration journal: %(path)s",
                    "ja": "移行ジャーナル：%(path)s"},
    "mig.journal_fail": {"zh": "无法写入迁移记录：%(err)s",
                         "en": "Cannot write migration journal: %(err)s",
                         "ja": "移行ジャーナルへの書き込みに失敗：%(err)s"},
    "mig.no_journal": {"zh": "没有找到迁移记录，无法回滚",
                       "en": "No migration journal found; cannot roll back",
                       "ja": "移行ジャーナルが見つからないため、ロールバックできません"},
    "mig.rollback_fail": {"zh": "回滚失败 %(path)s：%(err)s",
                          "en": "Rollback failed %(path)s: %(err)s",
                          "ja": "ロールバック失敗 %(path)s：%(err)s"},
    "mig.rollback_done": {"zh": "已回滚 %(count)d 个文件", "en": "Rolled back %(count)d files",
                          "ja": "%(count)d 個のファイルをロールバックしました"},
    "mig.skipped_reason": {"zh": "目标已存在，按策略跳过",
                           "en": "Target exists; skipped by policy",
                           "ja": "ターゲットが既に存在するため、ポリシーに従ってスキップ"},
    "mig.err_seg_len": {"zh": "段解压长度不符：%(name)s",
                        "en": "Decompressed size mismatch: %(name)s",
                        "ja": "セグメントの展開サイズが一致しません：%(name)s"},
    "mig.err_item_count": {"zh": "条目数不一致：源 %(before)d -> 产物 %(after)d",
                           "en": "Item count mismatch: source %(before)d -> output %(after)d",
                           "ja": "アイテム数が一致しません：ソース %(before)d -> 出力 %(after)d"},

    # -------------------------------------------------------------- 运行时缓存
    "mig.cache_copied": {"zh": "   缓存：%(name)s（%(size)s，已随包复制）",
                         "en": "   Cache: %(name)s (%(size)s, copied along)",
                         "ja": "   キャッシュ：%(name)s（%(size)s、パッケージと共にコピー済み）"},
    "mig.cache_overwritten": {
        "zh": "   缓存：%(name)s（%(size)s，覆盖了目标模块中的同名缓存）",
        "en": "   Cache: %(name)s (%(size)s, overwrote the same-name cache in the target)",
        "ja": "   キャッシュ：%(name)s（%(size)s、ターゲットモジュールの同名キャッシュを上書き）",
    },
    "mig.cache_fail": {"zh": "缓存复制失败：%(err)s —— 少了它，目标模块里这件装备会显示空白",
                       "en": "Cache copy failed: %(err)s — without it the matching item renders blank in the target",
                       "ja": "キャッシュのコピー失敗：%(err)s — これがないと、ターゲットモジュールで対応するアイテムが空白で表示されます"},
    "mig.cache_backup_fail": {"zh": "缓存备份失败：%(err)s", "en": "Cache backup failed: %(err)s",
                              "ja": "キャッシュのバックアップ失敗：%(err)s"},
    "mig.cache_summary": {
        "zh": "运行时缓存：新增 %(copied)d，覆盖 %(overwritten)d，已存在 %(same)d，"
              "按策略跳过 %(skipped)d，源内无缓存 %(missing)d（材质包通常如此），失败 %(failed)d",
        "en": "RuntimeDataCache: %(copied)d added, %(overwritten)d overwritten, "
              "%(same)d already present, %(skipped)d skipped by policy, "
              "%(missing)d absent in source (usual for material packages), %(failed)d failed",
        "ja": "RuntimeDataCache：%(copied)d 個追加、%(overwritten)d 個上書き、%(same)d 個既存、"
              "%(skipped)d 個ポリシーでスキップ、%(missing)d 個ソースに無し（マテリアルパッケージでは通常）、%(failed)d 個失敗",
    },

    # -------------------------------------------------------------- 命令行
    "cli.desc": {"zh": "批量迁移 Bannerlord .tpac 资源包",
                 "en": "Batch-migrate Bannerlord .tpac asset packages",
                 "ja": "Bannerlord .tpac アセットパッケージを一括移行"},
    "cli.source": {"zh": "源目录或 .tpac 文件（可多个；--rollback 时不需要）",
                   "en": "Source folder or .tpac files (repeatable; not needed with --rollback)",
                   "ja": "ソースフォルダまたは .tpac ファイル（複数指定可；--rollback では不要）"},
    "cli.target": {"zh": "目标模块目录", "en": "Target module folder", "ja": "ターゲットモジュールフォルダ"},
    "cli.from": {"zh": "源模块名（用于生成替换规则）",
                 "en": "Source module name (used to build replace rules)",
                 "ja": "ソースモジュール名（置換ルール生成に使用）"},
    "cli.to": {"zh": "目标模块名（默认取目标模块的文件夹名）",
               "en": "Target module name (defaults to the target module's folder name)",
               "ja": "ターゲットモジュール名（既定ではターゲットモジュールのフォルダ名）"},
    "cli.name_mismatch": {
        "zh": "⚠ 目标文件夹「%(folder)s」与模块 Id「%(id)s」不一致：包内 $BASE/Modules/… 路径只能对上其中一个，必然有一边失效。\n"
              "   建议先把文件夹改名为 %(id)s（启动器按 Id 记录勾选状态，改名不会丢）。",
        "en": "! Target folder \"%(folder)s\" differs from module Id \"%(id)s\": the baked "
              "$BASE/Modules/... paths can only match one of them, so one side is bound to fail.\n"
              "   Recommended: rename the folder to %(id)s (the launcher keys selection by Id, so nothing is lost).",
        "ja": "⚠ ターゲットフォルダ「%(folder)s」とモジュール Id「%(id)s」が一致しません。"
              "パッケージ内の $BASE/Modules/... パスはどちらか一方にしかマッチしないため、必ず一方が失敗します。\n"
              "   推奨：フォルダ名を %(id)s に変更してください（ランチャーは Id を選択状態と紐付けているため、変更しても失われません）。",
    },
    "cli.rule": {"zh": "自定义规则，格式 旧串=新串，可重复",
                 "en": "Custom rule as OLD=NEW, repeatable",
                 "ja": "カスタムルール（OLD=NEW 形式、複数指定可）"},
    "cli.flat": {"zh": "文件直投目标目录（默认行为，保留仅为兼容旧命令）",
                 "en": "Drop files flat into the target dir (default; kept for compatibility)",
                 "ja": "ファイルをターゲットディレクトリにフラット配置（既定動作、旧コマンドとの互換性のため残存）"},
    "cli.keep_relative": {"zh": "按源分类镜像目录结构（默认开启）",
                          "en": "Mirror the source folder tree (on by default)",
                          "ja": "ソースのディレクトリ構造を再現（既定：有効）"},
    "cli.subdir": {
        "zh": "把所有包归入 Assets/<子目录>（留空则按源分类，优先于 --keep-relative）",
        "en": "Put every package under Assets/<subdir> (empty = mirror source; overrides --keep-relative)",
        "ja": "すべてのパッケージを Assets/<サブフォルダ> に格納（空欄ならソースの分類を再現、--keep-relative より優先）",
    },
    "cli.deep_scan": {
        "zh": "深度扫描 segment（默认关闭；实测路径全在 metadata 里，开着只会更慢更占内存）",
        "en": "Deep-scan segments (off by default; paths all live in metadata, so this only costs time and RAM)",
        "ja": "セグメントを深くスキャン（既定：無効。パスはすべて metadata にあるため、有効にすると遅く・メモリを食うだけです）",
    },
    "cli.rollback": {"zh": "回滚最近一次迁移", "en": "Roll back the last migration",
                     "ja": "直近の移行をロールバック"},
    "cli.lang": {"zh": "输出语言：zh / en / ja", "en": "Output language: zh / en / ja",
                 "ja": "出力言語：zh / en / ja"},
    "cli.need_source": {"zh": "请用 --source 指定要迁移的目录或 .tpac 文件",
                        "en": "Specify folders or .tpac files with --source",
                        "ja": "--source で移行対象のフォルダまたは .tpac ファイルを指定してください"},
    "cli.no_files": {"zh": "没有找到 .tpac 文件", "en": "No .tpac files found",
                     "ja": ".tpac ファイルが見つかりません"},
    "cli.scanning": {"zh": "发现 %(count)d 个 tpac，扫描中...",
                     "en": "Found %(count)d tpac, scanning...",
                     "ja": "%(count)d 個の tpac を検出、スキャン中..."},
    "cli.rules_header": {"zh": "\n重映射规则：", "en": "\nRemap rules:", "ja": "\n再マップルール："},
    "cli.rules_none": {"zh": "  （无）", "en": "  (none)", "ja": "  （なし）"},
    "cli.rules_none_warn": {
        "zh": "  ⚠ 没有任何规则：包内 $BASE/Modules/… 路径不会被改写，迁过去进游戏会找不到资源。请用 --from/--to 指定源与目标模块名。",
        "en": "  ! No rules: $BASE/Modules/... paths will not be rewritten and the game will find no assets. Use --from/--to to name the source and target modules.",
        "ja": "  ⚠ ルールがありません。パッケージ内の $BASE/Modules/... パスは書き換えられず、ゲームはアセットを見つけられません。"
              "--from/--to でソースとターゲットのモジュール名を指定してください。",
    },
    "cli.dry_header": {"zh": "\n预演模式，不写盘。目标路径示例：",
                       "en": "\nDry run, nothing will be written. Example destinations:",
                       "ja": "\nドライランモード：書き込みは行いません。書き込み先の例："},
    "cli.cache_line": {"zh": "缓存 %(name)s  ->  %(dst)s",
                       "en": "cache %(name)s  ->  %(dst)s",
                       "ja": "キャッシュ %(name)s  ->  %(dst)s"},
    "cli.cache_none": {"zh": "缓存：源模块内没有对应的 .rdc（材质包通常如此）",
                       "en": "cache: no matching .rdc in the source module (usual for material packages)",
                       "ja": "キャッシュ：ソースモジュールに対応する .rdc がありません（マテリアルパッケージでは通常）"},
    "cli.cache_bundled": {
        "zh": "缓存：不需要（AssetPackages 打包文件自带全部数据）",
        "en": "cache: not needed (self-contained AssetPackages bundle)",
        "ja": "キャッシュ：不要（AssetPackages のバンドルは自己完結）",
    },
    "cli.cache_hint": {
        "zh": "（每个包对应的 RuntimeDataCache/<GUID>.rdc 都会自动一起迁移，落在目标模块根目录下）",
        "en": "(each package's RuntimeDataCache/<GUID>.rdc is migrated along automatically, "
              "landing at the target module root)",
        "ja": "（各パッケージの RuntimeDataCache/<GUID>.rdc は自動的に一緒に移行され、ターゲットモジュールのルートに配置されます）",
    },
    "cli.summary": {"zh": "\n完成：成功 %(ok)d / 共 %(total)d",
                    "en": "\nDone: %(ok)d succeeded / %(total)d total",
                    "ja": "\n完了：成功 %(ok)d / 合計 %(total)d"},

    # -------------------------------------------------------------- 解析报错
    "err.lz4_offset0": {"zh": "LZ4 数据损坏：match offset 为 0",
                        "en": "Corrupt LZ4 data: match offset is 0",
                        "ja": "LZ4 データが破損：match offset が 0"},
    "err.lz4_offset_oob": {"zh": "LZ4 数据损坏：match offset 越界",
                           "en": "Corrupt LZ4 data: match offset out of range",
                           "ja": "LZ4 データが破損：match offset が範囲外"},
    "err.lz4_len": {"zh": "LZ4 解压长度不符：期望 %(a)d，实际 %(b)d",
                    "en": "LZ4 decompressed size mismatch: expected %(a)d, got %(b)d",
                    "ja": "LZ4 展開サイズが一致しません：期待 %(a)d、実際 %(b)d"},
    "err.src_truncated": {"zh": "源文件在 %(path)s 处提前结束",
                          "en": "Source file ended early at %(path)s",
                          "ja": "ソースファイルが %(path)s で途中で終了しています"},
    "err.str_oob": {"zh": "读取字符串越界（偏移 %(pos)d）",
                    "en": "String read out of bounds (offset %(pos)d)",
                    "ja": "文字列読み取りが境界外（オフセット %(pos)d）"},
    "err.str_len": {"zh": "字符串长度异常：%(length)d（偏移 %(pos)d）",
                    "en": "Invalid string length: %(length)d (offset %(pos)d)",
                    "ja": "文字列の長さが異常：%(length)d（オフセット %(pos)d）"},
    "err.file_small": {"zh": "文件过小，不是有效的 tpac",
                       "en": "File too small to be a valid tpac",
                       "ja": "ファイルが小さすぎ、有効な tpac ではありません"},
    "err.magic": {"zh": "不是 tpac 文件（magic=0x%(magic)08X）",
                  "en": "Not a tpac file (magic=0x%(magic)08X)",
                  "ja": "tpac ファイルではありません（magic=0x%(magic)08X）"},
    "err.version": {"zh": "不支持的 tpac 版本：%(version)d",
                    "en": "Unsupported tpac version: %(version)d",
                    "ja": "サポートされていない tpac バージョン：%(version)d"},
    "err.toc_trunc": {"zh": "TOC 在偏移 %(pos)d 处提前结束（需要 %(need)d 字节，实得 %(got)d）",
                      "en": "TOC ended early at offset %(pos)d (need %(need)d bytes, got %(got)d)",
                      "ja": "TOC がオフセット %(pos)d で途中で終了（%(need)d バイト必要、%(got)d バイト取得）"},
    "err.meta_len": {"zh": "metadata 长度异常：%(length)d",
                     "en": "Invalid metadata length: %(length)d",
                     "ja": "metadata の長さが異常：%(length)d"},
    "err.seg_count": {"zh": "segment 数量异常：%(count)d",
                      "en": "Invalid segment count: %(count)d",
                      "ja": "segment 数が異常：%(count)d"},
    "err.seg_oob": {"zh": "segment 数据越界：offset=%(offset)d size=%(size)d，文件 %(total)d 字节",
                    "en": "Segment out of bounds: offset=%(offset)d size=%(size)d, "
                          "file is %(total)d bytes",
                    "ja": "segment データ境界外：offset=%(offset)d size=%(size)d、ファイル %(total)d バイト"},
    "err.dep_count": {"zh": "dependence 数量异常：%(count)d",
                      "en": "Invalid dependence count: %(count)d",
                      "ja": "dependence 数が異常：%(count)d"},
    "err.rewrite_abort": {"zh": "%(where)s：替换次数过多，已中断",
                          "en": "%(where)s: too many replacements, aborted",
                          "ja": "%(where)s：置換回数が多すぎるため中断しました"},
    "err.decompress_fail": {"zh": "%(where)s[%(name)s] 解压失败：%(err)s",
                            "en": "%(where)s[%(name)s] decompression failed: %(err)s",
                            "ja": "%(where)s[%(name)s] 展開失敗：%(err)s"},
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
    """语言配置文件的存放目录。

    源码运行时跟 i18n.py 放一起；打包成 exe 后 __file__ 指向 PyInstaller 的临时
    解包目录（程序退出就被删掉），所以冻结状态下改用 exe 所在目录，语言选择才存得住。
    """
    if getattr(sys, "frozen", False):
        base = os.path.dirname(os.path.abspath(sys.executable))
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, CONFIG_NAME)


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


# Windows UI Language 完整 ID → 默认语言。完整 16 位 ID 才准，
# 只看主语言字节（>>16 / & 0xFF）都会错——比如 zh-CN = 0x0804，
# 主语言字节是 0x08，写成 `== 0x04` 永远不命中。
# 表格之外的 ID 一律归到 en，宁可猜错也别瞎给。
_WINDOWS_UI_LANG = {
    # 简体 / 繁体 / 香港 / 新加坡 / 澳门
    0x0804: "zh", 0x0404: "zh", 0x0C04: "zh", 0x1004: "zh", 0x1404: "zh",
    # 日语
    0x0411: "ja",
    # 英语（美 / 英 / 澳 / 加 / 新西兰 / 爱尔兰 等）
    0x0409: "en", 0x0809: "en", 0x0C09: "en", 0x1009: "en",
    0x1809: "en", 0x1409: "en", 0x2009: "en", 0x2809: "en",
    0x2409: "en", 0x3009: "en", 0x3409: "en", 0x4009: "en",
    0x4409: "en", 0x4809: "en", 0x4C09: "en", 0x3809: "en",
}


def detect_lang() -> str:
    """按系统界面语言猜一个默认值。

    优先级：Windows API 完整 ID > 环境变量前缀 > CPython locale > en。
    Windows API 优先级最高，是因为 CPython 在没装 locale 数据的 Windows
    上默认会把 zh-CN 兜底成 ja_JP（实测过），完全不可靠。
    """
    # 1. Windows API：拿到完整 16 位 UI Language ID 查表
    try:
        import ctypes
        lang_id = ctypes.windll.kernel32.GetUserDefaultUILanguage()
        if lang_id in _WINDOWS_UI_LANG:
            return _WINDOWS_UI_LANG[lang_id]
    except Exception:
        pass
    # 2. POSIX 环境变量前缀（macOS / Linux 上也能用）
    for var in ("LC_ALL", "LC_MESSAGES", "LANG", "LANGUAGE"):
        val = os.environ.get(var, "")
        if not val:
            continue
        head = val.lower().split("_", 1)[0].split(".", 1)[0]
        if head in LANGS:
            return head
    # 3. CPython locale：仅作为兜底（看前缀，不看整串）
    try:
        head = (locale.getdefaultlocale()[0] or "").lower()[:2]
        if head in LANGS:
            return head
    except Exception:
        pass
    return "en"


def init_lang(explicit: str = "") -> str:
    """启动时定语言：命令行指定 > 上次保存 > 系统猜测。"""
    code = explicit if explicit in LANGS else load_saved_lang()
    set_lang(code)
    return code


set_lang(load_saved_lang())