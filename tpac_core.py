# -*- coding: utf-8 -*-
"""
tpac_core.py -- Mount & Blade II: Bannerlord (.tpac) 容器读写与迁移引擎。

容器格式（依据 TpacTool, MIT, szszss/hunharibo 的逆向结果，并已用真实
Bannerlord 资源包做过字节级 round-trip 校验）：

    文件头  36 字节
        0   u32  magic  0x43415054 ("TPAC", 小端)
        4   u32  version 1 (1.0.0~1.4.2) / 2 (1.4.3+)
        8   16   package guid
        24  u32  item 数量
        28  u32  data 区偏移 = TOC 字节数（不含 36 字节头）
        32  u32  保留 (0)
    TOC   item 数量 × 条目
        16      type guid
        16      item guid
        u32     asset version        (仅 version >= 2)
        sized   name                 (i32 长度 + UTF8 字节)
        u64     metadata 长度
        ...     metadata
        i64     未知校验和（原样保留）
        i32     segment 数量
        segment[]  offset u64 / actual u64 / storage u64 / owner 16 / type 16
                   / unknown u64 / unknown u32 / storage_format u8
        i32     dependence 数量
        dep[]   3 × 16 guid
    数据区 各 segment 的 storage 字节（offset 为绝对文件偏移）

storage_format: 0 = 原始, 1 = LZ4-HC（标准 LZ4 block，无 frame 头）。

设计要点：
  * 惰性读取：TOC 常驻内存，segment 数据按需从源文件读取，GB 级包也不会爆内存。
  * 写回时未修改的 segment 以分块拷贝方式原样搬运（连压缩字节一起），
    只有真正改写的 segment 才解压 -> 改写 -> 重新存储，把改动面压到最小。
  * 依赖是 GUID 引用，不是路径。迁移的核心是保证依赖闭包完整，
    本模块在 metadata 中搜索已知 GUID 字节串来还原依赖图，
    无需逐个解析每种资源的 metadata 结构。
"""

from __future__ import annotations

import io
import os
import re
import struct
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

from i18n import tr

MAGIC = 0x43415054
HEADER_SIZE = 36

STORAGE_RAW = 0
STORAGE_LZ4HC = 1

COPY_CHUNK = 8 << 20  # 分块拷贝大小

# TpacTool.Lib 中已知的资源类型 guid -> 名称
KNOWN_TYPE_GUIDS: Dict[str, str] = {
    "a08f8b97-197c-4bea-b95b-53846cae834e": "Metamesh",
    "1db01393-6902-4f19-83ba-b37a39830717": "Material",
    "c635a3d5-eabb-45dd-883e-aa57e4196113": "Skeleton",
    "5fce4668-0596-c44b-8db2-1edaa9408411": "Geometry",
}

# 常见段类型 guid -> 名称（用于报告可读性）
KNOWN_SEGMENT_GUIDS: Dict[str, str] = {
    "8ab981a7-6ba0-4908-9606-91ad341d19a9": "TextureSourceInfo",
    "11d07d37-e720-406b-ab67-c846f96a8771": "SkeletonDefinition",
    "9b6ac06d-a546-40af-a555-40d301ab4b2f": "SkeletonUserData",
}

ZERO_GUID = b"\x00" * 16


class TpacError(Exception):
    """tpac 解析 / 重建错误。"""


# --------------------------------------------------------------------------
# LZ4 block（纯 Python 实现，避免额外依赖）
# --------------------------------------------------------------------------

