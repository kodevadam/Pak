"""Inline expansions for PAK builtins and fixed-point arithmetic.

Handles compile-time and codegen-time expansion of:
  - sizeof(T) / sizeof(expr)   → integer constant
  - offsetof(Type, field)      → integer constant
  - align_of(T)                → integer constant
  - Fixed-point arithmetic     → MIPS instruction sequences
  - Type casts                 → sign-extend / truncate / FPU convert sequences

All functions receive an ``Emitter`` and return the register holding the
result (or ``None`` for void operations that produce no value).

Fixed-point arithmetic
----------------------
PAK supports three fixed-point formats:

    fix16.16  — Q16.16, stored as i32, 16 fractional bits
    fix10.5   — Q10.5,  stored as i16,  5 fractional bits
    fix1.15   — Q1.15,  stored as i16, 15 fractional bits

Addition/subtraction of two same-format values is just integer add/sub.
Multiplication requires a 64-bit intermediate:

    fix16.16 * fix16.16:
        mult  s1, s2            # 64-bit product in HI:LO
        mflo  tmp               # low 32 bits
        mfhi  tmp2              # high 32 bits
        srl   tmp,  tmp,  16    # shift low part right 16
        sll   tmp2, tmp2, 16    # shift high part left  16
        or    dst,  tmp,  tmp2  # combine

Division requires shifting the dividend left:
    fix16.16 / fix16.16:
        # Extend dividend to 64-bit shifted left 16
        sra   hi_reg, dividend, 16    # sign-extend upper bits
        sll   lo_reg, dividend, 16    # lower part shifted
        mthi  hi_reg
        mtlo  lo_reg
        div   lo_reg, divisor         # but we can't do 64-bit div directly
        # Fallback: call __pak_fix_div helper in runtime
"""

from __future__ import annotations
from typing import Optional

from .emit import Emitter
from .registers import (
    RegAlloc, borrow_temp,
    T0, T1, T2, T3, V0,
    ZERO,
)
from .types import MipsTypeEnv, TypeLayout, FRAC_BITS


# ── Compile-time builtins ─────────────────────────────────────────────────────

def expand_sizeof(type_node, tenv: MipsTypeEnv) -> int:
    """Return the size of a type as a compile-time integer constant."""
    return tenv.layout_of_type(type_node).size


def expand_offsetof(struct_name: str, field_name: str, tenv: MipsTypeEnv) -> int:
    """Return the byte offset of a struct field as a compile-time constant."""
    layout = tenv.layout_of_name(struct_name)
    fi = layout.field_info(field_name)
    if fi is None:
        raise KeyError(f"No field {field_name!r} in struct {struct_name!r}")
    return fi.offset


def expand_align_of(type_node, tenv: MipsTypeEnv) -> int:
    """Return the alignment requirement of a type as a compile-time constant."""
    return tenv.layout_of_type(type_node).align


# ── Fixed-point multiply ──────────────────────────────────────────────────────

def emit_fixmul(em: Emitter, ra: RegAlloc,
                dst: str, s1: str, s2: str,
                frac_bits: int) -> None:
    """Emit a fixed-point multiply sequence.

    Result = (s1 * s2) >> frac_bits, placed into dst.
    Uses HI:LO multiply + extraction.
    """
    em.mult(s1, s2)             # HI:LO = s1 * s2  (64-bit signed)
    if frac_bits == 16:
        # Extract the middle 32 bits of the 64-bit product
        with borrow_temp(ra) as tmp_hi, borrow_temp(ra) as tmp_lo:
            em.mflo(tmp_lo)
            em.mfhi(tmp_hi)
            em.srl(tmp_lo, tmp_lo, 16)          # low part: shift right 16
            em.sll(tmp_hi, tmp_hi, 16)          # high part: shift left  16
            em.or_(dst, tmp_lo, tmp_hi)
    elif frac_bits < 32:
        with borrow_temp(ra) as tmp_hi, borrow_temp(ra) as tmp_lo:
            em.mflo(tmp_lo)
            em.mfhi(tmp_hi)
            em.srl(tmp_lo, tmp_lo, frac_bits)
            em.sll(tmp_hi, tmp_hi, 32 - frac_bits)
            em.or_(dst, tmp_lo, tmp_hi)
    else:
        # frac_bits == 32: result is entirely in HI
        em.mfhi(dst)


