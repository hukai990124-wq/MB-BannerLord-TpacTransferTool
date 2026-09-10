# -*- coding: utf-8 -*-
"""
migrator_gui.py -- TPAC 批量迁移工具的图形界面（支持中英文切换）。

启动：
    python migrator_gui.py
    python migrator_gui.py --lang en
或双击  启动迁移工具.bat

自检模式（不弹窗，自动跑一遍并退出；中途会切一次语言以验证刷新逻辑）：
    python migrator_gui.py --smoke
"""
from __future__ import annotations

import os
import queue
import shutil
import sys
import tempfile
import threading
import time
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def _safe_print(text: str) -> None:
    """控制台输出：在任何代码页下都不抛异常。

    旧终端（GBK / cp932 等）无法表示部分字符时，直接 print 会抛
    UnicodeEncodeError 并把界面拖崩，所以这里逐级降级到 replace。
    """
    try:
        sys.stdout.write(text + "\n")
        sys.stdout.flush()
        return
    except Exception:
        pass
    try:
        buf = getattr(sys.stdout, "buffer", None)
        if buf is not None:
            buf.write((text + "\n").encode(
                getattr(sys.stdout, "encoding", None) or "utf-8", "replace"))
            buf.flush()
    except Exception:
        pass


import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk

from i18n import LANGS, get_lang, init_lang, save_lang, set_lang, tr
from tpac_core import MappingRule, PackageReport, scan_package
from migrator import (
    MigrateOptions, compute_target_path, discover_tpac, module_root_of,
    rollback, run_batch, suggest_rules,
)

# --------------------------------------------------------------------------
# 主题
# --------------------------------------------------------------------------
BG = "#1e1e1e"
BG_PANEL = "#252526"
BG_INPUT = "#313131"
FG = "#d4d4d4"
FG_DIM = "#8a8a8a"
ACCENT = "#0e639c"
ACCENT_HOVER = "#1177bb"
OK = "#4ec9b0"
WARN = "#dcdcaa"
ERR = "#f14c4c"

FONT = ("Microsoft YaHei UI", 9)
FONT_MONO = ("Consolas", 9)

GAME_DIR_NAME = "Mount & Blade II Bannerlord"

# 语言下拉里显示的是语言本身的名称（中文 / English），不随界面语言变化
LANG_LABELS = ("中文", "English")

CHECKED = "☑"
UNCHECKED = "☐"