def lz4_block_decompress(src: bytes, dst_len: int) -> bytes:
    """解压 LZ4 raw block。与 lz4net 的 LZ4Codec.Decode(src, 0, len, dst_len) 等价。"""
    dst = bytearray()
    pos = 0
    n = len(src)
    if dst_len <= 0:
        return b""
    while pos < n:
        token = src[pos]
        pos += 1

        lit = token >> 4
        if lit == 15:
            while True:
                b = src[pos]
                pos += 1
                lit += b
                if b != 255:
                    break
        if lit:
            dst += src[pos:pos + lit]
            pos += lit

        # 最后一个序列允许只含字面量
        if pos >= n:
            break

        offset = src[pos] | (src[pos + 1] << 8)
        pos += 2
        if offset == 0:
            raise TpacError(tr("err.lz4_offset0"))

        mlen = (token & 0x0F)
        if mlen == 15:
            while True:
                b = src[pos]
                pos += 1
                mlen += b
                if b != 255:
                    break
        mlen += 4

        start = len(dst) - offset
        if start < 0:
            raise TpacError(tr("err.lz4_offset_oob"))
        if start + mlen <= len(dst):
            dst += dst[start:start + mlen]
        else:  # 重叠匹配需逐字节复制
            for i in range(mlen):
                dst.append(dst[start + i])

    if len(dst) != dst_len:
        raise TpacError(
            tr("err.lz4_len", a=dst_len, b=len(dst))
        )
    return bytes(dst)


def lz4_block_store(src: bytes) -> bytes:
    """把数据包装成合法的 LZ4 block（纯字面量，无压缩）。无 lz4 库时的回退。"""
    if not src:
        return b""
    out = bytearray()
    pos = 0
    total = len(src)
    while pos < total:
        chunk_len = min(total - pos, 0xFFFF)
        out.append(0xF0)  # literal 长度走扩展字节，match_len = 0
        remain = chunk_len - 15
        while remain >= 255:
            out.append(255)
            remain -= 255
        out.append(remain)
        out += src[pos:pos + chunk_len]
        pos += chunk_len
    return bytes(out)


def lz4_block_compress(data: bytes) -> Optional[bytes]:
    """压缩为 LZ4-HC block。优先使用 lz4 扩展库，不可用时回退到纯字面量包装。"""
    try:
        import lz4.block  # type: ignore
        return lz4.block.compress(
            data, mode="high_compression", compression=9, store_size=False
        )
    except Exception:
        return lz4_block_store(data)


# --------------------------------------------------------------------------
# 数据源（惰性读取）
# --------------------------------------------------------------------------

class Source:
    """按 (offset, size) 惰性读取字节。"""

    def read_at(self, offset: int, size: int) -> bytes:
        raise NotImplementedError

    def copy_to(self, offset: int, size: int, out) -> None:
        raise NotImplementedError

    def close(self) -> None:
        pass


class FileSource(Source):
    def __init__(self, path: str):
        self.path = path
        self._fh = None

    def _handle(self):
        if self._fh is None:
            self._fh = open(self.path, "rb")
        return self._fh

    def read_at(self, offset: int, size: int) -> bytes:
        fh = self._handle()
        fh.seek(offset)
        return fh.read(size)

    def copy_to(self, offset: int, size: int, out) -> None:
        fh = self._handle()
        fh.seek(offset)
        left = size
        while left > 0:
            chunk = fh.read(min(COPY_CHUNK, left))
            if not chunk:
                raise TpacError(tr("err.src_truncated", path=self.path))
            out.write(chunk)
            left -= len(chunk)

    def close(self) -> None:
        if self._fh is not None:
            self._fh.close()
            self._fh = None


class MemorySource(Source):
    def __init__(self, data: bytes):
        self.data = data

    def read_at(self, offset: int, size: int) -> bytes:
        return self.data[offset:offset + size]

    def copy_to(self, offset: int, size: int, out) -> None:
        out.write(self.data[offset:offset + size])


# --------------------------------------------------------------------------
# 数据结构
# --------------------------------------------------------------------------

def guid_str(raw: bytes) -> str:
    """按 .NET Guid 的字节布局转成规范字符串，仅用于展示。"""
    if len(raw) != 16:
        return raw.hex()
    a, b, c = struct.unpack_from("<IHH", raw, 0)
    d = raw[8:]
    return "%08x-%04x-%04x-%s-%s" % (a, b, c, d[:2].hex(), d[2:].hex())


