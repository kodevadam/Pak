"""MIPS assembly emitter.

Produces GNU assembler (gas) compatible MIPS assembly text for use with
the libdragon N64 toolchain.  The emitter tracks the current section and
accumulates instruction and directive strings into an internal buffer;
call ``Emitter.getvalue()`` to retrieve the final .s text.

Instruction reference:
    All instructions follow MIPS I/II with VR4300 extensions.
    Delay slots after branches/jumps are filled with ``nop`` by default;
    the optimization phase (Phase 5) will back-fill them.

Usage::

    em = Emitter()
    em.section_text()
    em.globl('main')
    em.label('main')
    em.addiu(SP, SP, -32)
    em.sw(RA, 28, SP)
    em.jal('_pak_factorial')
    em.nop()
    em.lw(RA, 28, SP)
    em.addiu(SP, SP, 32)
    em.jr(RA)
    em.nop()
    print(em.getvalue())
"""

from __future__ import annotations
from typing import List, Optional
from io import StringIO


class Emitter:
    """Accumulates MIPS assembly text."""

    def __init__(self, indent: str = '    '):
        self._buf: List[str] = []
        self._indent = indent
        self._label_counter = 0

    # ── Output ────────────────────────────────────────────────────────────────

    def getvalue(self) -> str:
        return '\n'.join(self._buf) + '\n'

    def raw(self, line: str) -> None:
        """Emit a raw line (no automatic indentation)."""
        self._buf.append(line)

    def _instr(self, *parts: str) -> None:
        self._buf.append(self._indent + ' '.join(parts))

    def _comment(self, text: str) -> None:
        self._buf.append(self._indent + '# ' + text)

    def blank(self) -> None:
        self._buf.append('')

    def comment(self, text: str) -> None:
        self._comment(text)

    # ── Labels ────────────────────────────────────────────────────────────────

    def label(self, name: str) -> None:
        self._buf.append(f'{name}:')

    def fresh_label(self, prefix: str = '.L') -> str:
        """Generate a unique local label name."""
        n = self._label_counter
        self._label_counter += 1
        return f'{prefix}{n}'

    # ── Directives ───────────────────────────────────────────────────────────

    def section_text(self) -> None:
        self.raw('\t.section .text')

    def section_data(self) -> None:
        self.raw('\t.section .data')

    def section_rodata(self) -> None:
        self.raw('\t.section .rodata')

    def section_bss(self) -> None:
        self.raw('\t.section .bss')

    def globl(self, sym: str) -> None:
        self.raw(f'\t.globl {sym}')

    def type_func(self, sym: str) -> None:
        self.raw(f'\t.type {sym}, @function')

    def size_sym(self, sym: str, expr: str) -> None:
        self.raw(f'\t.size {sym}, {expr}')

    def align(self, n: int) -> None:
        """Align to 2^n bytes."""
        self.raw(f'\t.align {n}')

    def word(self, val) -> None:
        self.raw(f'\t.word {val}')

    def half(self, val) -> None:
        self.raw(f'\t.half {val}')

    def byte(self, val) -> None:
        self.raw(f'\t.byte {val}')

    def float_lit(self, val: float) -> None:
        self.raw(f'\t.float {val!r}')

    def double_lit(self, val: float) -> None:
        self.raw(f'\t.double {val!r}')

    def asciiz(self, s: str) -> None:
        escaped = s.replace('\\', '\\\\').replace('"', '\\"') \
                   .replace('\n', '\\n').replace('\r', '\\r').replace('\t', '\\t')
        self.raw(f'\t.asciiz "{escaped}"')

    def space(self, n: int) -> None:
        self.raw(f'\t.space {n}')

    def extern(self, sym: str) -> None:
        self.raw(f'\t.extern {sym}')

    # ── Pseudo-instructions ───────────────────────────────────────────────────

    def nop(self) -> None:
        self._instr('nop')

    def move(self, dst: str, src: str) -> None:
        """move dst, src — implemented as addu dst, src, $zero"""
        self._instr('move', dst + ',', src)

    def li(self, dst: str, imm: int) -> None:
        """li dst, imm — load immediate (assembler expands to lui+ori if needed)"""
        self._instr('li', dst + ',', str(imm))

    def la(self, dst: str, label: str) -> None:
        """la dst, label — load address"""
        self._instr('la', dst + ',', label)

    # ── Integer arithmetic ────────────────────────────────────────────────────

    def add(self, dst: str, s1: str, s2: str) -> None:
        self._instr('add', dst + ',', s1 + ',', s2)

    def addu(self, dst: str, s1: str, s2: str) -> None:
        self._instr('addu', dst + ',', s1 + ',', s2)

    def addiu(self, dst: str, s1: str, imm: int) -> None:
        self._instr('addiu', dst + ',', s1 + ',', str(imm))

    def sub(self, dst: str, s1: str, s2: str) -> None:
        self._instr('sub', dst + ',', s1 + ',', s2)

    def subu(self, dst: str, s1: str, s2: str) -> None:
        self._instr('subu', dst + ',', s1 + ',', s2)

    def mul(self, dst: str, s1: str, s2: str) -> None:
        """MIPS32 mul instruction (result in dst, no HI/LO)."""
        self._instr('mul', dst + ',', s1 + ',', s2)

    def mult(self, s1: str, s2: str) -> None:
        """mult s1, s2 — signed multiply; result in HI:LO."""
        self._instr('mult', s1 + ',', s2)

    def multu(self, s1: str, s2: str) -> None:
        self._instr('multu', s1 + ',', s2)

    def div(self, s1: str, s2: str) -> None:
        """div s1, s2 — signed divide; quotient in LO, remainder in HI."""
        self._instr('div', s1 + ',', s2)

    def divu(self, s1: str, s2: str) -> None:
        self._instr('divu', s1 + ',', s2)

    def mfhi(self, dst: str) -> None:
        self._instr('mfhi', dst)

    def mflo(self, dst: str) -> None:
        self._instr('mflo', dst)

    def mthi(self, src: str) -> None:
        self._instr('mthi', src)

    def mtlo(self, src: str) -> None:
        self._instr('mtlo', src)

    # ── Bitwise / shift ───────────────────────────────────────────────────────

    def and_(self, dst: str, s1: str, s2: str) -> None:
        self._instr('and', dst + ',', s1 + ',', s2)

    def andi(self, dst: str, s1: str, imm: int) -> None:
        self._instr('andi', dst + ',', s1 + ',', str(imm))

    def or_(self, dst: str, s1: str, s2: str) -> None:
        self._instr('or', dst + ',', s1 + ',', s2)

    def ori(self, dst: str, s1: str, imm: int) -> None:
        self._instr('ori', dst + ',', s1 + ',', str(imm))

    def xor(self, dst: str, s1: str, s2: str) -> None:
        self._instr('xor', dst + ',', s1 + ',', s2)

    def xori(self, dst: str, s1: str, imm: int) -> None:
        self._instr('xori', dst + ',', s1 + ',', str(imm))

    def nor(self, dst: str, s1: str, s2: str) -> None:
        self._instr('nor', dst + ',', s1 + ',', s2)

    def not_(self, dst: str, src: str) -> None:
        """not dst, src — implemented as nor dst, src, $zero"""
        self._instr('nor', dst + ',', src + ',', '$zero')

    def lui(self, dst: str, imm: int) -> None:
        self._instr('lui', dst + ',', str(imm))

    def sll(self, dst: str, src: str, shamt: int) -> None:
        self._instr('sll', dst + ',', src + ',', str(shamt))

    def srl(self, dst: str, src: str, shamt: int) -> None:
        self._instr('srl', dst + ',', src + ',', str(shamt))

    def sra(self, dst: str, src: str, shamt: int) -> None:
        self._instr('sra', dst + ',', src + ',', str(shamt))

    def sllv(self, dst: str, src: str, shamt_reg: str) -> None:
        self._instr('sllv', dst + ',', src + ',', shamt_reg)

    def srlv(self, dst: str, src: str, shamt_reg: str) -> None:
        self._instr('srlv', dst + ',', src + ',', shamt_reg)

    def srav(self, dst: str, src: str, shamt_reg: str) -> None:
        self._instr('srav', dst + ',', src + ',', shamt_reg)

    # ── Comparison ───────────────────────────────────────────────────────────

    def slt(self, dst: str, s1: str, s2: str) -> None:
        self._instr('slt', dst + ',', s1 + ',', s2)

    def sltu(self, dst: str, s1: str, s2: str) -> None:
        self._instr('sltu', dst + ',', s1 + ',', s2)

    def slti(self, dst: str, s1: str, imm: int) -> None:
        self._instr('slti', dst + ',', s1 + ',', str(imm))

    def sltiu(self, dst: str, s1: str, imm: int) -> None:
        self._instr('sltiu', dst + ',', s1 + ',', str(imm))

    def seq(self, dst: str, s1: str, s2: str) -> None:
        """seq dst, s1, s2 — set if equal (pseudo)."""
        self._instr('seq', dst + ',', s1 + ',', s2)

    def sne(self, dst: str, s1: str, s2: str) -> None:
        self._instr('sne', dst + ',', s1 + ',', s2)

    def sle(self, dst: str, s1: str, s2: str) -> None:
        self._instr('sle', dst + ',', s1 + ',', s2)

    def sge(self, dst: str, s1: str, s2: str) -> None:
        self._instr('sge', dst + ',', s1 + ',', s2)

    def sgt(self, dst: str, s1: str, s2: str) -> None:
        self._instr('sgt', dst + ',', s1 + ',', s2)

    # ── Loads ────────────────────────────────────────────────────────────────

    def lw(self, dst: str, offset: int, base: str) -> None:
        self._instr('lw', dst + ',', f'{offset}({base})')

    def lh(self, dst: str, offset: int, base: str) -> None:
        self._instr('lh', dst + ',', f'{offset}({base})')

    def lhu(self, dst: str, offset: int, base: str) -> None:
        self._instr('lhu', dst + ',', f'{offset}({base})')

    def lb(self, dst: str, offset: int, base: str) -> None:
        self._instr('lb', dst + ',', f'{offset}({base})')

    def lbu(self, dst: str, offset: int, base: str) -> None:
        self._instr('lbu', dst + ',', f'{offset}({base})')

    def lwc1(self, freg: str, offset: int, base: str) -> None:
        self._instr('lwc1', freg + ',', f'{offset}({base})')

    def ldc1(self, freg: str, offset: int, base: str) -> None:
        self._instr('ldc1', freg + ',', f'{offset}({base})')

    # ── Stores ───────────────────────────────────────────────────────────────

    def sw(self, src: str, offset: int, base: str) -> None:
        self._instr('sw', src + ',', f'{offset}({base})')

    def sh(self, src: str, offset: int, base: str) -> None:
        self._instr('sh', src + ',', f'{offset}({base})')

    def sb(self, src: str, offset: int, base: str) -> None:
        self._instr('sb', src + ',', f'{offset}({base})')

    def swc1(self, freg: str, offset: int, base: str) -> None:
        self._instr('swc1', freg + ',', f'{offset}({base})')

    def sdc1(self, freg: str, offset: int, base: str) -> None:
        self._instr('sdc1', freg + ',', f'{offset}({base})')

    # ── Branches ─────────────────────────────────────────────────────────────
    # Each branch is followed by a delay slot (caller must emit nop or useful instr).

    def beq(self, s1: str, s2: str, label: str) -> None:
        self._instr('beq', s1 + ',', s2 + ',', label)

    def bne(self, s1: str, s2: str, label: str) -> None:
        self._instr('bne', s1 + ',', s2 + ',', label)

    def beqz(self, reg: str, label: str) -> None:
        self._instr('beqz', reg + ',', label)

    def bnez(self, reg: str, label: str) -> None:
        self._instr('bnez', reg + ',', label)

    def bltz(self, reg: str, label: str) -> None:
        self._instr('bltz', reg + ',', label)

    def bgtz(self, reg: str, label: str) -> None:
        self._instr('bgtz', reg + ',', label)

    def blez(self, reg: str, label: str) -> None:
        self._instr('blez', reg + ',', label)

    def bgez(self, reg: str, label: str) -> None:
        self._instr('bgez', reg + ',', label)

    def blt(self, s1: str, s2: str, label: str) -> None:
        self._instr('blt', s1 + ',', s2 + ',', label)

    def ble(self, s1: str, s2: str, label: str) -> None:
        self._instr('ble', s1 + ',', s2 + ',', label)

    def bgt(self, s1: str, s2: str, label: str) -> None:
        self._instr('bgt', s1 + ',', s2 + ',', label)

    def bge(self, s1: str, s2: str, label: str) -> None:
        self._instr('bge', s1 + ',', s2 + ',', label)

    # ── Jumps ────────────────────────────────────────────────────────────────

    def j(self, label: str) -> None:
        self._instr('j', label)

    def jal(self, label: str) -> None:
        self._instr('jal', label)

    def jr(self, reg: str) -> None:
        self._instr('jr', reg)

    def jalr(self, reg: str, link: str = '$ra') -> None:
        self._instr('jalr', link + ',', reg)

    # ── FPU instructions ──────────────────────────────────────────────────────

    def add_s(self, fd: str, fs: str, ft: str) -> None:
        self._instr('add.s', fd + ',', fs + ',', ft)

    def sub_s(self, fd: str, fs: str, ft: str) -> None:
        self._instr('sub.s', fd + ',', fs + ',', ft)

    def mul_s(self, fd: str, fs: str, ft: str) -> None:
        self._instr('mul.s', fd + ',', fs + ',', ft)

    def div_s(self, fd: str, fs: str, ft: str) -> None:
        self._instr('div.s', fd + ',', fs + ',', ft)

    def neg_s(self, fd: str, fs: str) -> None:
        self._instr('neg.s', fd + ',', fs)

    def abs_s(self, fd: str, fs: str) -> None:
        self._instr('abs.s', fd + ',', fs)

    def sqrt_s(self, fd: str, fs: str) -> None:
        self._instr('sqrt.s', fd + ',', fs)

    def mov_s(self, fd: str, fs: str) -> None:
        self._instr('mov.s', fd + ',', fs)

    def add_d(self, fd: str, fs: str, ft: str) -> None:
        self._instr('add.d', fd + ',', fs + ',', ft)

    def sub_d(self, fd: str, fs: str, ft: str) -> None:
        self._instr('sub.d', fd + ',', fs + ',', ft)

    def mul_d(self, fd: str, fs: str, ft: str) -> None:
        self._instr('mul.d', fd + ',', fs + ',', ft)

    def div_d(self, fd: str, fs: str, ft: str) -> None:
        self._instr('div.d', fd + ',', fs + ',', ft)

    def cvt_s_w(self, fd: str, fs: str) -> None:
        """Convert word (integer) in fs to single float in fd."""
        self._instr('cvt.s.w', fd + ',', fs)

    def cvt_w_s(self, fd: str, fs: str) -> None:
        """Convert single float in fs to word (integer) in fd."""
        self._instr('cvt.w.s', fd + ',', fs)

    def cvt_d_w(self, fd: str, fs: str) -> None:
        self._instr('cvt.d.w', fd + ',', fs)

    def cvt_w_d(self, fd: str, fs: str) -> None:
        self._instr('cvt.w.d', fd + ',', fs)

    def cvt_s_d(self, fd: str, fs: str) -> None:
        self._instr('cvt.s.d', fd + ',', fs)

    def cvt_d_s(self, fd: str, fs: str) -> None:
        self._instr('cvt.d.s', fd + ',', fs)

    def mfc1(self, gpr: str, fpr: str) -> None:
        """Move from FPR to GPR."""
        self._instr('mfc1', gpr + ',', fpr)

    def mtc1(self, gpr: str, fpr: str) -> None:
        """Move from GPR to FPR."""
        self._instr('mtc1', gpr + ',', fpr)

    def c_lt_s(self, fs: str, ft: str) -> None:
        self._instr('c.lt.s', fs + ',', ft)

    def c_le_s(self, fs: str, ft: str) -> None:
        self._instr('c.le.s', fs + ',', ft)

    def c_eq_s(self, fs: str, ft: str) -> None:
        self._instr('c.eq.s', fs + ',', ft)

    def c_lt_d(self, fs: str, ft: str) -> None:
        self._instr('c.lt.d', fs + ',', ft)

    def c_le_d(self, fs: str, ft: str) -> None:
        self._instr('c.le.d', fs + ',', ft)

    def c_eq_d(self, fs: str, ft: str) -> None:
        self._instr('c.eq.d', fs + ',', ft)

    def bc1t(self, label: str) -> None:
        self._instr('bc1t', label)

    def bc1f(self, label: str) -> None:
        self._instr('bc1f', label)

    # ── Memory barrier ────────────────────────────────────────────────────────

    def sync(self) -> None:
        self._instr('sync')

    # ── Cache operations ──────────────────────────────────────────────────────

    def cache(self, op: int, offset: int, base: str) -> None:
        """CACHE instruction (op: encoded cache op, e.g. 0x19 for hit-writeback-D)."""
        self._instr('cache', f'{op:#x},', f'{offset}({base})')

    # ── Inline assembly pass-through ──────────────────────────────────────────

    def verbatim(self, asm_text: str) -> None:
        """Emit raw assembly text verbatim (for asm{} blocks)."""
        for line in asm_text.splitlines():
            self._buf.append(self._indent + line)
