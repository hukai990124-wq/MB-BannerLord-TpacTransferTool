# MB-BannerLord-TpacTransferTool

**English** | [中文](README.md)

Batch-migrate `.tpac` asset packages from one *Mount & Blade II: Bannerlord* mod to another,
automatically **re-mapping the hard-coded asset paths locked inside the packages** — so moved
meshes and textures are still found by the game instead of silently failing to load.

## The problem it solves

`.tpac` is TaleWorlds' asset container format. When assets are packed, the source path is baked
into the package, for example:

```
$BASE/Modules/MercenaryVariety/AssetSources/rome_items/mv_armor_coat.fbx
```

That path **travels with the package**. Copy a `.tpac` into a different mod and it still points at
the original module — which is exactly why "just move the file" breaks the model.

This tool parses the container and rewrites those references to the new module's path:

```
$BASE/Modules/MercenaryVariety/  ->  $BASE/Modules/<target module>/
```

It also scans the **GUID dependencies** between assets inside the package (material → texture and
mesh → material are GUID references, not paths) and reports which ones point outside the package,
so you know what else must come along.

## Requirements

- Windows (the launcher script and the GUI are Windows-oriented; the CLI is plain Python).
- Python 3.8+ — tested on 3.11.
- The **GUI requires a Python build that includes `tkinter`** (the official python.org builds do;
  some minimal/embedded builds and the Microsoft Store build do not).
- **No third-party packages are required.** The LZ4 block codec is implemented in pure Python.
  If `lz4` happens to be installed, it is used for faster re-compression, but it is optional.

## Getting started

### Option A — prebuilt executable

Run the bundled `霸主tpac迁移工具.exe` (Bannerlord tpac Migration Tool) — no Python required.
Double-click it and the GUI opens.

### Option B — from source

```bat
:: GUI (recommended)
启动迁移工具.bat
:: -- or --
python migrator_gui.py

:: Command line
python migrator.py --source "E:\...\Modules\MercenaryVariety\Assets" ^
                   --target "E:\...\Modules\MyMod" --to MyMod
```

## Usage

### GUI (recommended)

1. **Source & target** — add the mod directory (or individual `.tpac` files) to migrate, then pick
   the target module directory. *Find game directory…* lets you pick a module straight from
   `Modules\`.
   - The target module name is inferred from the directory name; it determines what the paths are
     rewritten to.
2. **Scan** — lists every `.tpac`, its item count, content breakdown and number of external
   dependencies. All rows are selected by default; use the first column to toggle.
3. **Path re-mapping rules** — after scanning, rules are **suggested from the paths that actually
   occur inside the packages** (not guessed). You can add, edit or delete them by hand.
4. **Options** — it is recommended to keep *back up before overwrite* and *verify structure after
   writing* enabled.
5. **Start migration** — use *Dry run (preview only)* to confirm the destination paths first, then
   run it for real.

If something goes wrong, use *Roll back last migration*: it deletes the files this run wrote and
restores the pre-overwrite backups.

### Command line

```bat
python migrator.py --source "E:\...\Modules\MercenaryVariety\Assets" ^
                   --target "E:\...\Modules\MyMod" --to MyMod