@dataclass
class Segment:
    offset: int = 0
    actual_size: int = 0
    storage_size: int = 0
    owner_guid: bytes = ZERO_GUID
    type_guid: bytes = ZERO_GUID
    unknown_ulong: int = 0
    unknown_uint: int = 0
    storage_format: int = STORAGE_RAW

    # 惰性来源
    source: Optional[Source] = None
    src_offset: int = 0
    # 已改写时驻留内存
    _storage: Optional[bytes] = None
    _data: Optional[bytes] = None

    def __post_init__(self):
        if self.owner_guid is None:
            self.owner_guid = ZERO_GUID
        if self.type_guid is None:
            self.type_guid = ZERO_GUID

    @property
    def dirty(self) -> bool:
        return self._storage is not None

    @property
    def type_name(self) -> str:
        return KNOWN_SEGMENT_GUIDS.get(guid_str(self.type_guid), "")

    def get_storage(self) -> bytes:
        """取得文件中存放的字节（可能已压缩）。"""
        if self._storage is not None:
            return self._storage
        if self.source is None:
            return b""
        return self.source.read_at(self.src_offset, self.storage_size)

    def get_data(self) -> bytes:
        """取得解压后的原始字节。"""
        if self._data is not None:
            return self._data
        storage = self.get_storage()
        if self.storage_format == STORAGE_LZ4HC:
            data = lz4_block_decompress(storage, self.actual_size)
        else:
            data = storage
        self._data = data
        return data

    def set_data(self, data: bytes, keep_compressed: bool = True) -> None:
        self._data = data
        self.actual_size = len(data)
        if keep_compressed and len(data) >= 16:
            compressed = lz4_block_compress(data)
            if compressed and len(compressed) < len(data):
                self._storage = compressed
                self.storage_size = len(compressed)
                self.storage_format = STORAGE_LZ4HC
                return
        self._storage = data
        self.storage_size = len(data)
        self.storage_format = STORAGE_RAW

    def size(self) -> int:
        return self.storage_size


@dataclass
class AssetItem:
    type_guid: bytes = ZERO_GUID
    guid: bytes = ZERO_GUID
    version: int = 0
    name: str = ""
    metadata: bytes = b""
    checksum: int = 0
    segments: List[Segment] = field(default_factory=list)
    deps: List[Tuple[bytes, bytes, bytes]] = field(default_factory=list)

    # 运行期派生
    refs: Set[bytes] = field(default_factory=set)        # 引用的同包 GUID
    external_refs: Set[bytes] = field(default_factory=set)  # 包外 GUID
    source_package: str = ""

    @property
    def type_name(self) -> str:
        return KNOWN_TYPE_GUIDS.get(guid_str(self.type_guid), guid_str(self.type_guid))

    @property
    def guid_text(self) -> str:
        return guid_str(self.guid)

    def requires(self) -> Set[bytes]:
        """本 item 依赖的 GUID（含包内与包外）。"""
        out = set(self.refs) | set(self.external_refs)
        for g1, g2, g3 in self.deps:
            out.update((g1, g2, g3))
        return {g for g in out if g != ZERO_GUID}


@dataclass
class TpacPackage:
    version: int = 2
    guid: bytes = ZERO_GUID
    items: List[AssetItem] = field(default_factory=list)
    data_offset: int = 0
    toc_end: int = 0
    source_path: str = ""

    @property
    def name_index(self) -> Dict[str, AssetItem]:
        return {it.name: it for it in self.items}

    @property
    def guid_index(self) -> Dict[bytes, AssetItem]:
        return {it.guid: it for it in self.items}

    def close(self) -> None:
        seen = set()
        for item in self.items:
            for seg in item.segments:
                if seg.source is not None and id(seg.source) not in seen:
                    seen.add(id(seg.source))
                    seg.source.close()


# --------------------------------------------------------------------------
# 读取
# --------------------------------------------------------------------------