def human_size(num: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if abs(num) < 1024.0:
            return "%.0f %s" % (num, unit)
        num /= 1024.0
    return "%.1f TB" % num


def rule_note(note: str) -> str:
    """规则来源文案：存的是 key（可带 |参数），显示时才翻译成当前语言。"""
    if not note:
        return ""
    key, sep, arg = note.partition("|")
    try:
        return tr(key, count=int(arg)) if sep else tr(key)
    except Exception:  # noqa: BLE001
        return note


class App(tk.Tk):
    def __init__(self, smoke: bool = False):
        super().__init__()
        self.smoke = smoke

        self.title(tr("app.title"))
        self.geometry("1180x820")
        self.minsize(1000, 700)
        self.configure(bg=BG)

        self.sources: list = []
        self.reports: dict = {}
        self.rules: list = []
        self.unchecked: set = set()      # 被取消勾选的包路径
        self.msgq: "queue.Queue" = queue.Queue()
        self.busy = False
        self._texts: list = []           # (key, widget) 需要随语言刷新
        self._headings: list = []        # (tree, column, key)

        self._configure_style()
        self._build_ui()
        self._poll()

        if self.smoke:
            self.after(200, self._smoke_test)

    # -- 样式 ------------------------------------------------------------
    def _configure_style(self) -> None:
        style = ttk.Style(self)
        if "clam" in style.theme_names():
            style.theme_use("clam")
        style.configure(".", background=BG, foreground=FG, font=FONT,
                        borderwidth=0)
        style.configure("TFrame", background=BG)
        style.configure("Panel.TFrame", background=BG_PANEL)
        style.configure("TLabel", background=BG, foreground=FG, font=FONT)
        style.configure("Panel.TLabel", background=BG_PANEL, foreground=FG)
        style.configure("Dim.TLabel", background=BG, foreground=FG_DIM, font=FONT)
        style.configure("Header.TLabel", background=BG, foreground=FG,
                        font=("Microsoft YaHei UI", 10, "bold"))
        style.configure("TButton", background=BG_INPUT, foreground=FG,
                        padding=(10, 5), font=FONT, borderwidth=0)
        style.map("TButton",
                  background=[("active", ACCENT_HOVER), ("pressed", ACCENT)],
                  foreground=[("disabled", "#666666")])
        style.configure("Accent.TButton", background=ACCENT, foreground="#ffffff",
                        padding=(14, 6))
        style.map("Accent.TButton", background=[("active", ACCENT_HOVER)])
        style.configure("TCheckbutton", background=BG, foreground=FG, font=FONT)
        style.map("TCheckbutton", background=[("active", BG)])
        style.configure("TRadiobutton", background=BG, foreground=FG, font=FONT)
        style.configure("TEntry", fieldbackground=BG_INPUT, foreground=FG,
                        insertcolor=FG, borderwidth=1, padding=(4, 3))
        style.configure("TCombobox", fieldbackground=BG_INPUT, foreground=FG,
                        padding=(4, 3))
        style.configure("TProgressbar", background=ACCENT, troughcolor=BG_INPUT,
                        borderwidth=0)
        style.configure("TLabelframe", background=BG, foreground=FG)
        style.configure("TLabelframe.Label", background=BG, foreground=FG,
                        font=("Microsoft YaHei UI", 9, "bold"))
        style.configure("Treeview", background=BG_INPUT, foreground=FG,
                        fieldbackground=BG_INPUT, borderwidth=0, rowheight=22)
        style.configure("Treeview.Heading", background=BG_PANEL, foreground=FG,
                        font=("Microsoft YaHei UI", 9, "bold"), borderwidth=0)
        style.map("Treeview", background=[("selected", ACCENT)],
                  foreground=[("selected", "#ffffff")])
        style.map("Treeview.Heading", background=[("active", BG_PANEL)])
        style.configure("Vertical.TScrollbar", background=BG_PANEL,
                        troughcolor=BG, borderwidth=0)
        style.configure("Horizontal.TScrollbar", background=BG_PANEL,
                        troughcolor=BG, borderwidth=0)

    # -- 界面 ------------------------------------------------------------
    def _txt(self, key: str, widget):
        """登记一个文案会随语言变化的控件。"""
        widget.configure(text=tr(key))
        self._texts.append((key, widget))
        return widget

    def _head(self, tree, column: str, key: str) -> None:
        tree.heading(column, text=tr(key))
        self._headings.append((tree, column, key))

    def _build_ui(self) -> None:
        top = ttk.Frame(self, padding=(14, 10, 14, 4))
        top.pack(fill="x")
        self._txt("app.title", ttk.Label(top, style="Header.TLabel")).pack(side="left")
        self._txt("app.subtitle", ttk.Label(top, style="Dim.TLabel")).pack(
            side="left", padx=(12, 0))

        lang_box = ttk.Frame(top)
        lang_box.pack(side="right")
        self._txt("app.lang", ttk.Label(lang_box, style="Dim.TLabel")).pack(side="left")
        self.lang_combo = ttk.Combobox(lang_box, width=9, state="readonly",
                                       values=LANG_LABELS)
        self.lang_combo.set(LANG_LABELS[0] if get_lang() == "zh" else LANG_LABELS[1])
        self.lang_combo.pack(side="left", padx=(4, 0))
        self.lang_combo.bind("<<ComboboxSelected>>", lambda _e: self._on_lang_change())

        # 1. 源与目标
        box = ttk.Frame(self, padding=(14, 4, 14, 4))
        box.pack(fill="x")
        self._txt("sec.sources", ttk.Label(box, style="Header.TLabel")).grid(
            row=0, column=0, sticky="w", pady=(0, 6))

        src_row = ttk.Frame(box)
        src_row.grid(row=1, column=0, sticky="ew")
        self._txt("lbl.sources", ttk.Label(src_row)).pack(side="left")
        self._txt("btn.add_dir",
                  ttk.Button(src_row, command=self._add_dir)).pack(side="left", padx=6)
        self._txt("btn.add_files",
                  ttk.Button(src_row, command=self._add_files)).pack(side="left")
        self._txt("btn.remove",
                  ttk.Button(src_row, command=self._remove_source)).pack(side="left", padx=6)
        self._txt("btn.clear",
                  ttk.Button(src_row, command=self._clear_sources)).pack(side="left")
        self.find_game_btn = self._txt("btn.find_game",
                                       ttk.Button(src_row, command=self._find_game))
        self.find_game_btn.pack(side="left", padx=6)

        self.src_list = tk.Listbox(self, height=4, bg=BG_INPUT, fg=FG,
                                   selectbackground=ACCENT, relief="flat",
                                   highlightthickness=0, font=FONT_MONO)
        self.src_list.pack(fill="x", padx=14, pady=(4, 0))

        dst_row = ttk.Frame(self)
        dst_row.pack(fill="x", padx=14, pady=(8, 0))
        self._txt("lbl.target", ttk.Label(dst_row)).pack(side="left")
        self.target_var = tk.StringVar()
        self.target_entry = ttk.Entry(dst_row, textvariable=self.target_var)
        self.target_entry.pack(side="left", fill="x", expand=True, padx=8)
        self._txt("btn.browse",
                  ttk.Button(dst_row, command=self._browse_target)).pack(side="left")

        mod_row = ttk.Frame(self)
        mod_row.pack(fill="x", padx=14, pady=(6, 0))
        self._txt("lbl.module", ttk.Label(mod_row)).pack(side="left")
        self.module_var = tk.StringVar()
        ttk.Entry(mod_row, textvariable=self.module_var, width=28).pack(side="left", padx=8)
        self._txt("lbl.module_hint", ttk.Label(mod_row, style="Dim.TLabel")).pack(side="left")
        self.target_var.trace_add("write", lambda *_: self._sync_module_name())

        btn_row = ttk.Frame(self)
        btn_row.pack(fill="x", padx=14, pady=(10, 0))
        self.scan_btn = self._txt("btn.scan",
                                  ttk.Button(btn_row, command=self._start_scan,
                                             style="Accent.TButton"))
        self.scan_btn.pack(side="left")
        self._txt("lbl.scan_hint", ttk.Label(btn_row, style="Dim.TLabel")).pack(
            side="left", padx=10)

        # 2. 扫描结果
        self._txt("sec.results", ttk.Label(self, style="Header.TLabel")).pack(
            fill="x", padx=14, pady=(12, 4))
        cols = ("sel", "module", "path", "size", "items", "ext", "types")
        self.tree = ttk.Treeview(self, columns=cols, show="headings", height=9)
        for key, column, width, anchor in (
            ("col.sel", "sel", 34, "center"),
            ("col.module", "module", 150, "w"),
            ("col.path", "path", 430, "w"),
            ("col.size", "size", 78, "e"),
            ("col.items", "items", 56, "center"),
            ("col.ext", "ext", 70, "center"),
            ("col.types", "types", 150, "w"),
        ):
            self._head(self.tree, column, key)
            self.tree.column(column, width=width, anchor=anchor)
        self.tree.pack(fill="both", expand=False, padx=14)
        self.tree.bind("<Button-1>", self._toggle_row)
        self._txt("btn.toggle_all",
                  ttk.Button(self, command=self._toggle_all)).pack(
            anchor="w", padx=14, pady=(4, 0))

        # 3. 规则
        self._txt("sec.rules", ttk.Label(self, style="Header.TLabel")).pack(
            fill="x", padx=14, pady=(12, 4))
        rcols = ("on", "old", "new", "note")
        self.rule_tree = ttk.Treeview(self, columns=rcols, show="headings", height=5)
        for key, column, width in (("col.on", "on", 50),
                                   ("col.old", "old", 430),
                                   ("col.new", "new", 430),
                                   ("col.note", "note", 150)):
            self._head(self.rule_tree, column, key)
            self.rule_tree.column(column, width=width,
                                  anchor="center" if column == "on" else "w")
        self.rule_tree.pack(fill="x", padx=14)
        self.rule_tree.bind("<Double-1>", lambda _e: self._edit_rule())

        rule_btn = ttk.Frame(self)
        rule_btn.pack(fill="x", padx=14, pady=(6, 0))
        self._txt("btn.suggest", ttk.Button(rule_btn, command=self._suggest)).pack(side="left")
        self._txt("btn.add", ttk.Button(rule_btn, command=self._add_rule)).pack(side="left", padx=6)
        self._txt("btn.edit", ttk.Button(rule_btn, command=self._edit_rule)).pack(side="left")
        self._txt("btn.del", ttk.Button(rule_btn, command=self._del_rule)).pack(side="left", padx=6)
        self._txt("lbl.rule_safety", ttk.Label(rule_btn, style="Dim.TLabel")).pack(
            side="left", padx=10)

        # 4. 选项
        self._txt("sec.options", ttk.Label(self, style="Header.TLabel")).pack(
            fill="x", padx=14, pady=(12, 4))
        opt = ttk.Frame(self)
        opt.pack(fill="x", padx=14)
        self.backup_var = tk.BooleanVar(value=True)
        self.relative_var = tk.BooleanVar(value=True)
        self.verify_var = tk.BooleanVar(value=True)
        self.conflict_var = tk.StringVar(value="rename")
        self._txt("chk.backup",
                  ttk.Checkbutton(opt, variable=self.backup_var)).pack(side="left")
        self._txt("chk.relative",
                  ttk.Checkbutton(opt, variable=self.relative_var)).pack(side="left", padx=12)
        self._txt("chk.verify",
                  ttk.Checkbutton(opt, variable=self.verify_var)).pack(side="left")
        self._txt("lbl.conflict", ttk.Label(opt)).pack(side="left", padx=(16, 4))
        ttk.Combobox(opt, textvariable=self.conflict_var, width=10, state="readonly",
                     values=("rename", "overwrite", "skip")).pack(side="left")

        # 5. 执行
        run = ttk.Frame(self)
        run.pack(fill="x", padx=14, pady=(14, 6))
        self.run_btn = self._txt("btn.run",
                                 ttk.Button(run, command=lambda: self._start(False),
                                            style="Accent.TButton"))
        self.run_btn.pack(side="left")
        self._txt("btn.dry", ttk.Button(run, command=lambda: self._start(True))).pack(
            side="left", padx=8)
        self._txt("btn.rollback", ttk.Button(run, command=self._rollback)).pack(side="left")
        self.status_var = tk.StringVar(value=tr("status.ready"))
        ttk.Label(run, textvariable=self.status_var, style="Dim.TLabel").pack(
            side="left", padx=14)
        self.progress = ttk.Progressbar(run, mode="determinate", length=200)
        self.progress.pack(side="right")

        self.log = scrolledtext.ScrolledText(
            self, height=12, bg=BG_INPUT, fg=FG, insertbackground=FG,
            relief="flat", font=FONT_MONO, wrap="word")
        self.log.pack(fill="both", expand=True, padx=14, pady=(0, 14))
        for tag, color in (("ok", OK), ("warn", WARN), ("err", ERR), ("dim", FG_DIM)):
            self.log.tag_configure(tag, foreground=color)

    # -- 语言 ------------------------------------------------------------
    def _on_lang_change(self) -> None:
        label = self.lang_combo.get()
        code = "zh" if label == LANG_LABELS[0] else "en"
        if code == get_lang():
            return
        self._set_lang(code)

    def _set_lang(self, code: str) -> None:
        set_lang(code)
        if not self.smoke:
            save_lang(code)      # 自检只是演练，不该动用户的语言设置
        self._retranslate()
        self._log(tr("log.lang_switched", name=LANG_LABELS[0] if code == "zh"
                     else LANG_LABELS[1]), "ok")

    def _retranslate(self) -> None:
        """切换语言后刷新全部界面文字。"""
        self.title(tr("app.title"))
        for key, widget in self._texts:
            try:
                widget.configure(text=tr(key))
            except tk.TclError:
                pass  # 控件已销毁（比如临时窗口）
        for tree, column, key in self._headings:
            try:
                tree.heading(column, text=tr(key))
            except tk.TclError:
                pass
        self._refresh_tree()
        self._refresh_rules()
        if not self.busy:
            self._status(tr("status.ready"))

    # -- 日志 ------------------------------------------------------------
    def _log(self, msg: str, level: str = "") -> None:
        self.log.insert("end", msg + "\n", level)
        self.log.see("end")
        if self.smoke:
            _safe_print("[%s] %s" % (level or "info", msg))

    def _info(self, title: str, msg: str) -> None:
        """提示信息：自检模式下只写日志，不弹阻塞式对话框。"""
        if self.smoke:
            self._log("%s：%s" % (title, msg), "warn")
            return
        messagebox.showinfo(title, msg)

    def _status(self, text: str) -> None:
        self.status_var.set(text)

    # -- 源列表 ----------------------------------------------------------
    def _add_dir(self) -> None:
        path = filedialog.askdirectory(title=tr("dlg.add_dir"))
        if path:
            self._add_path(path)

    def _add_files(self) -> None:
        paths = filedialog.askopenfilenames(
            title=tr("dlg.add_files"),
            filetypes=[(tr("filetype.tpac"), "*.tpac"),
                       (tr("filetype.all"), "*.*")])
        for path in paths:
            self._add_path(path)

    def _add_path(self, path: str) -> None:
        path = os.path.abspath(path)
        if path not in self.sources:
            self.sources.append(path)
            self.src_list.insert("end", path)

    def _remove_source(self) -> None:
        sel = list(self.src_list.curselection())
        for index in reversed(sel):
            self.src_list.delete(index)
            del self.sources[index]

    def _clear_sources(self) -> None:
        self.src_list.delete(0, "end")
        self.sources.clear()

    def _browse_target(self) -> None:
        path = filedialog.askdirectory(title=tr("dlg.target"))
        if path:
            self.target_var.set(os.path.abspath(path))

    def _sync_module_name(self) -> None:
        path = self.target_var.get().strip()
        if not path:
            return
        root = module_root_of(os.path.join(path, "x"))
        name = os.path.basename(root) if root else os.path.basename(
            path.rstrip("\\/"))
        if name and name.lower() != "modules":
            self.module_var.set(name)

    def _find_game(self) -> None:
        def worker():
            hits = []
            for drive in "CDEFG":
                for rel in ("SteamLibrary/steamapps/common",
                            "Program Files (x86)/Steam/steamapps/common",
                            "Program Files/Steam/steamapps/common",
                            "Steam/steamapps/common"):
                    cand = os.path.join("%s:\\" % drive, rel, GAME_DIR_NAME)
                    if os.path.isdir(cand):
                        hits.append(cand)
            self.msgq.put(("game", hits, None))
        threading.Thread(target=worker, daemon=True).start()
        self._status(tr("status.finding_game"))

    def _pick_module(self, game_dir: str) -> None:
        modules_dir = os.path.join(game_dir, "Modules")
        if not os.path.isdir(modules_dir):
            messagebox.showwarning(tr("dlg.no_modules_title"), tr("dlg.no_modules"))
            return
        win = tk.Toplevel(self)
        win.title(tr("dlg.pick_module"))
        win.configure(bg=BG)
        win.geometry("520x480")
        ttk.Label(win, text=tr("dlg.pick_module_hint"),
                  style="Panel.TLabel").pack(anchor="w", padx=12, pady=8)
        box = tk.Listbox(win, bg=BG_INPUT, fg=FG, relief="flat", font=FONT_MONO)
        box.pack(fill="both", expand=True, padx=12)
        names = sorted(d for d in os.listdir(modules_dir)
                       if os.path.isdir(os.path.join(modules_dir, d)))
        for name in names:
            box.insert("end", name)

        def choose(_e=None):
            sel = box.curselection()
            if not sel:
                return
            self._add_path(os.path.join(modules_dir, names[sel[0]]))
            win.destroy()

        box.bind("<Double-1>", choose)
        ttk.Button(win, text=tr("btn.ok"), command=choose).pack(pady=8)

    # -- 扫描 ------------------------------------------------------------
    def _start_scan(self) -> None:
        if self.busy:
            return
        if not self.sources:
            self._info(tr("dlg.title"), tr("msg.no_source"))
            return
        self.busy = True
        self.scan_btn.configure(state="disabled")
        self.tree.delete(*self.tree.get_children())
        self.reports.clear()
        self.unchecked.clear()
        self._status(tr("status.scanning"))
        files = discover_tpac(self.sources)

        def worker():
            try:
                if not files:
                    self.msgq.put(("log", tr("log.no_tpac"), "warn"))
                    return
                for index, path in enumerate(files):
                    report = scan_package(path)
                    self.reports[path] = report
                    self.msgq.put(("report", report, (index + 1, len(files))))
                self.msgq.put(("scan_done", len(files), None))
            except Exception:  # noqa: BLE001
                self.msgq.put(("traceback", traceback.format_exc(), None))

        threading.Thread(target=worker, daemon=True).start()

    def _toggle_row(self, event) -> None:
        row = self.tree.identify_row(event.y)
        if not row:
            return
        if self.tree.identify_column(event.x) != "#1":
            return
        tags = self.tree.item(row, "tags")
        if not tags:
            return
        path = tags[0]
        now_checked = path not in self.unchecked
        if now_checked:
            self.unchecked.add(path)
        else:
            self.unchecked.discard(path)
        values = list(self.tree.item(row, "values"))
        values[0] = UNCHECKED if now_checked else CHECKED
        self.tree.item(row, values=values)

    def _toggle_all(self) -> None:
        if not self.reports:
            return
        # 有任何一个没勾上，就全勾；否则全不勾
        all_checked = not self.unchecked
        self.unchecked = set(self.reports) if all_checked else set()
        self._refresh_tree()

    def _selected(self) -> list:
        return [p for p in self.reports if p not in self.unchecked]

    # -- 规则 ------------------------------------------------------------
    def _refresh_rules(self) -> None:
        self.rule_tree.delete(*self.rule_tree.get_children())
        for rule in self.rules:
            self.rule_tree.insert("", "end", values=(
                CHECKED if rule.enabled else UNCHECKED,
                rule.old, rule.new, rule_note(rule.note)))

    def _suggest(self) -> None:
        if not self.reports:
            self._info(tr("dlg.title"), tr("msg.need_scan"))
            return
        module = self.module_var.get().strip()
        if not module:
            self._info(tr("dlg.title"), tr("msg.need_module_suggest"))
            return
        found = suggest_rules(list(self.reports.values()), module)
        if not found:
            self._log(tr("log.suggest_none"), "warn")
            return
        existing = {r.old for r in self.rules}
        added = 0
        for rule in found:
            if rule.old not in existing:
                self.rules.append(rule)
                added += 1
        self._refresh_rules()
        self._log(tr("log.suggest_done", total=len(found), added=added), "ok")

    def _add_rule(self) -> None:
        self._rule_dialog(None)

    def _edit_rule(self) -> None:
        sel = self.rule_tree.selection()
        if not sel:
            return
        index = self.rule_tree.index(sel[0])
        self._rule_dialog(index)

    def _del_rule(self) -> None:
        for item in reversed(self.rule_tree.selection()):
            index = self.rule_tree.index(item)
            if 0 <= index < len(self.rules):
                del self.rules[index]
        self._refresh_rules()

    def _rule_dialog(self, index) -> None:
        rule = self.rules[index] if index is not None else MappingRule("", "")
        win = tk.Toplevel(self)
        win.title(tr("dlg.rule_edit") if index is not None else tr("dlg.rule_add"))
        win.configure(bg=BG)
        win.geometry("620x210")
        win.transient(self)
        win.grab_set()

        ttk.Label(win, text=tr("dlg.rule_old"),
                  style="Panel.TLabel").pack(anchor="w", padx=14, pady=(12, 2))
        old_var = tk.StringVar(value=rule.old)
        ttk.Entry(win, textvariable=old_var).pack(fill="x", padx=14)
        ttk.Label(win, text=tr("dlg.rule_new"),
                  style="Panel.TLabel").pack(anchor="w", padx=14, pady=(10, 2))
        new_var = tk.StringVar(value=rule.new)
        ttk.Entry(win, textvariable=new_var).pack(fill="x", padx=14)

        def save():
            old, new = old_var.get(), new_var.get()
            if not old:
                messagebox.showwarning(tr("dlg.title"), tr("warn.empty_old"),
                                       parent=win)
                return
            if index is None:
                self.rules.append(MappingRule(old, new, True, "note.manual"))
            else:
                self.rules[index] = MappingRule(old, new, rule.enabled, rule.note)
            self._refresh_rules()
            win.destroy()

        ttk.Button(win, text=tr("btn.save"), command=save,
                   style="Accent.TButton").pack(pady=14)

    # -- 执行 ------------------------------------------------------------
    def _migrate_options(self) -> MigrateOptions:
        return MigrateOptions(
            target_module=self.module_var.get().strip(),
            on_conflict=self.conflict_var.get(),
            backup=self.backup_var.get(),
            keep_relative=self.relative_var.get(),
            verify=self.verify_var.get(),
        )

    def _start(self, dry_run: bool) -> None:
        if self.busy:
            return
        selected = self._selected()
        if not selected:
            self._info(tr("dlg.title"), tr("msg.need_select"))
            return
        target = self.target_var.get().strip()
        if not target:
            self._info(tr("dlg.title"), tr("msg.need_target"))
            return
        module = self.module_var.get().strip()
        if not module:
            self._info(tr("dlg.title"), tr("msg.need_module"))
            return

        if dry_run:
            self._log(tr("log.dry_header"), "dim")
            for path in selected[:50]:
                dst = compute_target_path(path, target, self.relative_var.get())
                self._log("  %s\n     -> %s" % (os.path.basename(path), dst))
            self._log(tr("log.dry_total", count=len(selected)), "ok")
            return

        self.busy = True
        self.run_btn.configure(state="disabled")
        self.progress["value"] = 0
        rules = [r for r in self.rules]
        options = self._migrate_options()

        def worker():
            try:
                run_batch(selected, target, rules, options,
                          log=lambda m: self.msgq.put(("log", m, "dim")),
                          progress=lambda d, t: self.msgq.put(("progress", (d, t), None)))
                self.msgq.put(("done", None, None))
            except Exception:  # noqa: BLE001
                self.msgq.put(("traceback", traceback.format_exc(), None))
                self.msgq.put(("done", None, None))

        threading.Thread(target=worker, daemon=True).start()
        self._status(tr("status.migrating"))

    def _rollback(self) -> None:
        target = self.target_var.get().strip()
        if not target:
            self._info(tr("dlg.title"), tr("msg.need_target"))
            return
        if self.smoke:
            self._info(tr("dlg.rollback_title"), tr("dlg.rollback_msg"))
            return
        if not messagebox.askyesno(tr("dlg.rollback_title"), tr("dlg.rollback_msg")):
            return
        rollback(target, log=lambda m: self._log(m, "warn"))
        self._log(tr("log.rollback_done"), "ok")

    # -- 消息轮询 --------------------------------------------------------
    def _poll(self) -> None:
        try:
            while True:
                kind, payload, extra = self.msgq.get_nowait()
                if kind == "log":
                    self._log(payload, extra or "")
                elif kind == "report":
                    self._insert_report(payload)
                    if extra:
                        self._status(tr("status.scan_progress", a=extra[0], b=extra[1]))
                elif kind == "scan_done":
                    self._finish_scan(payload)
                elif kind == "done":
                    self.busy = False
                    self.run_btn.configure(state="normal")
                    self._status(tr("status.done"))
                    self._log(tr("log.migrate_done"), "ok")
                elif kind == "progress":
                    done, total = payload
                    self.progress["value"] = (done / total * 100) if total else 0
                elif kind == "game":
                    self._on_game_found(payload)
                elif kind == "traceback":
                    self._log(payload, "err")
                    self.busy = False
                    self.scan_btn.configure(state="normal")
                    self.run_btn.configure(state="normal")
                    self._status(tr("status.error"))
        except queue.Empty:
            pass
        self.after(120, self._poll)

    def _insert_report(self, report: PackageReport) -> None:
        sep = tr("types.sep")
        types = sep.join("%s×%d" % (k, v) for k, v in
                         sorted(report.types.items(), key=lambda kv: -kv[1])[:3])
        if report.error:
            self.tree.insert("", "end", tags=(report.path,),
                             values=(UNCHECKED, "-", report.path, "-", "-", "-",
                                     tr("log.parse_failed", err=report.error)))
            self.unchecked.add(report.path)   # 解析失败的不默认勾选
            return
        self.tree.insert("", "end", tags=(report.path,), values=(
            UNCHECKED if report.path in self.unchecked else CHECKED,
            report.module or "-",
            os.path.relpath(report.path, os.path.dirname(
                module_root_of(report.path) or report.path)),
            human_size(report.size), report.item_count,
            len(report.external_refs), types))

    def _refresh_tree(self) -> None:
        """按当前语言重建扫描结果表，并保留勾选状态。"""
        self.tree.delete(*self.tree.get_children())
        for report in self.reports.values():
            self._insert_report(report)

    def _finish_scan(self, count: int) -> None:
        self.busy = False
        self.scan_btn.configure(state="normal")
        self._status(tr("status.scan_done", count=count))
        self._log(tr("log.scan_done", count=count), "ok")
        externals = sum(len(r.external_refs) for r in self.reports.values())
        if externals:
            self._log(tr("log.externals", count=externals), "warn")
        if self.reports:
            self._suggest()

    def _on_game_found(self, hits) -> None:
        self._status(tr("status.ready"))
        if not hits:
            self._info(tr("dlg.not_found"), tr("dlg.game_not_found"))
            return
        self._pick_module(hits[0])

    # -- 自检 ------------------------------------------------------------
    def _smoke_test(self) -> None:
        """无人值守跑一遍关键路径，用于验证界面没有低级错误。"""
        game = None
        for drive in "CDEFG":
            cand = os.path.join("%s:\\" % drive, "SteamLibrary", "steamapps",
                                "common", GAME_DIR_NAME)
            if os.path.isdir(cand):
                game = cand
                break
        if not game:
            self._log(tr("smoke.not_found"), "warn")
            self.after(300, self.destroy)
            return

        src = os.path.join(game, "Modules", "MercenaryVariety", "Assets", "rome_items")
        # 自检产物落系统临时目录，绝不在程序所在目录（可能是桌面）留垃圾
        out = os.path.join(tempfile.mkdtemp(prefix="tpac_smoke_"),
                           "Modules", "SmokeTarget")
        self._smoke_tmp = os.path.dirname(os.path.dirname(out))
        self._add_path(src)
        self.target_var.set(out)
        self.module_var.set("SmokeTarget")
        self.after(100, self._start_scan)
        # 迁移前先切到另一门语言，顺便验证切换不会打断流程
        self.after(4000, lambda: (
            self._set_lang("en" if get_lang() == "zh" else "zh"),
            self._log(tr("smoke.start"), "dim"),
            self._start(False)))
        self.after(20000, self._smoke_finish)

    def _smoke_finish(self) -> None:
        """自检收尾：清掉临时产物再退出。"""
        tmp = getattr(self, "_smoke_tmp", "")
        if tmp and os.path.isdir(tmp):
            try:
                shutil.rmtree(tmp, ignore_errors=True)
                self._log(tr("smoke.cleanup", path=tmp), "dim")
            except Exception as exc:  # noqa: BLE001
                self._log(tr("smoke.cleanup_fail", err=exc), "warn")
        self.destroy()


def _parse_lang_arg(argv: list) -> str:
    """从命令行里取出 --lang 的值，支持 --lang=en 和 --lang en 两种写法。"""
    for index, arg in enumerate(argv):
        if arg.startswith("--lang="):
            return arg.split("=", 1)[1].strip()
        if arg == "--lang" and index + 1 < len(argv):
            return argv[index + 1].strip()
    return ""


def main() -> int:
    argv = sys.argv[1:]
    smoke = "--smoke" in argv
    init_lang(_parse_lang_arg(argv))

    try:
        app = App(smoke=smoke)
    except tk.TclError as exc:
        _safe_print("无法启动图形界面 / Cannot start GUI: %s" % exc)
        return 1
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
