"""MIPS o32 calling convention.

o32 ABI rules relevant to PAK:
- Stack pointer ($sp) must be 8-byte aligned at every call site.
- The caller always reserves a 16-byte "argument save area" at the bottom
  of its own frame (offsets $sp+0 to $sp+15) so the callee may spill
  $a0-$a3 there if needed.
- First four integer/pointer arguments go in $a0-$a3.
- First two float arguments (when the formal parameter is float/double) go
  in $f12/$f14; integer arguments that follow still use $a2/$a3.
- Return value: $v0 for 32-bit int/ptr, $v0:$v1 for 64-bit, $f0 for float.
- Structs > 8 bytes are returned via a hidden first pointer argument in $a0;
  the caller allocates the storage and passes its address.
- Callee must preserve $s0-$s7, $fp, $ra, $f20-$f30.

Frame layout (grows downward):
    +--------------------------------------------+  <- $fp / high addr
    |  caller's arg save area (16 bytes)          |
    +--------------------------------------------+
    |  saved $ra (4 bytes)                        |
    +--------------------------------------------+
    |  saved $fp (4 bytes)                        |
    +--------------------------------------------+
    |  saved callee $s registers (4 bytes each)   |
    +--------------------------------------------+
    |  saved callee $f registers (8 bytes each)   |
    +--------------------------------------------+
    |  local variable storage                     |
    +--------------------------------------------+
    |  spill slots (if any)                       |
    +--------------------------------------------+
    |  arg save area for callees (16 bytes)       |  <- $sp / low addr
    +--------------------------------------------+

All sizes are rounded up to 8-byte alignment so $sp stays aligned.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from .registers import (
    SP, FP, RA, GP,
    A0, A1, A2, A3,
    F12, F14,
    V0, V1, F0, F2,
    S0, S1, S2, S3, S4, S5, S6, S7,
    F20, F22, F24, F26, F28, F30,
    gpr_number,
)


# ── Argument placement ────────────────────────────────────────────────────────

@dataclass
class ArgLoc:
    """Where a single argument lives when the call is in flight."""
    kind: str           # 'gpr' | 'fpr' | 'stack'
    reg: Optional[str]  # register name, or None for stack
    stack_offset: int   # SP-relative offset if kind=='stack'
    size: int           # bytes consumed (4 or 8)


def classify_args(param_types) -> List[ArgLoc]:
    """Assign each parameter to its o32 location.

    param_types is a list of type-info strings or objects with a
    ``is_float`` bool and ``size`` int attribute.  For simplicity this
    function accepts plain strings: 'f32', 'f64', or anything else
    (treated as integer/pointer of size 4).  Use TypeInfo objects from
    types.py in the full implementation.
    """
    gpr_regs  = [A0, A1, A2, A3]
    fpr_regs  = [F12, F14]
    gpr_idx   = 0
    fpr_idx   = 0
    stack_off = 16  # skip the 16-byte arg save area

    locs: List[ArgLoc] = []
    for pt in param_types:
        is_float = _is_float_type(pt)
        size     = _type_size(pt)

        if is_float and fpr_idx < len(fpr_regs) and gpr_idx < len(gpr_regs):
            # Float arg goes in $f12 or $f14; matching $a slot is skipped
            locs.append(ArgLoc('fpr', fpr_regs[fpr_idx], 0, size))
            fpr_idx  += 1
            gpr_idx  += (2 if size == 8 else 1)  # doubles consume two gpr slots
        elif not is_float and gpr_idx < len(gpr_regs):
            if size == 8:
                # 64-bit int: needs two consecutive even GPRs
                if gpr_idx % 2 == 1:
                    gpr_idx += 1  # align to even slot
                if gpr_idx + 1 < len(gpr_regs):
                    locs.append(ArgLoc('gpr', gpr_regs[gpr_idx], 0, size))
                    gpr_idx += 2
                else:
                    # Spill
                    off = (stack_off + 7) & ~7
                    locs.append(ArgLoc('stack', None, off, size))
                    stack_off = off + size
            else:
                locs.append(ArgLoc('gpr', gpr_regs[gpr_idx], 0, size))
                gpr_idx += 1
        else:
            # Stack argument
            off = (stack_off + (size - 1)) & ~(size - 1)
            locs.append(ArgLoc('stack', None, off, size))
            stack_off = off + size

    return locs


def _is_float_type(t) -> bool:
    if hasattr(t, 'is_float'):
        return t.is_float
    return str(t) in ('f32', 'f64')


def _type_size(t) -> int:
    if hasattr(t, 'size'):
        return t.size
    return {'f64': 8, 'i64': 8, 'u64': 8}.get(str(t), 4)


# ── Return value placement ────────────────────────────────────────────────────

@dataclass
class RetLoc:
    kind: str          # 'gpr' | 'gpr64' | 'fpr' | 'void' | 'struct_ptr'
    reg: str = ''
    reg2: str = ''     # second word for 64-bit returns


def classify_return(ret_type) -> RetLoc:
    """Determine where the return value lives."""
    if ret_type is None or str(ret_type) == 'void':
        return RetLoc('void')
    s = str(ret_type)
    if s in ('f32', 'f64'):
        return RetLoc('fpr', F0)
    if s in ('i64', 'u64'):
        return RetLoc('gpr64', V0, V1)
    # Structs larger than 8 bytes → hidden pointer (caller allocates, passes in $a0)
    size = _type_size(ret_type)
    if size > 8:
        return RetLoc('struct_ptr', A0)
    return RetLoc('gpr', V0)


# ── Frame builder ─────────────────────────────────────────────────────────────

# Callee-saved registers (must be saved/restored by every non-leaf function)
CALLEE_SAVED_GPRS = [S0, S1, S2, S3, S4, S5, S6, S7]
CALLEE_SAVED_FPRS = [F20, F22, F24, F26, F28, F30]


@dataclass
class FrameLayout:
    """Computed frame layout for a single function."""
    # Total frame size (multiple of 8)
    total_size:     int = 0

    # SP-relative offsets for key slots
    arg_save_area:  int = 0       # always 0; base of frame
    local_area_off: int = 16      # just above arg save area
    spill_off:      int = 0       # base of spill region (SP-relative)
    saved_ra_off:   int = 0       # SP-relative offset of saved $ra
    saved_fp_off:   int = 0       # SP-relative offset of saved $fp
    saved_gpr_offs: dict = field(default_factory=dict)   # reg → SP-relative offset
    saved_fpr_offs: dict = field(default_factory=dict)   # reg → SP-relative offset

    # How many bytes the locals + spills consume
    local_bytes:    int = 0


def build_frame(
    local_bytes: int,
    spill_bytes: int,
    used_callee_gprs: List[str],
    used_callee_fprs: List[str],
) -> FrameLayout:
    """Compute the full frame layout for a function.

    Layout (low to high, SP at bottom):
        [  arg save area  : 16 bytes  ]  $sp + 0
        [  local vars     : local_bytes (padded to 4) ]
        [  spill slots    : spill_bytes ]
        [  callee FPRs    : 8 bytes each ]
        [  callee GPRs    : 4 bytes each ]
        [  saved $fp      : 4 bytes  ]
        [  saved $ra      : 4 bytes  ]   <- top of frame ($sp + total_size - 4)
    """
    fl = FrameLayout()
    fl.local_bytes = local_bytes

    cursor = 16  # arg save area
    cursor += (local_bytes + 3) & ~3
    fl.spill_off = cursor
    cursor += (spill_bytes + 3) & ~3

    # Callee-saved FPRs (8-byte aligned)
    if used_callee_fprs:
        cursor = (cursor + 7) & ~7
    for freg in used_callee_fprs:
        fl.saved_fpr_offs[freg] = cursor
        cursor += 8

    # Callee-saved GPRs
    for reg in used_callee_gprs:
        fl.saved_gpr_offs[reg] = cursor
        cursor += 4

    # $fp
    fl.saved_fp_off = cursor
    cursor += 4

    # $ra
    fl.saved_ra_off = cursor
    cursor += 4

    # Round total frame up to 8-byte boundary
    fl.total_size = (cursor + 7) & ~7
    return fl