def _read_sized_string(blob: bytes, pos: int) -> Tuple[str, int]:
    if pos + 4 > len(blob):
        raise TpacError(tr("err.str_oob", pos=pos))
    (length,) = struct.unpack_from("<i", blob, pos)
    pos += 4
    if length == 0:
        return "", pos
    if length < 0 or pos + length > len(blob):
        raise TpacError(tr("err.str_len", length=length, pos=pos))
    return blob[pos:pos + length].decode("utf-8", errors="replace"), pos + length


def parse_header(data: bytes) -> Tuple[int, bytes, int, int]:
    if len(data) < HEADER_SIZE:
        raise TpacError(tr("err.file_small"))
    magic, version = struct.unpack_from("<II", data, 0)
    if magic != MAGIC:
        raise TpacError(tr("err.magic", magic=magic))
    if version not in (1, 2):
        raise TpacError(tr("err.version", version=version))
    count, data_offset = struct.unpack_from("<II", data, 24)
    return version, data[8:24], count, data_offset


class _StreamReader:
    """对文件 / 内存做严格的顺序读取，读完正好停在 TOC 末尾。

    之所以不按文件头里的 data_offset 切出 TOC：实测部分资源包该字段与
    真实 TOC 长度不一致（照它切片会截断条目），顺序解析才可靠。
    """

    def __init__(self, fh):
        self.fh = fh
        self.consumed = 0

    def take(self, n: int) -> bytes:
        data = self.fh.read(n)
        if data is None:
            data = b""
        if len(data) != n:
            raise TpacError(tr("err.toc_trunc", pos=self.consumed,
                               need=n, got=len(data)))
        self.consumed += n
        return data

    def u32(self) -> int:
        return struct.unpack("<I", self.take(4))[0]

    def i32(self) -> int:
        return struct.unpack("<i", self.take(4))[0]

    def u64(self) -> int:
        return struct.unpack("<Q", self.take(8))[0]

    def i64(self) -> int:
        return struct.unpack("<q", self.take(8))[0]

    def guid(self) -> bytes:
        return self.take(16)

    def string(self) -> str:
        length = self.i32()
        if length == 0:
            return ""
        if length < 0 or length > (1 << 24):
            raise TpacError(tr("err.str_len", length=length, pos=self.consumed))
        return self.take(length).decode("utf-8", errors="replace")


def _parse_items(reader: _StreamReader, version: int, count: int, source: Source,
                 file_size: int, source_path: str) -> List[AssetItem]:
    items: List[AssetItem] = []
    for _ in range(count):
        item = AssetItem(source_package=source_path)
        item.type_guid = reader.guid()
        item.guid = reader.guid()
        if version > 1:
            item.version = reader.u32()
        item.name = reader.string()

        meta_len = reader.u64()
        if meta_len > (1 << 31):
            raise TpacError(tr("err.meta_len", length=meta_len))
        item.metadata = reader.take(meta_len)
        item.checksum = reader.i64()

        seg_count = reader.i32()
        if not 0 <= seg_count < (1 << 20):
            raise TpacError(tr("err.seg_count", count=seg_count))
        for _ in range(seg_count):
            seg = Segment(source=source)
            seg.offset = reader.u64()
            seg.actual_size = reader.u64()
            seg.storage_size = reader.u64()
            seg.owner_guid = reader.guid()
            seg.type_guid = reader.guid()
            seg.unknown_ulong = reader.u64()
            seg.unknown_uint = reader.u32()
            seg.storage_format = reader.take(1)[0]
            seg.src_offset = seg.offset
            if seg.offset + seg.storage_size > file_size:
                raise TpacError(tr("err.seg_oob", offset=seg.offset,
                                   size=seg.storage_size, total=file_size))
            item.segments.append(seg)

        dep_count = reader.i32()
        if not 0 <= dep_count < (1 << 20):
            raise TpacError(tr("err.dep_count", count=dep_count))
        for _ in range(dep_count):
            item.deps.append((reader.guid(), reader.guid(), reader.guid()))

        items.append(item)
    return items


