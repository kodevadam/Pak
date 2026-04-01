"""MIPS register definitions and linear-scan register allocator.

Register conventions (MIPS o32 ABI):
    $zero / $0   — hardwired zero
    $at   / $1   — assembler temporary (reserved)
    $v0   / $2   — return value / expression result (low word)
    $v1   / $3   — return value (high word, or second return word)
    $a0   / $4   — argument 0 / hidden struct-return pointer
    $a1   / $5   — argument 1
    $a2   / $6   — argument 2
    $a3   / $7   — argument 3
    $t0   / $8   — caller-saved temporary
    $t1   / $9   — caller-saved temporary
    $t2   / $10  — caller-saved temporary
    $t3   / $11  — caller-saved temporary
    $t4   / $12  — caller-saved temporary
    $t5   / $13  — caller-saved temporary
    $t6   / $14  — caller-saved temporary
    $t7   / $15  — caller-saved temporary
    $s0   / $16  — callee-saved
    $s1   / $17  — callee-saved
    $s2   / $18  — callee-saved
    $s3   / $19  — callee-saved
    $s4   / $20  — callee-saved
    $s5   / $21  — callee-saved
    $s6   / $22  — callee-saved
    $s7   / $23  — callee-saved
    $t8   / $24  — caller-saved temporary
    $t9   / $25  — caller-saved temporary / indirect call register
    $k0   / $26  — kernel reserved
    $k1   / $27  — kernel reserved
    $gp   / $28  — global pointer
    $sp   / $29  — stack pointer
    $fp   / $30  — frame pointer (callee-saved)
    $ra   / $31  — return address (callee must preserve)

FPU registers (paired in o32 for doubles):
    $f0, $f2     — return values
    $f4–$f10     — caller-saved temporaries
    $f12, $f14   — first two float/double arguments
    $f16, $f18   — caller-saved temporaries
    $f20–$f30    — callee-saved (even-numbered only for doubles)
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional


# ── Register name constants ───────────────────────────────────────────────────

ZERO = '$zero'
AT   = '$at'
V0   = '$v0'
V1   = '$v1'
A0   = '$a0'
A1   = '$a1'
A2   = '$a2'
A3   = '$a3'
T0   = '$t0'
T1   = '$t1'
T2   = '$t2'
T3   = '$t3'
T4   = '$t4'
T5   = '$t5'
T6   = '$t6'
T7   = '$t7'
S0   = '$s0'
S1   = '$s1'
S2   = '$s2'
S3   = '$s3'
S4   = '$s4'
S5   = '$s5'
S6   = '$s6'
S7   = '$s7'
T8   = '$t8'
T9   = '$t9'
K0   = '$k0'
K1   = '$k1'
GP   = '$gp'
SP   = '$sp'
FP   = '$fp'
RA   = '$ra'

# FPU
F0  = '$f0'
F2  = '$f2'
F4  = '$f4'
F6  = '$f6'
F8  = '$f8'
F10 = '$f10'
F12 = '$f12'
F14 = '$f14'
F16 = '$f16'
F18 = '$f18'
F20 = '$f20'
F22 = '$f22'
F24 = '$f24'
F26 = '$f26'
F28 = '$f28'
F30 = '$f30'

# Ordered pools for allocation
_CALLER_SAVED_GPRS = [T0, T1, T2, T3, T4, T5, T6, T7, T8, T9]
_CALLEE_SAVED_GPRS = [S0, S1, S2, S3, S4, S5, S6, S7]

# Float temporaries (caller-saved, available for expression temporaries)
_CALLER_SAVED_FPRS = [F4, F6, F8, F10, F16, F18]
# Float callee-saved
_CALLEE_SAVED_FPRS = [F20, F22, F24, F26, F28, F30]

# Argument registers
ARG_GPRS = [A0, A1, A2, A3]
ARG_FPRS = [F12, F14]

# Return registers
RET_GPR  = V0
RET_GPR2 = V1
RET_FPR  = F0


# ── Register number helpers ───────────────────────────────────────────────────

_GPR_NUMBER: dict[str, int] = {
    ZERO: 0, AT: 1, V0: 2, V1: 3,
    A0: 4,  A1: 5,  A2: 6,  A3: 7,
    T0: 8,  T1: 9,  T2: 10, T3: 11,
    T4: 12, T5: 13, T6: 14, T7: 15,
    S0: 16, S1: 17, S2: 18, S3: 19,
    S4: 20, S5: 21, S6: 22, S7: 23,
    T8: 24, T9: 25, K0: 26, K1: 27,
    GP: 28, SP: 29, FP: 30, RA: 31,
}

def gpr_number(reg: str) -> int:
    return _GPR_NUMBER[reg]


# ── Allocation context ────────────────────────────────────────────────────────

@dataclass
class RegAlloc:
    """Simple linear-scan register allocator for a single function body.

    Strategy:
    - Temporaries (short-lived, within one expression) come from the
      caller-saved pool (_CALLER_SAVED_GPRS / _CALLER_SAVED_FPRS).
    - Long-lived values (live across calls or scope boundaries) use
      callee-saved regs; they are saved/restored in the function frame.
    - When a pool is exhausted, values spill to stack slots.

    Usage pattern::

        ra = RegAlloc()
        with ra.temp() as reg:   # borrows a caller-saved GPR
            emit.add(reg, A0, A1)
        # reg automatically returned to pool after `with` block
    """

    _free_temps:   list = field(default_factory=lambda: list(_CALLER_SAVED_GPRS))
    _free_saved:   list = field(default_factory=lambda: list(_CALLEE_SAVED_GPRS))
    _free_ftemps:  list = field(default_factory=lambda: list(_CALLER_SAVED_FPRS))
    _free_fsaved:  list = field(default_factory=lambda: list(_CALLEE_SAVED_FPRS))
    _used_saved:   set  = field(default_factory=set)
    _used_fsaved:  set  = field(default_factory=set)
    _next_spill:   int  = 0     # offset from $fp, grows downward

    # ── GPR allocation ────────────────────────────────────────────────────────

    def alloc_temp(self) -> Optional[str]:
        """Allocate a caller-saved GPR temporary. Returns None if exhausted."""
        return self._free_temps.pop() if self._free_temps else None

    def free_temp(self, reg: str) -> None:
        """Return a caller-saved GPR to the pool."""
        if reg not in self._free_temps:
            self._free_temps.append(reg)

    def alloc_saved(self) -> Optional[str]:
        """Allocate a callee-saved GPR. Marks it as used (needs save/restore)."""
        if not self._free_saved:
            return None
        reg = self._free_saved.pop()
        self._used_saved.add(reg)
        return reg

    def free_saved(self, reg: str) -> None:
        if reg not in self._free_saved:
            self._free_saved.append(reg)

    # ── FPR allocation ────────────────────────────────────────────────────────

    def alloc_ftemp(self) -> Optional[str]:
        return self._free_ftemps.pop() if self._free_ftemps else None

    def free_ftemp(self, reg: str) -> None:
        if reg not in self._free_ftemps:
            self._free_ftemps.append(reg)

    def alloc_fsaved(self) -> Optional[str]:
        if not self._free_fsaved:
            return None
        reg = self._free_fsaved.pop()
        self._used_fsaved.add(reg)
        return reg

    # ── Spill slots ───────────────────────────────────────────────────────────

    def alloc_spill(self, size: int = 4, align: int = 4) -> int:
        """Allocate a spill slot on the stack. Returns SP-relative offset (negative)."""
        self._next_spill = (self._next_spill + align - 1) & ~(align - 1)
        self._next_spill += size
        return -self._next_spill

    @property
    def spill_bytes(self) -> int:
        return self._next_spill

    @property
    def used_callee_gprs(self) -> list:
        """Callee-saved GPRs that were allocated; must be saved/restored."""
        return sorted(self._used_saved, key=lambda r: gpr_number(r))

    @property
    def used_callee_fprs(self) -> list:
        return sorted(self._used_fsaved, key=lambda r: int(r[2:]))


# ── Context-manager wrapper for temporary registers ───────────────────────────

class _TempReg:
    """Context manager that automatically frees a register on exit."""

    def __init__(self, alloc: RegAlloc, reg: str, is_float: bool = False):
        self._alloc = alloc
        self._reg = reg
        self._float = is_float

    def __enter__(self) -> str:
        return self._reg

    def __exit__(self, *_):
        if self._float:
            self._alloc.free_ftemp(self._reg)
        else:
            self._alloc.free_temp(self._reg)


def borrow_temp(alloc: RegAlloc) -> _TempReg:
    """Borrow a caller-saved GPR temporary as a context manager."""
    reg = alloc.alloc_temp()
    if reg is None:
        raise RuntimeError("GPR temporary pool exhausted — need spilling logic")
    return _TempReg(alloc, reg, is_float=False)


def borrow_ftemp(alloc: RegAlloc) -> _TempReg:
    """Borrow a caller-saved FPR temporary as a context manager."""
    reg = alloc.alloc_ftemp()
    if reg is None:
        raise RuntimeError("FPR temporary pool exhausted — need spilling logic")
    return _TempReg(alloc, reg, is_float=True)
