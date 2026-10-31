# MB-BannerLord-TpacTransferTool

**English** | [中文](README.md)

> **Download:** [Bannerlord-Tpac-Migrator.exe](https://github.com/hukai990124-wq/MB-BannerLord-TpacTransferTool/releases/latest/download/Bannerlord-Tpac-Migrator.exe) — a single file, double-click to run, **no Python installation required**. This link **always points at the newest release**; see the [changelog](https://github.com/hukai990124-wq/MB-BannerLord-TpacTransferTool/releases) for the current version and what changed.

Batch-migrate `.tpac` asset packages from one *Mount & Blade II: Bannerlord* mod to another,
**bringing each package's runtime cache along**, and automatically **re-mapping the hard-coded
asset paths locked inside the packages** — so moved meshes and textures are found by the game
instead of silently failing to load.

## The problem it solves

Moving an asset to another mod means moving **two things**. Miss either one and it breaks:

| What to move | What it is | What happens if you skip it |
|---|---|---|
| `Assets/<subfolder>/*.tpac` | The asset container: describes meshes, materials, textures — plus the source paths baked in at pack time | The game cannot find the asset at all |
| `RuntimeDataCache/<GUID>.rdc` | The **actual data** for meshes and textures (the tpac holds only references, no pixels) | The item can be bought and equipped, the log even shows a render request, **but the model is blank — and nothing is reported as an error** |

This tool moves both.

### Part one: rewriting the locked-in paths

`.tpac` is TaleWorlds' asset container format. When assets are packed, the source path is baked
into the package, for example:

```
$BASE/Modules/MercenaryVariety/AssetSources/rome_items/mv_armor_coat.fbx
```

That path **travels with the package**. Copy a `.tpac` into a different mod and it still points at
the original module — which is exactly why "just move the file" breaks the model.

The tool parses the container and rewrites those references to the new module's path:

```
$BASE/Modules/MercenaryVariety/  ->  $BASE/Modules/<target module>/
```

It also scans the **GUID dependencies** between assets inside the package (material → texture and
mesh → material are GUID references, not paths) and reports which ones point outside the package,
so you know what else must come along.

### Part two: bringing the runtime cache (RuntimeDataCache)

The real mesh and texture data is **not inside the `.tpac`** — it lives at the module root:

```
Modules/<module>/RuntimeDataCache/82F204BF-0A6C-4F0E-A023-326A2D9D65B1.rdc
                                 └─ the file name is the GUID at header bytes 8–24 ─┘
```

For every package it migrates, the tool derives that name, finds the file in the **source**
module's `RuntimeDataCache/` and copies it to the same place in the **target** module. The name
does not change and the contents are **not rewritten** — a `.rdc` is pure binary with no path
strings in it, so a straight copy is safe.

Two rules worth remembering:

- **The cache always lands at the target module root**, never mirroring the `Assets/` subtree.
  The engine looks up `Modules/<module>/RuntimeDataCache/<GUID>.rdc`, so tucking the cache into
  `Assets/<subfolder>/` is the same as not moving it.
- **Material packages (`*_mtl.tpac`) never have a cache**, and the tool skips them without
  complaining. Of the 62 packages in MCV, 50 have a cache and 12 materials do not — no exceptions.

### Bundled packages (`AssetPackages/*.tpac`) are self-contained

Packages under `AssetPackages/` (and `EmAssetPackages/`) are **not the same thing** as the
single-asset packages under `Assets/`:

| | `Assets/<subfolder>/xxx.tpac` | `AssetPackages/xxx.tpac` |
|---|---|---|
| Holds | **one** asset (a mesh / material / texture) | **many** assets, with the data inside |
| Header GUID is | **that asset's GUID** (= the cache file name) | a **format GUID** (one fixed value) |
| Needs a separate `.rdc` cache | yes | **no** — the data is in the package |

The header GUID of a bundled package is in fact constant — across 244 bundled packages scanned,
**243 share the same value** `807E3D8D-E501-499B-A1D3-22AE3F4E64F3`. Older builds treated it as an
asset GUID, went looking for a cache in `RuntimeDataCache/`, found nothing, and flagged every large
package red as "cache missing" — a false alarm. The tool now recognises these packages: the Cache
column shows **"self-contained"**, no red, and they are excluded from the completeness statistics.

### The truth about `RuntimeDataCache/`

It is **not** something shipped with a mod — it is a by-product the Bannerlord editor generates
**when you bake assets on your own machine**. Scanning an entire install: only 3 modules had a
`RuntimeDataCache/` (all of them development machines where the editor had been used); the official
**Native / SandBox / NavalDLC modules and every mod downloaded from the internet have none**.
Consequently:

- When migrating someone else's mod there is simply no cache to bring — **that is normal, not a failure**;
- A missing cache does not have to mean a blank model — on first load the engine **bakes it itself**
  from the `AssetSources/<...>/xxx.png` pointer in the package `metadata`, *provided those source
  files exist*. Only "no cache **and** no source files" is genuinely broken.
- So "cache missing in the source" is only a **hint**; the tool never blocks a migration over it.

### What you do *not* need to move: AssetSources

`AssetSources/` holds the **artist source files** (fbx, psd, …) used by the Bannerlord editor when
re-baking an asset. **Runtime loading never touches it** — the game reads the `.rdc` cache above.
So you do not need to migrate it, and mods downloaded from the internet usually do not ship it at
all. Keep it only if you intend to re-edit that asset in the editor later.

### Part three: a cache-completeness check (non-blocking)

Moving the cache is not the whole story — the tool runs a **"is everything that should be there actually there?"** check at two points, and **never blocks the migration**:

| When | What it checks | Where to look |
|---|---|---|
| After scan | Of the N packages that should bring a cache, how many does the source module have / how many are missing | The log + the **Cache** column in the scan table (missing rows are **highlighted red**) |
| After migrate | Did the target module's `RuntimeDataCache/` actually end up with everything we just copied? | The `Target module check: …` log line |

The rule is simple:

- **No cache needed — material** — material packages (only `Material` type)
- **No cache needed — self-contained** — bundled files under `AssetPackages/` /
  `EmAssetPackages/` (see the previous section), or any header GUID matching a known format GUID
- **Should have a cache** — all remaining single-asset packages
- **Missing** — should have a cache but the source module has no matching `.rdc` — flagged red

> Both "no cache needed" categories are **excluded from the denominator** of the completeness
> statistics, so large packages no longer paint the numbers red.

Why not block? Because empirically, on first load the engine **re-bakes** a missing cache itself, by
reading the `metadata` pointer inside the package back to the source file in `AssetSources/<...>/xxx.png`
— *provided that AssetSources is present*. So a missing source-side cache does not necessarily mean a
white model in game; it just means the first load will pause for a moment while the engine bakes it.

**Sample output**:

```
Cache audit: 8 expected, source has 7, missing 1; 2 material package(s) need no cache
    0566A1FC-A449-4DAD-9443-1D54BE030C9E.rdc
Target module check: all 7 caches in place
```

**How to read it**:

- Source missing but target present (engine already baked it earlier) → nothing to worry about
- Source missing *and* target missing → first in-game load will pause a few seconds for the engine to bake it
- **Target** side missing after migration (write failed / disk full) → real problem; check the error log above

## Destinations: which subfolder does a package land in?

Modders usually group assets by category (`rome_items` / `levant_items` / `vaegir_items` …) to keep
things manageable in the editor. The tool **mirrors the source layout by default**, so nothing extra
is required:

| Source location | Destination (default) |
|---|---|
| `…\Assets\rome_items\a_geo.tpac` | `<target module>\Assets\rome_items\a_geo.tpac` |
| `…\Assets\levant_items\b_geo.tpac` | `<target module>\Assets\levant_items\b_geo.tpac` |
| `…\AssetPackages\pack0.tpac` | `<target module>\AssetPackages\pack0.tpac` |

To force **every** package into one subfolder instead (say, gathering scattered packages into
`rome_items`), type the name into the **Subfolder** box in the GUI, or use `--subdir` on the CLI:

| You type | Actual destination | Notes |
|---|---|---|
| `rome_items` | `<target module>\Assets\rome_items\` | `Assets\` is added automatically |
| `Assets\rome_items` | `<target module>\Assets\rome_items\` | Fully qualified — no extra prefix |
| `rome_items\heavy` | `<target module>\Assets\rome_items\heavy\` | Nested paths work too |
| `AssetPackages` | `<target module>\AssetPackages\` | Recognised as a resource root, no extra `Assets\` |
| *(empty)* | mirror the source | the default |

When a subfolder is given it **takes precedence** over the *mirror the source* checkbox — all
packages go into that one directory.

### Choosing a target directory "too deep" is still safe

The engine only preloads the **first-level** subfolders of `Assets\` / `AssetPackages\`, so appending
another `Assets\` would produce `Assets\Assets\rome_items\` and none of those packages would load.
The tool **normalises the target to the module root** before joining: whether you pick `<module>\`,
`<module>\Assets\` or even `<module>\Assets\rome_items\`, the result is the same and correct.

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
   - **Subfolder left empty** (recommended) = mirror the source, so `Assets/rome_items/` in the
     source lands in `Assets/rome_items/` in the target. **Fill it in** (e.g. `rome_items`) to force
     every package into `Assets/rome_items/` — handy for organising things in the editor.

> ⚠️ **One thing to check before you start: the target module's folder name must equal the `<Id>`
> declared in its `SubModule.xml`.** The `$BASE/Modules/〈name〉/AssetSources/…` strings baked into
> the packages can only match one of them, so a mismatch guarantees that one side fails to resolve.
> The symptom is deceptive: **the item can be bought and equipped in game, the engine log even shows
> a render request, yet the model is blank — and nothing is reported as an error.** The tool flags
> the mismatch in red and asks for confirmation before migrating. Fix: rename the folder to match the
> `<Id>` (the launcher records selection by Id, so nothing is lost).
2. **Scan** — lists every `.tpac`, its item count, content breakdown, number of external
   dependencies, and a **Cache** column. All rows are selected by default; use the first column to
   toggle.
   - The **Cache** column has **four** states:
     - `✓ 6.0 MB` — the source module's `RuntimeDataCache/` holds the matching `.rdc`; it is moved along
     - `— material` — material packages never have one; normal
     - `— self-contained` — an `AssetPackages/` bundle whose data is inside the package; no cache needed
     - `missing` (**whole row red**) — it should have one but none was found; a hint only, it
       **does not block** the migration
3. **Path re-mapping rules** — after scanning, rules are **suggested from the paths that actually
   occur inside the packages** (not guessed). You can add, edit or delete them by hand.
4. **Options** — it is recommended to keep *back up before overwrite* and *verify structure after
   writing* enabled.
5. **Start migration** — use *Dry run (preview only)* to confirm destination paths and cache
   locations first, then run it for real. The log reports each cache file as it goes and ends with a
   summary line, e.g.:

   ```
   RuntimeDataCache: 32 added, 0 overwritten, 0 already present, 0 skipped by policy, 8 absent in source (usual for material packages), 0 failed
   ```

If something goes wrong, use *Roll back last migration*: it deletes the files this run wrote
(**including caches**) and restores the pre-overwrite backups.

### Command line

```bat
python migrator.py --source "E:\...\Modules\MercenaryVariety\Assets" ^
                   --target "E:\...\Modules\MyMod" --to MyMod
```

Common flags: `--from <source module name>`, `--rule "old=new"`,
`--on-conflict rename|overwrite|skip`, `--dry-run`, `--no-backup`,
`--subdir rome_items` (put every package under `Assets/rome_items/`; **overrides**
`--keep-relative`), `--flat` (drop files into the module root, no categories),
`--deep-scan` (scan segments deeply; **off by default** — see "Why large packages no longer
exhaust memory" below), `--rollback` (undo the last migration), `--lang zh|en|ja`.

> Destinations **mirror the source by default** (same as the GUI): `Assets/rome_items/a.tpac` in the
> source lands at `Assets/rome_items/a.tpac` in the target. `--keep-relative` is now only a
> compatibility spelling and is accepted without error. Use `--flat` to flatten.

`--dry-run` first prints the layout rule, then both the `.tpac` and the cache destination for each
package:

```
  Layout: mirror the source — Assets/rome_items/ lands at the target's Assets/rome_items/
  ...\vaegir_items\vaegir_lord_helm_geo.tpac -> ...\Modules\MyMod\Assets\vaegir_items\vaegir_lord_helm_geo.tpac
      cache 0566A1FC-A449-4DAD-9443-1D54BE030C9E.rdc  ->  ...\Modules\MyMod\RuntimeDataCache\0566A1FC-....rdc
  ...\AssetPackages\pack0.tpac -> ...\Modules\MyMod\AssetPackages\pack0.tpac
      cache: not needed (self-contained AssetPackages bundle)
```

The cache is unaffected by `--flat` / `--keep-relative` / `--subdir`; it **always lands at the
target module root**. Bundled packages (`AssetPackages/*.tpac`) simply have **no** cache to move.

### Interface language

The UI has a **中文 / English / 日本語** switcher in the top-right corner; the choice is saved to
`ui_config.json` and reused on the next launch.

Translation covers three layers, not just button captions:

- UI widgets, table headers and dialogs
- Migration log lines and warnings
- Parse / rebuild error messages

The CLI can override it per run: `python migrator_gui.py --lang en`,
`python migrator.py --lang ja`. With no saved preference, the language is inferred from the
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

### Why large packages (hundreds of MB to several GB) no longer exhaust memory

There used to be a trap: migrating the 2.8 GB `core_game.tpac` drove the process peak working set to
**4.6 GB**.

Measurement showed **two independent causes** — fixing only one of them is not enough:

1. **The post-write structural self-check** decompresses every segment to verify the decompressed
   length, and the accessor `get_data()` **caches the decompressed bytes permanently** on the
   segment object — so all 23,109 segments stayed in memory at once, effectively holding the whole
   unpacked package.
2. **Segment scanning (deep scan)** — the "just in case the paths are hidden in a resource segment"
   precaution — decompresses every segment ≤4 MB and keeps those resident too.

Four runs on the same machine and the same file (rewrites were 2010 every time, so none of this
changed behaviour):

| Configuration | Peak memory | Time |
|---|---|---|
| Segment scan **on** + old self-check | 4467 MB | — |
| Segment scan **off** + old self-check | 4609 MB | 212 s |
| Segment scan **on** + new self-check | 4483 MB | 447 s |
| **Segment scan off + new self-check (defaults)** | **150 MB** | 239 s |

Rows 2 and 3 make the point: **both had to be fixed.** The peak now depends only on the **single
largest segment**, not on the number of segments — so any package size fits.

That is also why **segment scanning can safely be off by default**: measured on the same package,
scanning and not scanning gave **identical results (2010 rewrites either way)** — all path strings
live in `metadata`, so the segment scan found nothing extra. Turning it off saves 4.3 GB of memory
and 200-odd seconds. If you ever hit a structurally unusual package, tick *deep-scan segments* in the
GUI (CLI `--deep-scan`) as a fallback.

That 2.8 GB `AssetPackages/core_game.tpac` migrates fine: 5045 items, 2010 path rewrites, about
235 seconds, and the output re-parses with an identical item count.

`.rdc` caches are never parsed or rewritten at all — they are copied byte for byte.

### How cache conflicts are handled

The cache file name *is* the engine's lookup key, so it must **not** be renamed (a `<GUID>_1.rdc`
would be the same as not moving it). The tool therefore behaves like this:

| A same-name cache already exists in the target | What it does |
|---|---|
| Identical contents | Skips it — no pointless copy of tens of MB |
| Different contents | Backs it up and overwrites (`--on-conflict skip` keeps the existing file instead) |

## Verification

Both the format implementation and the migration pipeline are validated against real files:

- **Byte-level round-trip** — 26 real `.tpac` packages (including a 137 MB one) were parsed and
  rebuilt unchanged, **byte-for-byte identical** to the originals. This proves the container layout
  is understood correctly.
- **End-to-end migration** — 40 real packages migrated, 40/40 successful; the outputs re-parse,
  keep the same item count, their segments still decompress, and the paths are rewritten to the
  target module. In the same run **32 caches were copied along, 8 material packages were correctly
  recognised as having none, 0 failures**.
- **Cache-specific regression** (`tests/test_cache.py`) — file-name derivation (.NET GUID byte
  order, casing, extension), lookup inside the source module, destination pinned to the module
  root, hit pattern across a real module, end-to-end copy plus de-duplication on re-runs.
- **Cache-completeness regression** (`tests/test_audit.py`) — the base `cache_audit` decision, the
  target-side check, the `run_batch` "build the audit alongside" path, and the four
  `needs_runtime_cache` verdicts.
- **Destination regression** (`tests/test_paths.py`) — mirroring, forced subfolder destinations (bare
  name / `Assets\`-prefixed / `AssetPackages` / nested), empty input not changing the default, and
  normalisation when the target is picked as deep as `Assets\` (confirming **no** `Assets\Assets\`
  is ever produced). 7 new cases, all passing.
- **Large-package measurement** — the 2.8 GB `AssetPackages/core_game.tpac` (23,109 segments,
  5045 items) migrates successfully with 2010 rewrites; **peak memory went from 4.6 GB to 150 MB**
  (after fixing *both* the segment scan and the post-write self-check — see the four-run matrix
  above). Also verified on a 130 MB `gauntlet_ui.tpac` and a 62 MB `pack0.tpac`.
- **Streaming self-check regression** (`tests/test_verify.py`) — synthetic and real packages both:
  the segment count is right, a wrong segment length is reported with the asset name, and
  **no segment data is left behind after verification** (the structural guarantee behind flat memory).
- **Bundled-package recognition** — across 244 scanned `AssetPackages/*.tpac`, **243 share the same
  fixed header GUID**, confirming that treating a format GUID as an asset GUID was the source of the
  false "missing cache" reports. These are now recognised as *self-contained*.
- **i18n self-check** (`tests/test_i18n.py`) — 191 messages × 3 languages (zh/en/ja) with matching
  keys and placeholders, plus 8 language-detection cases.
- **Rollback** — a migration of 18 files (10 `.tpac` + 8 caches) was reverted completely.

## Project layout

```
霸主tpac迁移工具/
  tpac_core.py       container read/write, LZ4, dependency graph, re-mapping engine, cache-name derivation, bundled-package detection, streaming verify
  migrator.py        migration layer (discovery, rule suggestions, conflicts, backup, cache copying, destinations, rollback, CLI)
  migrator_gui.py    graphical interface (zh/en/ja switch)
  i18n.py            zh/en/ja message table (UI / log / errors, 191 entries)
  启动迁移工具.bat    one-click launcher
  ui_config.json     remembered language choice (created on first run)
  README.md / README_EN.md / README_JA.md   Chinese / English / Japanese docs
  tests/
    test_roundtrip.py  byte-level round-trip check
    test_remap.py      end-to-end migration check on real files
    test_paths.py      module root / target path / subfolder destination / folder-name-vs-Id consistency
    test_cache.py      runtime cache lookup and copying
    test_audit.py      cache-completeness audit (bundled packages excluded)
    test_verify.py     streaming behaviour of the post-write self-check (no segment data may be retained)
    test_i18n.py       message-table check (missing translations / placeholder mismatch)
```

Run the checks yourself:

```bat
python tests\test_i18n.py
python tests\test_paths.py
python tests\test_cache.py
python tests\test_audit.py
python tests\test_verify.py
python tests\test_roundtrip.py
python tests\test_remap.py
```

> The "real module" sections of `test_roundtrip.py`, `test_remap.py` and `test_cache.py` expect a
> local Bannerlord installation (`E:\SteamLibrary\steamapps\common\Mount & Blade II Bannerlord` by
> default); adjust the path in the script if yours differs. Without the game installed, the
> synthetic-data assertions still run.

### Building a standalone EXE

With PyInstaller installed:

```bat
pyinstaller --noconfirm --onefile --windowed --name 霸主tpac迁移工具 migrator_gui.py
```

`--windowed` keeps the console window from appearing. The GUI renders Chinese natively through
tkinter (UTF-8), so it is unaffected by the console code page.

## Caveats

- The tool does exactly two things: rewrite the path references inside `.tpac` files, and copy the
  matching `.rdc` caches. References to assets from **XML files** (items, troops, etc. under
  `ModuleData`) are outside the package and must be renamed by you — or the target module must keep
  the original asset names.
- If the scan reports *external dependency GUIDs*, those assets reference something outside this
  package. The target environment must be able to resolve them too, otherwise the model still will
  not show up — such dependencies (usually materials/textures left in the source mod or in Native)
  have to be migrated as well.
- Migration only writes to the **destination** directory and **never modifies the source mod**.
  Even so, back up the target module before your first batch run.
- If the target module already holds a same-name cache with different contents, it is backed up and
  overwritten.
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

The **package guid** in the header (bytes 8–24) also determines the runtime cache file name: it is
rendered in .NET Guid text form (first three groups little-endian), uppercased, with a `.rdc`
extension.

> **One exception**: in a **single-asset package** (`Assets/<subfolder>/xxx.tpac`) this field really
> is the asset GUID, but in a **bundled file** (`AssetPackages/xxx.tpac`) it is a **package format
> GUID** (measured: 243 out of 244 share `807E3D8D-E501-499B-A1D3-22AE3F4E64F3`). Bundled files are
> self-contained and have no corresponding cache, so this field must not be used to look one up in
> `RuntimeDataCache/` — which is exactly the trait the tool uses to recognise them.

The tool ships a pure-Python LZ4 block decoder, so no third-party library is needed; if `lz4` is
installed it is used when re-compressing — faster with it, fully functional without it.

## Credits

- Container format reverse engineering: [TpacTool](https://github.com/hunharibo/TpacTool) by
  szszss / hunharibo (MIT).
- Built for the *Mount & Blade II: Bannerlord* modding community.