def load_tpac(path: str) -> TpacPackage:
    """惰性加载：TOC 顺序解析，segment 数据按需读取。"""
    file_size = os.path.getsize(path)
    src = FileSource(path)
    try:
        fh = src._handle()
        fh.seek(0)
        version, pkg_guid, count, data_offset = parse_header(fh.read(HEADER_SIZE))
        reader = _StreamReader(fh)
        items = _parse_items(reader, version, count, src, file_size, path)
    except Exception:
        src.close()
        raise

    pkg = TpacPackage(version=version, guid=pkg_guid, items=items, source_path=path)
    pkg.data_offset = data_offset
    pkg.toc_end = HEADER_SIZE + reader.consumed
    return pkg


def parse_tpac(data: bytes, source_path: str = "") -> TpacPackage:
    """从内存字节解析（小文件 / 测试用）。"""
    version, pkg_guid, count, data_offset = parse_header(data)
    src = MemorySource(data)
    reader = _StreamReader(io.BytesIO(data))
    reader.take(HEADER_SIZE)
    pkg = TpacPackage(version=version, guid=pkg_guid, source_path=source_path)
    pkg.items = _parse_items(reader, version, count, src, len(data), source_path)
    pkg.data_offset = data_offset
    pkg.toc_end = HEADER_SIZE + reader.consumed
    return pkg


# --------------------------------------------------------------------------
# 写回
# --------------------------------------------------------------------------

def _write_sized_string(out: bytearray, value: str) -> None:
    raw = value.encode("utf-8")
    out += struct.pack("<i", len(raw))
    out += raw


def build_toc(pkg: TpacPackage, version: int) -> Tuple[bytearray, List[Tuple[int, Segment]]]:
    """生成 TOC 字节（segment 偏移先置 0）与需要回填的位置列表。"""
    toc = bytearray()
    patches: List[Tuple[int, Segment]] = []
    for item in pkg.items:
        toc += item.type_guid
        toc += item.guid
        if version > 1:
            toc += struct.pack("<I", item.version)
        _write_sized_string(toc, item.name)
        toc += struct.pack("<Q", len(item.metadata))
        toc += item.metadata
        toc += struct.pack("<q", item.checksum)
        toc += struct.pack("<i", len(item.segments))
        for seg in item.segments:
            patches.append((len(toc), seg))
            toc += struct.pack("<QQQ", 0, seg.actual_size, seg.storage_size)
            toc += seg.owner_guid
            toc += seg.type_guid
            toc += struct.pack("<QI", seg.unknown_ulong, seg.unknown_uint)
            toc += bytes([seg.storage_format])
        toc += struct.pack("<i", len(item.deps))
        for g1, g2, g3 in item.deps:
            toc += g1 + g2 + g3
    return toc, patches


def build_tpac(pkg: TpacPackage, version: Optional[int] = None) -> bytes:
    """在内存中重建完整 tpac（适合小文件与测试）。"""
    version = pkg.version if version is None else version
    toc, patches = build_toc(pkg, version)
    cursor = HEADER_SIZE + len(toc)
    for pos, seg in patches:
        struct.pack_into("<Q", toc, pos, cursor)
        cursor += seg.storage_size

    out = bytearray()
    out += struct.pack("<II", MAGIC, version)
    out += pkg.guid
    out += struct.pack("<II", len(pkg.items), len(toc))
    out += struct.pack("<I", 0)
    out += toc
    for _pos, seg in patches:
        out += seg.get_storage()
    return bytes(out)


