# Bannerlord TPAC 批量迁移工具

[English](README_EN.md) | **中文**

> **直接下载**：[Bannerlord-Tpac-Migrator.exe](https://github.com/hukai990124-wq/MB-BannerLord-TpacTransferTool/releases/latest/download/Bannerlord-Tpac-Migrator.exe) —— 单文件，双击即用，**不需要安装 Python**。此链接**始终指向最新版本**，版本号与改动见[更新说明](https://github.com/hukai990124-wq/MB-BannerLord-TpacTransferTool/releases)。

把《骑马与砍杀 II：霸主》mod 里的 `.tpac` 资源包批量迁移到另一个 mod，
**同时带上每个包对应的运行时缓存**，并自动重映射包内被锁死的资源路径引用——
解决"搬过去、游戏里却一片空白而且不报错"的问题。

## 它到底解决了什么

搬一件资源到别的 mod，需要搬**两样东西**，少一样都不行：

| 要搬的 | 是什么 | 少搬了会怎样 |
|---|---|---|
| `Assets/<子目录>/*.tpac` | 资源容器：描述网格、材质、贴图，以及打包时写死的源路径 | 游戏里根本找不到这件资源 |
| `RuntimeDataCache/<GUID>.rdc` | 网格与贴图的**真实数据**（tpac 里只有引用，没有像素） | 装备能买到、能装备、日志里也有渲染请求，**但模型一片空白，且一句报错都没有** |

这个工具两样都搬。

### 第一件事：改写被锁死的路径

`.tpac` 是 TaleWorlds 的资源容器。资源在打包时会把源路径写进包里，例如：

```
$BASE/Modules/MercenaryVariety/AssetSources/rome_items/mv_armor_coat.fbx
```

这条路径是**随包一起搬走**的。把 tpac 复制到别的 mod 之后，包内仍然指向原来那个模块，
这就是"换个 mod 包就失效"的根源。

工具会解析容器，把这些引用按规则改写成新模块的路径：

```
$BASE/Modules/MercenaryVariety/  ->  $BASE/Modules/目标模块/
```

同时它会扫描包内资源之间的 **GUID 依赖**（材质 → 纹理、网格 → 材质都是 GUID 引用，不是路径），
报告哪些依赖指向了包外，让你知道迁移后还缺什么。

### 第二件事：跟着搬运行时缓存（RuntimeDataCache）

网格和贴图的真实数据**不在 `.tpac` 里**，而在模块根目录：

```
Modules/<模块名>/RuntimeDataCache/82F204BF-0A6C-4F0E-A023-326A2D9D65B1.rdc
                                  └── 文件名就是 tpac 头部第 8~24 字节的 GUID ──┘
```

工具在迁移每个包时会自动算出这个文件名，从**源模块**的 `RuntimeDataCache/` 里找到它，
复制到**目标模块**的同一位置。文件名不变，内容也**不改写**——`.rdc` 里是纯二进制，
不含任何路径字符串，所以是安全的原样复制。

两条要记住的规律：

- **缓存永远落在目标模块根目录**，不跟随 `Assets/` 的子目录层级。引擎查的就是
  `Modules/<模块名>/RuntimeDataCache/<GUID>.rdc`，把缓存塞进 `Assets/<子目录>/` 里等于没搬。
- **材质包（`*_mtl.tpac`）天生没有缓存**，工具会正常跳过而不报错。实测 MCV 的 62 个包里，
  50 个有缓存、12 个材质包没有，一个不漏。

### 打包文件（`AssetPackages/*.tpac`）是自包含的，不需要缓存

`AssetPackages/`（以及 `EmAssetPackages/`）下的包和 `Assets/` 下的单资源包**不是一回事**：

| | `Assets/<子目录>/xxx.tpac` | `AssetPackages/xxx.tpac` |
|---|---|---|
| 装什么 | **一件**资源（一个网格/材质/贴图） | **一大堆**资源，自带完整数据 |
| 头部 GUID 是什么 | **该资源的 GUID**（= 缓存文件名） | **包格式 GUID**（一个固定值） |
| 要另配 `.rdc` 缓存吗 | 要 | **不要**，数据就在包里 |

打包文件头部那个 GUID 实测是固定的——扫了 244 个打包文件，**243 个都是同一个值**
`807E3D8D-E501-499B-A1D3-22AE3F4E64F3`。旧版本工具把它当成资源 GUID 去
`RuntimeDataCache/` 找缓存，自然一个都找不到，于是把大包全标成红字「缺缓存」——
这是误报。现在工具会认出这类包，缓存列显示**「自包含」**，不标红、也不计入完整性统计。

### 关于 `RuntimeDataCache/` 的真相

它**不是**随 mod 一起发布的东西，而是 Bannerlord 编辑器**在你本机烘焙资源时**生成的副产物。
实测扫遍全库：只有 3 个模块有 `RuntimeDataCache/`（都是自己用编辑器烘过的开发机模块），
官方 **Native / SandBox / NavalDLC 以及所有从网上直接下载的 mod 都没有**。由此：

- 迁移别人的 mod 时源里本来就没有缓存可搬，**这是常态，不是出错**；
- 没有缓存也不必然白模——引擎首次加载会按包内 `metadata` 指向的
  `AssetSources/<...>/xxx.png` **自己烘焙出缓存**，前提是 `AssetSources/` 里确实有源文件。
  只有"既没缓存、源文件也不在"才会真的缺。
- 所以「源里缺缓存」只是**提示**，工具永远不会因为缺缓存而阻止你迁移。

### 不需要搬的东西：AssetSources

`AssetSources/` 是**编辑器用的美术源文件**（fbx、psd 之类），只在 Bannerlord 编辑器里
重新烘焙资源时才用得上。**运行时加载完全不经过它**——游戏读的是上面那个 `.rdc` 缓存。
所以迁移时不必搬，网上直接下载的 mod 包里通常也根本没有这个目录。
只有"以后还要用编辑器改这件资源"时才需要保留它。

### 第三件事：缓存完整性检查（不阻断）

光把缓存搬过去还不够，工具在两个时机再做一次"**该有的都有吗**"的核对，全程**不阻断迁移**：

| 时机 | 核对什么 | 哪里看 |
|---|---|---|
| 扫描结束 | 待迁移包里，**应带缓存**的 N 个中源模块齐全几个 / 缺几个 | 日志 + 扫描表的「缓存」列（缺的那行**标红**） |
| 迁移结束 | 目标模块 `RuntimeDataCache/` 是否把刚搬过去的缓存都就位 | 日志行「目标模块校验：…」 |

判定规则很简单：

- **无需缓存 · 材质包**：只有 `Material` 类型的材质包（文件名 `*_mtl.tpac` 或 `*_material_mtl.tpac` 之类）
- **无需缓存 · 自包含**：`AssetPackages/` / `EmAssetPackages/` 下的打包文件（见上一节），
  或头部 GUID 命中已知包格式 GUID
- **应带**：其余所有单资源包
- **缺失**：本应带缓存，但源模块里也找不到对应 `.rdc` —— 标红警告

> 上面两类"无需缓存"都**不计入**完整性统计的分母，所以大包不会把统计数字污染成一片红。

为什么不阻断？因为实测发现：游戏**首次加载**时，引擎会按包内 `metadata` 指向的源文件
（`AssetSources/<...>/xxx.png` 等）**自己烘焙出缺的缓存**——前提是 `AssetSources/` 里有源文件。
所以"源里缺缓存"并不一定意味着进游戏会白模；只是意味着首次加载要等引擎烘焙。

**示例输出**：

```
Cache audit: 8 expected, source has 7, missing 1; 2 material package(s) need no cache
    0566A1FC-A449-4DAD-9443-1D54BE030C9E.rdc
Target module check: all 7 caches in place
```

**该看哪一行做什么决定**：
- 源里缺但目标里齐（说明游戏已烘焙过）→ 没事，照常用
- 源里缺且目标里也缺 → 第一次进游戏会卡一下让引擎烘焙；过几秒就好
- 迁移后**目标**侧缺（写盘失败 / 磁盘满）→ 这次是真出问题了，看上面的错误日志

## 落点：把包放进哪个子文件夹

做 mod 的人通常会按物品类别把资源分开放（`rome_items` / `levant_items` / `vaegir_items`…），
方便在编辑器里翻找管理。工具**默认就按源分类镜像**，不需要额外操作：

| 源里的位置 | 目标里的位置（默认） |
|---|---|
| `…\Assets\rome_items\a_geo.tpac` | `<目标模块>\Assets\rome_items\a_geo.tpac` |
| `…\Assets\levant_items\b_geo.tpac` | `<目标模块>\Assets\levant_items\b_geo.tpac` |
| `…\AssetPackages\pack0.tpac` | `<目标模块>\AssetPackages\pack0.tpac` |

如果想把**所有**包强制收进同一个子文件夹（比如把散在各处的都归到 `rome_items`），
在界面的「子文件夹」框里填名字即可，命令行用 `--subdir`：

| 你填的 | 实际落点 | 说明 |
|---|---|---|
| `rome_items` | `<目标模块>\Assets\rome_items\` | 自动补上 `Assets\` 前缀 |
| `Assets\rome_items` | `<目标模块>\Assets\rome_items\` | 写全了就不重复加 |
| `rome_items\heavy` | `<目标模块>\Assets\rome_items\heavy\` | 嵌套路径也支持 |
| `AssetPackages` | `<目标模块>\AssetPackages\` | 认作资源根，不再套一层 `Assets\` |
| *（留空）* | 按源分类镜像 | 默认行为 |

填了子文件夹后，它**优先于**「按源分类」勾选——所有包都归到那一个目录下。

### 目标目录选深了也不会出错

引擎只预载 `Assets\` / `AssetPackages\` 下的**第一层**子文件夹，所以再拼一次
`Assets\` 就会得到 `Assets\Assets\rome_items\`，里面的包一个都加载不到。工具会把目标目录
**归一化到模块根**再拼接：你把目标选到 `<模块>\`、`<模块>\Assets\`、
甚至 `<模块>\Assets\rome_items\`，算出来的结果都一样正确。

## 运行环境

- Windows（启动器与图形界面面向 Windows；命令行是纯 Python）。
- Python 3.8+，实测于 3.11。
- **图形界面要求 Python 自带 `tkinter`**（python.org 官方安装包自带；部分精简版/嵌入式版本
  以及 Microsoft Store 版本没有）。
- **不需要任何第三方库**：LZ4 block 解码是纯 Python 实现。若环境里恰好装了 `lz4`，
  重新压缩时会用它，装了更快、没装也完全正常。

## 使用方法

### 图形界面（推荐）

双击 **`启动迁移工具.bat`**，或命令行执行 `python migrator_gui.py`。

1. **源与目标**：添加要迁移的 mod 目录（或单个 `.tpac` 文件），再选目标模块目录。
   点「查找游戏目录…」可以直接从 `Modules` 里挑一个模块。
   - 目标模块名会自动从**文件夹名**推断，它决定替换成什么样的路径。

> ⚠️ **动手前请确认一件事：目标模块的文件夹名，必须等于它 `SubModule.xml` 里的 `<Id>`。**
> 包内写死的 `$BASE/Modules/〈名字〉/AssetSources/…` 只能对上其中一个，两者不一致时必然有一边
> 解析不到。症状非常隐蔽：**装备在游戏里能买到、能装备，引擎日志里也有渲染请求，但模型一片
> 空白，而且没有任何报错**。工具检测到不一致时会红字告警，并在开始迁移前弹窗确认。
> 修法：把文件夹改名成与 `<Id>` 相同（启动器按 Id 记录勾选状态，改名不会丢）。
2. **扫描源**：列出所有 tpac、条目数、内容构成、包外依赖数量，以及**「缓存」列**。
   默认全选，点首列可勾选。
   - 「缓存」列显示 `✓ 6.0 MB` 表示源模块 `RuntimeDataCache/` 里有对应的 `.rdc`，
     迁移时会一起带走；显示 `—` 表示源模块里没有（**材质包本来就没有，属正常**）。
3. **路径重映射规则**：扫描完成后会**依据包内真实出现的路径**自动建议规则（不是猜的）。
   可以手工增删改。
4. **选项**：建议保持「覆盖前备份」和「写盘后结构自检」开启。
5. **开始迁移**：先用「预演（只看不改）」确认目标路径和缓存落点，再正式执行。
   迁移日志里会逐条报告缓存去向，最后给一条汇总，例如：

   ```
   运行时缓存：新增 32，覆盖 0，已存在 0，按策略跳过 0，源内无缓存 8（材质包通常如此），失败 0
   ```

出问题时用「回滚上次迁移」撤销——它会删除本次写入的文件（**含缓存**），还原被覆盖前的备份。

### 命令行

```bat
python migrator.py --source "E:\...\Modules\MercenaryVariety\Assets" ^
                   --target "E:\...\Modules\MyMod" --to MyMod
```

常用参数：`--from <源模块名>`、`--rule "旧串=新串"`、`--on-conflict rename|overwrite|skip`、
`--dry-run`、`--no-backup`、`--subdir rome_items`（把所有包归进 `Assets/rome_items/`，
**优先于** `--keep-relative`）、`--flat`（拍平到模块根，不保留分类）、
`--deep-scan`（深度扫描 segment，**默认关闭**，见下文"大包为什么不再爆内存"）、
`--rollback`（撤销上次迁移）、`--lang zh|en|ja`。

> 落点**默认按源分类镜像**（和界面一致）：源里 `Assets/rome_items/a.tpac` 就落到目标
> `Assets/rome_items/a.tpac`。`--keep-relative` 现在只是兼容旧命令的写法，写了也不报错。
> 想拍平就用 `--flat`。

`--dry-run` 会先打印落点规则，再把每个包的 tpac 落点**和缓存落点**都列出来，输出形如：

```
  落点：按源分类镜像 —— 源里的 Assets/rome_items/ 会落到目标 Assets/rome_items/
  ...\vaegir_items\vaegir_lord_helm_geo.tpac -> ...\Modules\MyMod\Assets\vaegir_items\vaegir_lord_helm_geo.tpac
      缓存 0566A1FC-A449-4DAD-9443-1D54BE030C9E.rdc  ->  ...\Modules\MyMod\RuntimeDataCache\0566A1FC-....rdc
  ...\AssetPackages\pack0.tpac -> ...\Modules\MyMod\AssetPackages\pack0.tpac
      缓存：不需要（AssetPackages 打包文件自带全部数据）
```

缓存不受 `--flat` / `--keep-relative` / `--subdir` 影响，**永远落在目标模块根目录下**；
打包文件（`AssetPackages/*.tpac`）则本来就**没有**缓存要搬。

### 界面语言

右上角可切换 **中文 / English / 日本語**，选择会存进 `ui_config.json`，下次启动自动沿用。

切换范围覆盖三层，不只是按钮文字：

- 界面控件、表头、弹窗
- 迁移过程日志与警告
- 解析 / 重建的报错信息

命令行可单独指定：`python migrator_gui.py --lang en`、`python migrator.py --lang ja`。
首次运行没有记录时，按 Windows 界面语言自动选（中文系统默认中文）。

## 改写的安全策略

tpac 是二进制容器，乱改长度会直接损坏文件。工具按保守程度分三档处理：

| 情况 | 做法 |
|---|---|
| 新旧字符串**等长** | 直接字节替换，不改变任何结构长度，零风险 |
| 字符串**带 i32 长度前缀**（tpac 的通用写法） | 同步改写长度前缀，结构自洽，支持变长 |
| 既不等长、又找不到长度前缀 | **跳过并明确报告**，绝不硬改 |

因为整个容器是按条目重新生成的，改长改短都会自动重算 TOC 与数据区偏移。

未改写的资源段会**连压缩字节一起原样搬运**，不做多余的解压/重压，
改动面被压到最小，上百 MB 的包也能处理（分段流式读写，不会把整个文件读进内存）。

### 大包（几百 MB ~ 几 GB）为什么不再爆内存

曾经有个坑：迁移 2.8 GB 的 `core_game.tpac` 时，进程峰值内存会飙到 **4.6 GB**。

实测下来是**两个互相独立的原因**，只修一个都不够：

1. **写盘后的结构自检**：它逐个段解压、核对"解压长度对不对"，而取数据用的 `get_data()`
   会把解压结果**永久缓存**在段对象里——于是 23109 个段一起留在内存，等于把整个包解压后揣着不放。
2. **段扫描（深度扫描）**：为了"万一路径藏在资源段里"，它会把每个 ≤4 MB 的段解压一遍，
   同样驻留内存。

同一台机器、同一个文件的四组对照（改写数始终是 2010，说明修内存没有改变行为）：

| 配置 | 峰值内存 | 耗时 |
|---|---|---|
| 段扫描**开** + 旧自检 | 4467 MB | — |
| 段扫描**关** + 旧自检 | 4609 MB | 212 s |
| 段扫描**开** + 新自检 | 4483 MB | 447 s |
| **段扫描关 + 新自检（默认设置）** | **150 MB** | 239 s |

看第 2、3 行就知道：**两个都得修**。修完后峰值只跟**单个最大段**有关、与包的段数无关，
所以多大的包都吃得下。

那为什么可以放心把**段扫描默认关掉**？因为实测扫与不扫，**改写结果完全一致（都是 2010 处）**
——所有路径字符串本来就在 `metadata` 里，扫段一处都没多找到。关掉它既省 4.3 GB 内存、
也省 200 多秒。万一遇到结构特殊的包，可在界面勾「深度扫描段」（命令行 `--deep-scan`）兜底。

`core_game.tpac` 本身实测能正常迁完：5045 个条目、2010 处路径改写、产物重新解析条目数一致。

`.rdc` 缓存则完全不解析、不改写，直接按字节复制。

### 缓存冲突怎么处理

缓存文件名就是引擎的查找键，所以**不能改名**（改成 `<GUID>_1.rdc` 等于没搬）。工具的处理是：

| 目标模块里已有同名缓存 | 做法 |
|---|---|
| 内容完全相同 | 跳过，不重复拷几十 MB |
| 内容不同 | 备份后覆盖（`--on-conflict skip` 时改为保留原有文件） |

## 已验证

格式实现与迁移链路都经过真实文件校验，不是纸上推演：

- **字节级 round-trip**：解析 26 个真实 tpac（含 137 MB 的包）后原样重建，
  与原始文件**逐字节完全一致**。这证明容器布局的理解没有偏差。
- **迁移端到端**：真实迁移 40 个资源包，40/40 成功，产物可重新解析、条目数一致、
  段数据可正常解压，路径已改写为目标模块；同时 **32 个缓存随包复制、8 个材质包正确识别为无缓存、0 失败**。
- **缓存专项回归**（`tests/test_cache.py`）：文件名推导（.NET GUID 字节序 + 大小写 + 扩展名）、
  源模块内定位、目标落点固定在模块根、真实模块命中规律、端到端搬运与重复迁移去重。
- **缓存完整性回归**（`tests/test_audit.py`）：`cache_audit` 的基础判定、目标侧校验、
  `run_batch` 的"同时构建校验"路径、`needs_runtime_cache` 的四类判定。
- **落点专项回归**（`tests/test_paths.py`）：源分类镜像、子目录强制落点（裸名 / 带 `Assets\` 前缀 /
  `AssetPackages` / 嵌套路径）、留空不改变默认行为、目标目录选深到 `Assets\` 或更深时的归一化
  （确认**不会**拼出 `Assets\Assets\`）——7 组新用例，全部通过。
- **大包实测**：2.8 GB 的 `AssetPackages/core_game.tpac`（23109 段、5045 条目）迁移成功，
  2010 处路径改写；**峰值内存 4.6 GB → 150 MB**（段扫描与写盘自检两处都修之后，四组对照见上文）。
  另有 130 MB 的 `gauntlet_ui.tpac`、62 MB 的 `pack0.tpac` 等一并验过。
- **自检流式行为回归**（`tests/test_verify.py`）：合成包 + 真实包双路验证——段数统计正确、
  段长不符会带资源名报错、且**校验结束后没有任何段残留解压数据**（内存恒定的结构性保证）。
- **打包文件识别**：扫遍 244 个 `AssetPackages/*.tpac`，**243 个头部 GUID 是同一个固定值**，
  据此确认"把包格式 GUID 当资源 GUID 找缓存"是误报根源，现已改为识别为「自包含」。
- **i18n 自检**（`tests/test_i18n.py`）：191 条文案 × 3 语言（中/英/日）键与占位符一一对应，
  语言探测 8 组用例全部通过。
- **回滚**：撤销一次 18 个文件的迁移（10 个 tpac + 8 个缓存），全部清理干净。

## 目录结构

```
霸主tpac迁移工具/
  tpac_core.py       容器读写 / LZ4 / 依赖图 / 重映射引擎 / 缓存文件名推导 / 打包文件识别 / 流式自检
  migrator.py        迁移执行层（发现、规则建议、冲突、备份、缓存搬运、落点、回滚、命令行）
  migrator_gui.py    图形界面（中英日切换）
  i18n.py            中英日文案表（界面 / 日志 / 报错，共 191 条）
  启动迁移工具.bat    一键启动
  ui_config.json     记住的语言选择（首次运行后生成）
  README.md / README_EN.md / README_JA.md   中 / 英 / 日三语说明
  tests/
    test_roundtrip.py  字节级 round-trip 校验
    test_remap.py      真实文件迁移端到端校验
    test_paths.py      模块根定位 / 目标路径 / 子目录落点 / 文件夹名与 Id 一致性
    test_cache.py      运行时缓存定位与搬运校验
    test_audit.py      缓存完整性审计（含打包文件排除）
    test_verify.py     写盘后自检的流式行为（不许把所有段留在内存里）
    test_i18n.py       语言表自检（缺译 / 占位符不一致）
```

跑校验：

```bat
python tests\test_i18n.py
python tests\test_paths.py
python tests\test_cache.py
python tests\test_audit.py
python tests\test_verify.py
python tests\test_roundtrip.py
python tests\test_remap.py
```

> `test_roundtrip.py`、`test_remap.py`、`test_cache.py` 的"真实模块"部分需要本机装有游戏
> （默认路径 `E:\SteamLibrary\steamapps\common\Mount & Blade II Bannerlord`），
> 路径不同请改脚本里的常量。没有装游戏时，纯合成数据的断言仍会跑完。

### 打包成独立 EXE

装好 PyInstaller 后：

```bat
pyinstaller --noconfirm --onefile --windowed --name 霸主tpac迁移工具 migrator_gui.py
```

`--windowed` 避免弹出控制台黑框。界面里的中文由 tkinter 原生渲染（UTF-8），
不受控制台代码页影响。

## 注意

- 工具只做两件事：改 tpac 内部的路径引用、搬对应的 `.rdc` 缓存。
  **XML 里对资源的引用**（`ModuleData` 下的物品、兵种等）不在 tpac 内，需要你自己同步改名，
  或让目标模块沿用原资源名。
- 如果扫描报告出现「包外依赖 GUID」，说明这些资源引用了本包之外的东西。
  目标环境必须同样能解析到它们，否则模型仍然显示不出来——这类依赖通常是材质/纹理
  留在了源 mod 或原版里，需要一并迁移。
- 迁移只会写目标目录，**不会改动源 mod**。但第一次批量操作前，仍然建议先备份目标模块。
- 目标模块里如果已经存在同名缓存且内容不同，会被备份后覆盖。
- 建议先拿几个不重要的包试一次，进游戏确认无误再批量跑。

## 格式依据

容器格式参考 TpacTool（szszss / hunharibo，MIT）的逆向结果，并在真实资源包上完成校验：

```
文件头 36B: magic "TPAC" | version | package guid | 条目数 | 数据区偏移 | 保留
条目:      type guid | item guid | version | 名称(长度前缀) | metadata 长度 | metadata
           | 校验和 | 段数 | 段[] | 依赖数 | 依赖[]
段:        偏移 | 原始大小 | 存储大小 | owner guid | type guid | 未知×2 | 存储格式
存储格式:  0 = 原始, 1 = LZ4-HC
```

其中头部的 **package guid**（偏移 8~24）同时决定运行时缓存的文件名：
按 .NET Guid 文本格式（前三段小端）大写输出，加 `.rdc` 扩展名。

> **注意一个例外**：这个字段在**单资源包**（`Assets/<子目录>/xxx.tpac`）里确实是资源 GUID，
> 但在**打包文件**（`AssetPackages/xxx.tpac`）里是**包格式 GUID**（实测 244 个里 243 个都是
> `807E3D8D-E501-499B-A1D3-22AE3F4E64F3`）。打包文件自包含、本来就没有对应缓存，所以不能用它
> 去 `RuntimeDataCache/` 找 `.rdc`——工具靠这个特征识别「自包含」包。

工具自带纯 Python 的 LZ4 block 解码，无需安装任何第三方库；
若环境里装了 `lz4`，重新压缩时会用它，装了更快、没装也能正常工作。
