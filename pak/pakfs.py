"""PakFS - Pak File System archive format.

PakFS replaces DFS (Dragon File System) as the asset archive format for
Pak language projects. Assets are packed into a .pakfs archive that is
embedded into the final .z64 ROM.

Archive format:
  Header:
    magic:      4 bytes  "PKFS"
    version:    2 bytes  0x0001
    num_files:  2 bytes  number of entries
    index_off:  4 bytes  offset to file index

  File index (num_files entries):
    name_len:   2 bytes
    name:       name_len bytes (utf-8, no null)
    offset:     4 bytes  offset from start of archive to file data
    size:       4 bytes  file size in bytes
    flags:      2 bytes  reserved (0)

  File data:
    (raw bytes, 16-byte aligned)
"""

import struct
import os
from pathlib import Path
from typing import List, Tuple

MAGIC = b'PKFS'
VERSION = 1


def pack(files: List[Tuple[str, bytes]]) -> bytes:
    """Pack files into a PakFS archive.

    Args:
        files: list of (name, data) pairs

    Returns:
        Raw archive bytes
    """
    # Build index and data sections
    index_entries = []
    data_chunks = []
    data_offset = 0

    # Reserve space for header (12 bytes) and index (computed below)
    # First compute index size
    index_size = 0
    for name, _ in files:
        name_bytes = name.encode('utf-8')
        index_size += 2 + len(name_bytes) + 4 + 4 + 2  # name_len + name + offset + size + flags

    header_size = 12
    index_offset = header_size
    data_start = header_size + index_size
    # Align data start to 16 bytes
    data_start = (data_start + 15) & ~15

    current_offset = data_start
    for name, data in files:
        name_bytes = name.encode('utf-8')
        # Pad data to 16-byte boundary
        padded_size = (len(data) + 15) & ~15
        padded_data = data + b'\x00' * (padded_size - len(data))
        index_entries.append((name_bytes, current_offset, len(data)))
        data_chunks.append(padded_data)
        current_offset += padded_size

    # Build archive
    out = bytearray()

    # Header
    out += MAGIC
    out += struct.pack('<HHI', VERSION, len(files), index_offset)

    # Index
    for name_bytes, offset, size in index_entries:
        out += struct.pack('<H', len(name_bytes))
        out += name_bytes
        out += struct.pack('<IIH', offset, size, 0)

    # Pad to data_start
    while len(out) < data_start:
        out += b'\x00'

    # Data
    for chunk in data_chunks:
        out += chunk

    return bytes(out)


def unpack(data: bytes) -> List[Tuple[str, bytes]]:
    """Unpack a PakFS archive.

    Returns:
        list of (name, data) pairs
    """
    if data[:4] != MAGIC:
        raise ValueError('Not a PakFS archive (bad magic)')

    version, num_files, index_offset = struct.unpack_from('<HHI', data, 4)
    if version != VERSION:
        raise ValueError(f'Unsupported PakFS version: {version}')

    files = []
    pos = index_offset
    for _ in range(num_files):
        name_len = struct.unpack_from('<H', data, pos)[0]
        pos += 2
        name = data[pos:pos + name_len].decode('utf-8')
        pos += name_len
        offset, size, flags = struct.unpack_from('<IIH', data, pos)
        pos += 10
        file_data = data[offset:offset + size]
        files.append((name, file_data))

    return files


def pack_directory(asset_dir: Path, output: Path) -> int:
    """Pack all files in a directory into a PakFS archive.

    Returns:
        Number of files packed
    """
    files = []
    for filepath in sorted(asset_dir.rglob('*')):
        if filepath.is_file():
            rel = filepath.relative_to(asset_dir)
            name = str(rel).replace(os.sep, '/')
            data = filepath.read_bytes()
            files.append((name, data))

    if files:
        archive = pack(files)
        output.write_bytes(archive)

    return len(files)