def save_tpac(pkg: TpacPackage, path: str, version: Optional[int] = None,
              progress=None) -> None:
    """流式写出 tpac：未改写的 segment 直接从源分块拷贝，内存占用恒定。

    progress(done, total) 可选，用于界面进度条。
    """
    version = pkg.version if version is None else version
    toc, patches = build_toc(pkg, version)
    total_bytes = sum(seg.storage_size for _pos, seg in patches)

    cursor = HEADER_SIZE + len(toc)
    for pos, seg in patches:
        struct.pack_into("<Q", toc, pos, cursor)
        cursor += seg.storage_size

    directory = os.path.dirname(os.path.abspath(path))
    if directory:
        os.makedirs(directory, exist_ok=True)

    tmp_path = path + ".tmp"
    with open(tmp_path, "wb") as out:
        out.write(struct.pack("<II", MAGIC, version))
        out.write(pkg.guid)
        out.write(struct.pack("<II", len(pkg.items), len(toc)))
        out.write(struct.pack("<I", 0))
        out.write(toc)
        done = 0
        for _pos, seg in patches:
            if seg.dirty:
                out.write(seg.get_storage())
                done += seg.storage_size
            elif seg.source is not None:
                seg.source.copy_to(seg.src_offset, seg.storage_size, out)
                done += seg.storage_size
            else:
                out.write(seg.get_storage())
                done += seg.storage_size
            if progress:
                progress(done, total_bytes)

    if os.path.exists(path):
        os.replace(tmp_path, path)
    else:
        os.rename(tmp_path, path)


# --------------------------------------------------------------------------
# 依赖图
# --------------------------------------------------------------------------

def build_dependency_graph(pkg: TpacPackage) -> None:
    """在 metadata / dependence 表中搜索已知 GUID 字节串，还原依赖图。

    不解析每种资源的具体 metadata 结构，只做 16 字节串匹配。GUID 长度
    16 字节且取值随机，误命中概率极低。
    """
    guid_index = pkg.guid_index
    all_guids = list(guid_index.keys())

    for item in pkg.items:
        refs: Set[bytes] = set()
        blob = item.metadata
        for g in all_guids:
            if g == item.guid:
                continue
            if blob.find(g) >= 0:
                refs.add(g)
        item.refs = refs

        external: Set[bytes] = set()
        for g1, g2, g3 in item.deps:
            for g in (g1, g2, g3):
                if g == ZERO_GUID:
                    continue
                if g in guid_index and g != item.guid:
                    refs.add(g)
                elif g not in guid_index:
                    external.add(g)
        item.external_refs = external


def dependency_closure(items: Sequence[AssetItem],
                       guid_index: Dict[bytes, AssetItem]) -> List[AssetItem]:
    """返回 items 及其全部依赖闭包（依赖在前，被依赖者先输出）。"""
    seen: Set[bytes] = set()
    order: List[AssetItem] = []

    def visit(item: AssetItem) -> None:
        if item.guid in seen:
            return
        seen.add(item.guid)
        for ref in sorted(item.requires()):
            dep = guid_index.get(ref)
            if dep is not None:
                visit(dep)
        order.append(item)

    for it in items:
        visit(it)
    return order


# --------------------------------------------------------------------------
# 字符串 / 路径扫描与重映射
# --------------------------------------------------------------------------

_PRINTABLE = re.compile(rb"[\x20-\x7e]{4,}")
_PATHISH_EXT = (
    ".fbx", ".dds", ".tga", ".png", ".psd", ".tif", ".tiff", ".exr", ".bmp",
    ".jpg", ".jpeg", ".xml", ".msh", ".brf", ".obj", ".dae", ".gltf",
    ".tpac", ".gtex", ".txt", ".ini", ".cfg", ".mp3", ".wav", ".ogg",
)
_PATH_HINTS = ("AssetSources", "AssetPackages", "EmAssetPackages", "Modules",
               "ModuleData", ":/", ":\\", "BASE", "asset_sources")


def looks_like_path(text: str) -> bool:
    if "/" in text or "\\" in text:
        return True
    low = text.lower()
    if low.endswith(_PATHISH_EXT):
        return True
    return any(hint.lower() in low for hint in _PATH_HINTS)


def scan_strings(blob: bytes, min_len: int = 5) -> List[Tuple[int, str]]:
    """返回 (起始偏移, 字符串) 列表（ASCII/UTF-8 可打印串）。"""
    out: List[Tuple[int, str]] = []
    for m in _PRINTABLE.finditer(blob):
        raw = m.group()
        if len(raw) < min_len:
            continue
        out.append((m.start(), raw.decode("ascii", errors="replace")))
    return out


