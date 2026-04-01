"""Constant pool and .data/.rodata section management.

Collects all string literals, float constants, and large integer constants
encountered during codegen and emits them into the appropriate sections of
the assembly output.

Usage::

    pool = LiteralPool()

    # During expression codegen:
    lbl = pool.intern_string("hello, world\\n")
    em.la(T0, lbl)                  # load address of the string

    lbl = pool.intern_float(3.14159)
    em.la(T0, lbl)
    em.lwc1(F4, 0, T0)              # load the float constant

    # After all codegen is done:
    pool.emit_rodata(em)            # emit .rodata section into emitter
    pool.emit_data(em)              # emit .data section (mutable statics)
"""

from __future__ import annotations
import struct
from typing import Dict, List, Optional, Tuple

from .emit import Emitter


class LiteralPool:
    """Accumulates read-only constants for .rodata and mutable globals for .data."""

    def __init__(self):
        self._strings:  Dict[str, str]   = {}  # value → label
        self._floats:   Dict[float, str] = {}  # value → label
        self._doubles:  Dict[float, str] = {}
        self._words:    List[Tuple[str, int]] = []  # (label, value)
        self._data_syms: List[Tuple[str, int, int, Optional[int]]] = []
        # (label, size_bytes, align, init_value_or_None)
        self._counter = 0

    def _fresh(self, prefix: str = '.Lc') -> str:
        n = self._counter
        self._counter += 1
        return f'{prefix}{n}'

    # ── String literals ───────────────────────────────────────────────────────

    def intern_string(self, value: str) -> str:
        """Return the .rodata label for a string literal, creating it if new."""
        if value not in self._strings:
            lbl = self._fresh('.Lstr')
            self._strings[value] = lbl
        return self._strings[value]

    # ── Float constants ───────────────────────────────────────────────────────

    def intern_float(self, value: float) -> str:
        """Return a .rodata label for an f32 constant."""
        if value not in self._floats:
            lbl = self._fresh('.Lf32')
            self._floats[value] = lbl
        return self._floats[value]

    def intern_double(self, value: float) -> str:
        """Return a .rodata label for an f64 constant."""
        if value not in self._doubles:
            lbl = self._fresh('.Lf64')
            self._doubles[value] = lbl
        return self._doubles[value]

    # ── Word constants ────────────────────────────────────────────────────────

    def intern_word(self, value: int) -> str:
        """Return a .rodata label for a 32-bit integer constant."""
        lbl = self._fresh('.Lw')
        self._words.append((lbl, value & 0xFFFFFFFF))
        return lbl

    # ── Static / global variables ─────────────────────────────────────────────

    def add_static(self, name: str, size: int, align: int,
                   init_value: Optional[int] = None) -> str:
        """Register a static variable in .data (or .bss if no init value)."""
        self._data_syms.append((name, size, align, init_value))
        return name

    # ── Emission ──────────────────────────────────────────────────────────────

    def emit_rodata(self, em: Emitter) -> None:
        """Emit the .rodata section with all interned constants."""
        has_content = (self._strings or self._floats or self._doubles or self._words)
        if not has_content:
            return

        em.blank()
        em.section_rodata()

        # Strings
        for value, lbl in self._strings.items():
            em.align(0)     # byte alignment
            em.label(lbl)
            em.asciiz(value)

        # f32 constants
        for value, lbl in self._floats.items():
            em.align(2)     # 4-byte alignment
            em.label(lbl)
            # Emit as .word with the IEEE 754 bit pattern for exactness
            bits = struct.unpack('>I', struct.pack('>f', value))[0]
            em.word(bits)

        # f64 constants
        for value, lbl in self._doubles.items():
            em.align(3)     # 8-byte alignment
            em.label(lbl)
            bits = struct.unpack('>Q', struct.pack('>d', value))[0]
            hi = (bits >> 32) & 0xFFFFFFFF
            lo =  bits        & 0xFFFFFFFF
            em.word(hi)
            em.word(lo)

        # Word constants
        for lbl, val in self._words:
            em.align(2)
            em.label(lbl)
            em.word(val)

    def emit_data(self, em: Emitter) -> None:
        """Emit the .data and .bss sections for static variables."""
        if not self._data_syms:
            return

        # Separate initialised (.data) from uninitialised (.bss)
        inited   = [(n, sz, al, iv) for (n, sz, al, iv) in self._data_syms if iv is not None]
        uninited = [(n, sz, al, iv) for (n, sz, al, iv) in self._data_syms if iv is None]

        if inited:
            em.blank()
            em.section_data()
            for name, size, align, init_value in inited:
                log2 = (align - 1).bit_length()
                em.align(log2)
                em.globl(name)
                em.label(name)
                _emit_init(em, size, init_value)

        if uninited:
            em.blank()
            em.section_bss()
            for name, size, align, _ in uninited:
                log2 = (align - 1).bit_length()
                em.align(log2)
                em.globl(name)
                em.label(name)
                em.space(size)


def _emit_init(em: Emitter, size: int, value: int) -> None:
    """Emit initializer words/bytes for a static variable."""
    val = value & ((1 << (size * 8)) - 1) if size < 8 else value & 0xFFFFFFFFFFFFFFFF
    if size == 8:
        hi = (val >> 32) & 0xFFFFFFFF
        lo =  val        & 0xFFFFFFFF
        em.word(hi)
        em.word(lo)
    elif size == 4:
        em.word(val)
    elif size == 2:
        em.half(val)
    elif size == 1:
        em.byte(val)
    else:
        # Emit as sequence of words + remaining bytes
        offset = 0
        while offset + 4 <= size:
            em.word(0)
            offset += 4
        while offset < size:
            em.byte(0)
            offset += 1