```

Common flags: `--from <source module name>`, `--rule "old=new"`,
`--on-conflict rename|overwrite|skip`, `--dry-run`, `--no-backup`,
`--flat` (do not preserve relative directories), `--rollback` (undo the last migration),
`--lang zh|en`.

### Interface language

The UI has a **中文 / English** switcher in the top-right corner; the choice is saved to
`ui_config.json` and reused on the next launch.

Translation covers three layers, not just button captions:

- UI widgets, table headers and dialogs
- Migration log lines and warnings
- Parse / rebuild error messages

The CLI can override it per run: `python migrator_gui.py --lang en`,
`python migrator.py --lang en`. With no saved preference, the language is inferred from the
Windows UI language.

## How rewriting stays safe

A `.tpac` is a binary container — changing a length carelessly corrupts the file. The tool handles
three cases, from most to least conservative:

| Case | What it does |
|---|---|
| Old and new strings are **the same length** | Plain byte replacement, no structural length change, zero risk |
| The string has an **i32 length prefix** (the usual tpac layout) | The length prefix is rewritten too, so the structure stays self-consistent and variable-length replacement works |
| Neither equal-length **nor** length-prefixed | **Skipped and reported explicitly** — never force-written |

Because the whole container is regenerated item by item, any change in length automatically
recomputes the TOC and data-region offsets.

Asset segments that are not rewritten are **copied verbatim together with their compressed bytes** —
no needless decompress/recompress — keeping the change surface minimal. Packages hundreds of MB in
size are fine: reading and writing are chunked and streaming, so the whole file is never loaded
into memory.

## Verification

The format implementation is validated against real files, not just theory:

- **Byte-level round-trip** — 23 real `.tpac` packages (including a 137 MB one) were parsed and
  rebuilt unchanged, **byte-for-byte identical** to the originals. This proves the container layout
  is understood correctly.
- **End-to-end migration** — 40 real packages migrated, 40/40 successful; the outputs re-parse,
  keep the same item count, their segments still decompress, and the paths are rewritten to the
  target module.
- **Rollback** — all 40 written files were reverted cleanly.

Run the checks yourself:

```bat
python tests\test_i18n.py
python tests\test_roundtrip.py
python tests\test_remap.py
```

> `test_roundtrip.py` and `test_remap.py` expect a local Bannerlord installation
> (`E:\SteamLibrary\steamapps\common\Mount & Blade II Bannerlord` by default); adjust the path in
> the script if yours differs.

## Project layout

```
霸主tpac迁移工具/
  tpac_core.py       container read/write, LZ4, dependency graph, re-mapping engine
  migrator.py        migration layer (discovery, rule suggestions, conflicts, backup, rollback, CLI)
  migrator_gui.py    graphical interface (zh/en switch)
  i18n.py            zh/en message table (UI / log / errors)
  启动迁移工具.bat    one-click launcher
  ui_config.json     remembered language choice (created on first run)
  tests/
    test_roundtrip.py  byte-level round-trip check
    test_remap.py      end-to-end migration check on real files
    test_i18n.py       message-table check (missing translations / placeholder mismatch)
```

### Building a standalone EXE

With PyInstaller installed:

```bat
pyinstaller --noconfirm --onefile --windowed --name 霸主tpac迁移工具 migrator_gui.py
```

`--windowed` keeps the console window from appearing. The GUI renders Chinese natively through
tkinter (UTF-8), so it is unaffected by the console code page.

## Caveats

- The tool only rewrites path references **inside `.tpac` files**. References to assets from
  **XML files** (items, troops, etc. under `ModuleData`) are outside the package and must be renamed
  by you — or the target module must keep the original asset names.
- If the scan reports *external dependency GUIDs*, those assets reference something outside this
  package. The target environment must be able to resolve them too, otherwise the model still will
  not show up — such dependencies (usually materials/textures left in the source mod or in Native)
  have to be migrated as well.
- Migration only writes to the **destination** directory and **never modifies the source mod**.
  Even so, back up the target module before your first batch run.
- Try a few unimportant packages first and confirm in-game before running the whole batch.

## Format reference

The container format follows the reverse-engineering work of
[TpacTool](https://github.com/hunharibo/TpacTool) (szszss / hunharibo, MIT), validated against real
asset packages:

```
Header, 36 B: magic "TPAC" | version | package guid | item count | data offset | reserved
Item:         type guid | item guid | version | name (length-prefixed)
              | metadata length | metadata | checksum | segment count | segments[]
              | dependency count | dependencies[]
Segment:      offset | actual size | storage size | owner guid | type guid | unknown ×2 | storage format
Storage format:  0 = raw, 1 = LZ4-HC
```

The tool ships a pure-Python LZ4 block decoder, so no third-party library is needed; if `lz4` is
installed it is used when re-compressing — faster with it, fully functional without it.

## Credits

- Container format reverse engineering: [TpacTool](https://github.com/hunharibo/TpacTool) by
  szszss / hunharibo (MIT).
- Built for the *Mount & Blade II: Bannerlord* modding community.