def is_sized_string_at(blob: bytes, start: int, length: int) -> bool:
    """start 处的可打印串是否由前 4 字节的 i32 长度前缀描述。"""
    if start < 4:
        return False
    (declared,) = struct.unpack_from("<i", blob, start - 4)
    return declared == length


def find_sized_strings(blob: bytes, predicate=None,
                       min_len: int = 4) -> List[Tuple[int, int, str]]:
    """找出所有"带长度前缀"的字符串：(长度字段偏移, 长度, 文本)。

    以长度前缀声明的值为准，而不是以可打印扫描的终点为准。真实资源里
    字符串后面常常紧跟着别的字段（"$BASE/.../a.png" 之后紧跟 0x69 0x72），
    扫描会把这些字节也吞进来，只有相信长度前缀才能拿到正确边界。
    """
    out: List[Tuple[int, int, str]] = []
    for start, text in scan_strings(blob, min_len=min_len):
        if start < 4:
            continue
        (declared,) = struct.unpack_from("<i", blob, start - 4)
        if declared < min_len or declared > len(text):
            continue
        real = text[:declared]
        if predicate is not None and not predicate(real):
            continue
        out.append((start - 4, declared, real))
    return out


def printable_ratio(sample: bytes) -> float:
    if not sample:
        return 0.0
    good = sum(1 for b in sample if 0x20 <= b < 0x7F or b in (9, 10, 13))
    return good / len(sample)


@dataclass
class MappingRule:
    """一条重映射规则。"""
    old: str
    new: str
    enabled: bool = True
    note: str = ""


@dataclass
class RewriteStats:
    package: str = ""
    item: str = ""
    area: str = ""
    rule: str = ""
    kind: str = ""   # "name" | "sized" | "raw-inline"
    count: int = 0


@dataclass
class ScanOptions:
    """控制扫描范围，避免对上百 MB 的顶点/像素数据做无谓扫描。"""
    scan_metadata: bool = True
    max_segment_size: int = 4 << 20      # 超过此大小的段不解压扫描
    min_printable_ratio: float = 0.60    # 头部采样可打印率低于此值视为二进制数据


class Remapper:
    """按规则改写 tpac 内的路径 / 名称引用。

    安全策略（由保守到激进）：
      1. 等长替换：old / new 长度相同 -> 直接字节替换，不改变任何结构长度，零风险。
      2. 带长度前缀的字符串：同步改写 i32 长度前缀，结构自洽。
      3. 其余情况（非长度前缀且长度变化）-> 跳过并报告，绝不硬改。
    """

    def __init__(self, rules: Sequence[MappingRule], options: Optional[ScanOptions] = None):
        self.rules = [r for r in rules if r.enabled and r.old and r.old != r.new]
        self.options = options or ScanOptions()
        self.stats: List[RewriteStats] = []
        self.skipped: List[str] = []

    # -- 单块改写 ---------------------------------------------------------
    def rewrite_blob(self, blob: bytes, where: str, package: str = "",
                     item: str = "") -> Tuple[bytes, int]:
        total = 0
        for rule in self.rules:
            old_b = rule.old.encode("utf-8")
            new_b = rule.new.encode("utf-8")
            if old_b not in blob:
                continue

            label = "%s -> %s" % (rule.old, rule.new)

            # 1) 长度前缀字符串（支持变长）
            handled = 0
            work = blob
            while True:
                hits = [h for h in find_sized_strings(work) if rule.old in h[2]]
                if not hits:
                    break
                pos, length, text = hits[0]
                new_raw = text.replace(rule.old, rule.new).encode("utf-8")
                buf = bytearray(work)
                struct.pack_into("<i", buf, pos, len(new_raw))
                buf[pos + 4:pos + 4 + length] = new_raw
                work = bytes(buf)
                handled += 1
                if handled > 512:  # 防止异常数据导致死循环
                    self.skipped.append(tr("err.rewrite_abort", where=where))
                    break
            if handled:
                blob = work
                total += handled
                self.stats.append(RewriteStats(package, item, where, label,
                                               "sized", handled))
                continue

            # 2) 等长内联替换
            if len(old_b) == len(new_b):
                cnt = blob.count(old_b)
                if cnt:
                    blob = blob.replace(old_b, new_b)
                    total += cnt
                    self.stats.append(RewriteStats(package, item, where, label,
                                                   "raw-inline", cnt))
                continue

            # 3) 变长但找不到长度前缀 -> 报告，不硬改
            self.skipped.append(
                "%s：发现 '%s'，但没有长度前缀且长度变化，已跳过（可改成等长名称后重试）"
                % (where, rule.old))
        return blob, total

    # -- 整个包 -----------------------------------------------------------
    def rewrite_package(self, pkg: TpacPackage) -> int:
        total = 0
        opts = self.options
        for item in pkg.items:
            for rule in self.rules:
                if rule.old in item.name:
                    new_name = item.name.replace(rule.old, rule.new)
                    self.stats.append(RewriteStats(
                        pkg.source_path, item.name, "name",
                        "%s -> %s" % (item.name, new_name), "name", 1))
                    item.name = new_name
                    total += 1

            if opts.scan_metadata:
                blob, n = self.rewrite_blob(item.metadata, "metadata",
                                            pkg.source_path, item.name)
                if n:
                    item.metadata = blob
                    total += n

            for idx, seg in enumerate(item.segments):
                where = "segment#%d" % idx
                if seg.storage_size > opts.max_segment_size:
                    continue
                try:
                    data = seg.get_data()
                except TpacError as exc:
                    self.skipped.append(tr("err.decompress_fail", where=where,
                                                name=item.name, err=exc))
                    continue
                if len(data) > 4096 and printable_ratio(data[:4096]) < opts.min_printable_ratio:
                    continue  # 顶点 / 像素数据，不含路径
                blob, n = self.rewrite_blob(data, where, pkg.source_path, item.name)
                if n:
                    seg.set_data(blob)
                    total += n
        return total