def emit_fixdiv(em: Emitter, ra: RegAlloc,
                dst: str, dividend: str, divisor: str,
                frac_bits: int) -> None:
    """Emit a fixed-point division sequence.

    Result = (dividend << frac_bits) / divisor.
    For fix16.16 this requires a 64-bit shifted dividend; we call the
    runtime helper __pak_fix16_div to avoid complexity here.
    """
    if frac_bits == 16:
        # Call runtime helper: __pak_fix16_div(dividend, divisor) → $v0
        from .registers import A0, A1, RA
        em.move(A0, dividend)
        em.move(A1, divisor)
        em.jal('__pak_fix16_div')
        em.nop()
        if dst != V0:
            em.move(dst, V0)
    else:
        # For smaller frac bits we can shift in a single register
        with borrow_temp(ra) as tmp:
            em.sll(tmp, dividend, frac_bits)
            em.div(tmp, divisor)
            em.mflo(dst)


def emit_int_to_fix(em: Emitter, dst: str, src: str, frac_bits: int) -> None:
    """Convert integer → fixed-point by shifting left."""
    em.sll(dst, src, frac_bits)


def emit_fix_to_int(em: Emitter, dst: str, src: str, frac_bits: int) -> None:
    """Convert fixed-point → integer by arithmetic right-shift."""
    em.sra(dst, src, frac_bits)


# ── Integer cast sequences ────────────────────────────────────────────────────

def emit_int_cast(em: Emitter, dst: str, src: str,
                  from_size: int, to_size: int, to_signed: bool) -> None:
    """Truncate or sign/zero-extend between integer sizes.

    MIPS always works with 32-bit registers, so casts between 8/16/32-bit
    only require masking or sign-extending the register contents.
    Casts to 64-bit are not handled here (require register pairs).
    """
    if to_size >= 4:
        # 32-bit: just move (the register already holds the value)
        if dst != src:
            em.move(dst, src)
        return

    if to_size == 2:
        if to_signed:
            # Sign-extend 16-bit: shift left then arithmetically right
            em.sll(dst, src, 16)
            em.sra(dst, dst, 16)
        else:
            em.andi(dst, src, 0xFFFF)
        return

    if to_size == 1:
        if to_signed:
            em.sll(dst, src, 24)
            em.sra(dst, dst, 24)
        else:
            em.andi(dst, src, 0xFF)
        return


def emit_float_to_int(em: Emitter, dst_gpr: str, src_fpr: str,
                      is_double: bool = False) -> None:
    """Convert float/double in FPR to integer in GPR."""
    # Use an FPR scratch to hold the integer bits
    from .registers import F0
    cvt_tmp = F0  # use f0 as temp (caller must save if needed)
    if is_double:
        em.cvt_w_d(cvt_tmp, src_fpr)
    else:
        em.cvt_w_s(cvt_tmp, src_fpr)
    em.mfc1(dst_gpr, cvt_tmp)


def emit_int_to_float(em: Emitter, dst_fpr: str, src_gpr: str,
                      is_double: bool = False) -> None:
    """Convert integer in GPR to float/double in FPR."""
    # Move int to FPR first (mtc1), then cvt
    em.mtc1(src_gpr, dst_fpr)
    if is_double:
        em.cvt_d_w(dst_fpr, dst_fpr)
    else:
        em.cvt_s_w(dst_fpr, dst_fpr)


# ── Boolean helpers ───────────────────────────────────────────────────────────

def emit_bool_not(em: Emitter, dst: str, src: str) -> None:
    """Logical NOT: dst = (src == 0) ? 1 : 0."""
    em.sltiu(dst, src, 1)


def emit_bool_and(em: Emitter, ra: RegAlloc,
                  dst: str, s1: str, s2: str) -> None:
    """Short-circuit &&: dst = (s1 != 0 && s2 != 0)."""
    # Both must be non-zero.  Since the caller already has both values in
    # registers (no short-circuit on already-evaluated subexprs), we just:
    with borrow_temp(ra) as tmp:
        em.sltiu(tmp, s1, 1)    # tmp = (s1 == 0)
        em.sltiu(dst, s2, 1)    # dst = (s2 == 0)
        em.or_(dst, tmp, dst)   # either zero → result is 0
        em.sltiu(dst, dst, 1)   # flip: 1 if both non-zero


def emit_bool_or(em: Emitter, ra: RegAlloc,
                 dst: str, s1: str, s2: str) -> None:
    """Short-circuit ||: dst = (s1 != 0 || s2 != 0)."""
    with borrow_temp(ra) as tmp:
        em.or_(tmp, s1, s2)
        em.sltu(dst, ZERO, tmp)   # dst = (tmp != 0)