# --------------------------------------------------------------------------
# 扫描报告
# --------------------------------------------------------------------------

@dataclass
class PackageReport:
    path: str
    module: str
    size: int
    version: int
    item_count: int
    types: Dict[str, int]
    strings: List[Tuple[str, str]] = field(default_factory=list)  # (区域, 文本)
    external_refs: Set[str] = field(default_factory=set)
    error: str = ""


def module_name_of(tpac_path: str) -> str:
    """从 .../Modules/<ModuleName>/... 推断模块名。"""
    norm = tpac_path.replace("\\", "/")
    marker = "/Modules/"
    pos = norm.rfind(marker)
    if pos < 0:
        return ""
    return norm[pos + len(marker):].split("/")[0]


def scan_package(path: str, options: Optional[ScanOptions] = None) -> PackageReport:
    """只读扫描一个 tpac，返回结构 / 路径字符串 / 外部依赖概览。"""
    options = options or ScanOptions()
    try:
        pkg = load_tpac(path)
    except Exception as exc:  # noqa: BLE001
        return PackageReport(path, module_name_of(path), os.path.getsize(path)
                             if os.path.exists(path) else 0,
                             0, 0, {}, error=str(exc))

    types: Dict[str, int] = {}
    for item in pkg.items:
        types[item.type_name] = types.get(item.type_name, 0) + 1

    strings: List[Tuple[str, str]] = []
    seen: Set[Tuple[str, str]] = set()
    for item in pkg.items:
        for where, blob in (("name", item.name.encode("utf-8")),
                            ("metadata", item.metadata)):
            for _start, text in scan_strings(blob):
                if looks_like_path(text):
                    key = (where, text)
                    if key not in seen:
                        seen.add(key)
                        strings.append(("%s[%s]" % (where, item.name), text))

    build_dependency_graph(pkg)
    external = {guid_str(g) for item in pkg.items for g in item.external_refs}

    report = PackageReport(
        path=path,
        module=module_name_of(path),
        size=os.path.getsize(path),
        version=pkg.version,
        item_count=len(pkg.items),
        types=types,
        strings=strings,
        external_refs=external,
    )
    pkg.close()
    return report
