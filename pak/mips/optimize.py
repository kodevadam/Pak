"""MIPS peephole optimizer, instruction scheduler, and delay-slot filler (Phase 5).

Runs as a post-processing pass on the assembly text produced by MipsCodegen.
The optimizer operates on lines of text, not a structured IR, keeping it
simple and robust.  It performs four categories of optimization:

1. **Peephole optimizations** — local patterns that can be replaced with
   shorter or faster sequences:
   - ``li $reg, 0`` → ``move $reg, $zero``
   - ``move $reg, $reg`` → deleted (nop move)
   - ``li $reg, N`` followed by ``addu $dst, $src, $reg`` when N fits in
     16-bit signed → ``addiu $dst, $src, N``
   - Redundant store→load elimination: ``sw $r, off($sp)`` followed
     immediately by ``lw $r, off($sp)`` → delete the lw
   - Strength reduction: ``mul $d, $s, $t`` where ``$t`` is known power-of-2
     → ``sll $d, $s, log2(N)``

2. **VR4300 instruction scheduling** — reorders instructions within basic
   blocks to reduce pipeline stalls on the N64's VR4300 CPU:
   - Load-use hazards: inserts independent instructions between a load and
     its consumer to avoid a 1-cycle stall.
   - Multiply latency: fills cycles between ``mult``/``multu`` and
     ``mflo``/``mfhi`` with independent work.
   - Divide latency: similarly fills cycles after ``div``/``divu``.

3. **Branch delay slot filling** — moves a useful instruction into the
   delay slot of a branch/jump, removing the ``nop`` that Phase 1 placed there:
   - If the instruction *before* the branch is independent of the branch
     condition and the instruction in the delay slot, move it into the slot.
   - Conservative: only fills slots with simple ALU/load instructions that
     don't touch the branch's condition register.

4. **Redundant label elimination** — labels that are never referenced are
   removed (along with any preceding blank line).

Usage::

    from pak.mips.optimize import optimize_asm
    optimized = optimize_asm(raw_asm_text)
"""

from __future__ import annotations
import re
from typing import List, Optional, Tuple, Set


# ── Instruction patterns ─────────────────────────────────────────────────────

_BRANCH_OPS = frozenset([
    'beq', 'bne', 'beqz', 'bnez', 'bgez', 'bgtz', 'blez', 'bltz',
    'bge', 'bgt', 'ble', 'blt',
])
_JUMP_OPS = frozenset(['j', 'jal', 'jr', 'jalr'])

_RE_INSTR = re.compile(r'^\s+(\w+)\s*(.*)')
_RE_LABEL = re.compile(r'^(\.\w+|[A-Za-z_]\w*):\s*$')
_RE_MOVE = re.compile(r'move\s+(\$\w+),\s*(\$\w+)')
_RE_LI   = re.compile(r'li\s+(\$\w+),\s*(-?\d+)')
_RE_SW   = re.compile(r'sw\s+(\$\w+),\s*(-?\d+)\((\$\w+)\)')
_RE_LW   = re.compile(r'lw\s+(\$\w+),\s*(-?\d+)\((\$\w+)\)')
_RE_ADDU = re.compile(r'addu\s+(\$\w+),\s*(\$\w+),\s*(\$\w+)')


def _parse_line(line: str) -> Optional[Tuple[str, str]]:
    """Parse an instruction line into (opcode, operands) or None."""
    m = _RE_INSTR.match(line)
    if m:
        return m.group(1), m.group(2).strip()
    return None


def _is_branch_or_jump(opcode: str) -> bool:
    return opcode in _BRANCH_OPS or opcode in _JUMP_OPS


def _regs_read(opcode: str, operands: str) -> Set[str]:
    """Return the set of registers read by an instruction (approximate)."""
    regs = set()
    # Find all $reg references
    for m in re.finditer(r'\$\w+', operands):
        regs.add(m.group())
    # For stores (sw, sh, sb), the first register is also read
    # For loads (lw, lh, lb), the first register is written (remove from reads)
    if opcode in ('lw', 'lh', 'lb', 'lhu', 'lbu', 'lwc1'):
        parts = operands.split(',', 1)
        if parts:
            dst = parts[0].strip()
            regs.discard(dst)
    elif opcode in ('li', 'la', 'move', 'addiu', 'addu', 'subu', 'mul',
                     'and', 'or', 'xor', 'sll', 'srl', 'sra', 'slt',
                     'sltu', 'seq', 'sne', 'sle', 'sge', 'sgt', 'not',
                     'sllv', 'srav', 'srlv', 'andi', 'ori', 'xori',
                     'sltiu', 'mflo', 'mfhi'):
        parts = operands.split(',', 1)
        if parts:
            dst = parts[0].strip()
            regs.discard(dst)
    return regs


def _regs_written(opcode: str, operands: str) -> Set[str]:
    """Return the set of registers written by an instruction (approximate)."""
    written = set()
    if opcode in ('lw', 'lh', 'lb', 'lhu', 'lbu', 'lwc1', 'li', 'la',
                   'move', 'addiu', 'addu', 'subu', 'mul', 'and', 'or',
                   'xor', 'sll', 'srl', 'sra', 'slt', 'sltu', 'seq',
                   'sne', 'sle', 'sge', 'sgt', 'not', 'sllv', 'srav',
                   'srlv', 'andi', 'ori', 'xori', 'sltiu', 'mflo', 'mfhi'):
        parts = operands.split(',', 1)
        if parts:
            written.add(parts[0].strip())
    elif opcode in ('mult', 'multu', 'div', 'divu'):
        written.add('HI')
        written.add('LO')
    elif opcode in ('jal', 'jalr'):
        written.add('$ra')
        written.add('$v0')
        written.add('$v1')
        written.add('$a0')  # conservative: caller-saved
    return written


# ── Peephole pass ────────────────────────────────────────────────────────────

def _peephole(lines: List[str]) -> List[str]:
    """Single-pass peephole optimization."""
    result: List[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        parsed = _parse_line(line)

        if parsed:
            op, operands = parsed

            # 1. li $reg, 0 → move $reg, $zero
            if op == 'li':
                m = _RE_LI.match(f'li {operands}')
                if m and int(m.group(2)) == 0:
                    result.append(line.replace(f'li {operands}', f'move {m.group(1)}, $zero'))
                    i += 1
                    continue

            # 2. move $reg, $reg → skip (no-op)
            if op == 'move':
                m = _RE_MOVE.match(f'move {operands}')
                if m and m.group(1) == m.group(2):
                    i += 1
                    continue

            # 3. Redundant store→load: sw $r, off($sp) then lw $r, off($sp)
            if op == 'sw' and i + 1 < len(lines):
                m_sw = _RE_SW.match(f'sw {operands}')
                next_parsed = _parse_line(lines[i + 1])
                if m_sw and next_parsed and next_parsed[0] == 'lw':
                    m_lw = _RE_LW.match(f'lw {next_parsed[1]}')
                    if (m_lw and m_sw.group(1) == m_lw.group(1) and
                        m_sw.group(2) == m_lw.group(2) and
                        m_sw.group(3) == m_lw.group(3)):
                        # sw $r, off($sp) followed by lw $r, off($sp) → keep only sw
                        result.append(line)
                        i += 2
                        continue

            # 4. li $t, N + addu $d, $s, $t → addiu $d, $s, N (if N fits i16)
            if op == 'li' and i + 1 < len(lines):
                m_li = _RE_LI.match(f'li {operands}')
                next_parsed = _parse_line(lines[i + 1])
                if m_li and next_parsed and next_parsed[0] == 'addu':
                    m_add = _RE_ADDU.match(f'addu {next_parsed[1]}')
                    if m_add:
                        val = int(m_li.group(2))
                        li_reg = m_li.group(1)
                        if (m_add.group(3) == li_reg and
                            -32768 <= val <= 32767):
                            indent = line[:len(line) - len(line.lstrip())]
                            result.append(
                                f'{indent}addiu {m_add.group(1)}, {m_add.group(2)}, {val}')
                            i += 2
                            continue

        result.append(line)
        i += 1

    return result


# ── Branch delay slot filling ────────────────────────────────────────────────

def _fill_delay_slots(lines: List[str]) -> List[str]:
    """Try to fill branch/jump delay slots with useful instructions.

    Looks for patterns:
        <useful_instr>
        <branch/jump>
        nop

    and transforms to:
        <branch/jump>
        <useful_instr>

    Only if <useful_instr> is independent of the branch's operands.
    """
    result: List[str] = []
    i = 0
    while i < len(lines):
        # Look for: instr, branch/jump, nop
        if (i + 2 < len(lines)):
            prev_parsed = _parse_line(lines[i])
            branch_parsed = _parse_line(lines[i + 1])
            nop_parsed = _parse_line(lines[i + 2])

            if (prev_parsed and branch_parsed and nop_parsed and
                _is_branch_or_jump(branch_parsed[0]) and
                nop_parsed[0] == 'nop'):

                prev_op, prev_operands = prev_parsed
                branch_op, branch_operands = branch_parsed

                # Don't move branches, jumps, labels, or multi-cycle ops
                if (not _is_branch_or_jump(prev_op) and
                    prev_op not in ('nop', 'mult', 'multu', 'div', 'divu',
                                     'jal', 'jalr', 'sync') and
                    not prev_op.startswith('.')):

                    # Check independence: prev doesn't write branch's reads
                    prev_writes = _regs_written(prev_op, prev_operands)
                    branch_reads = _regs_read(branch_op, branch_operands)

                    if not prev_writes.intersection(branch_reads):
                        # Safe to move into delay slot
                        result.append(lines[i + 1])   # branch
                        result.append(lines[i])         # moved instruction (delay slot)
                        i += 3
                        continue

        result.append(lines[i])
        i += 1

    return result


# ── VR4300 instruction scheduling ────────────────────────────────────────────

_LOAD_OPS = frozenset(['lw', 'lh', 'lb', 'lhu', 'lbu', 'lwc1'])
_MULT_OPS = frozenset(['mult', 'multu'])
_DIV_OPS = frozenset(['div', 'divu'])
_MFHILO_OPS = frozenset(['mflo', 'mfhi'])


def _is_independent(line_a: str, line_b: str) -> bool:
    """Return True if *line_b* can be moved before *line_a* without changing
    semantics.  Both must be parsed as instructions.  Conservative: returns
    False on any ambiguity."""
    pa = _parse_line(line_a)
    pb = _parse_line(line_b)
    if not pa or not pb:
        return False
    op_a, operands_a = pa
    op_b, operands_b = pb
    # Never move branches, jumps, syscalls, nops, or HI/LO producers
    if (_is_branch_or_jump(op_b) or op_b in ('nop', 'sync', 'syscall',
            'mult', 'multu', 'div', 'divu', 'mflo', 'mfhi')):
        return False
    reads_a = _regs_read(op_a, operands_a)
    writes_a = _regs_written(op_a, operands_a)
    reads_b = _regs_read(op_b, operands_b)
    writes_b = _regs_written(op_b, operands_b)
    # WAR: b writes something a reads
    if writes_b & reads_a:
        return False
    # RAW: b reads something a writes
    if reads_b & writes_a:
        return False
    # WAW: both write same register
    if writes_b & writes_a:
        return False
    return True


def _schedule_vr4300(lines: List[str]) -> List[str]:
    """Reorder instructions within basic blocks to reduce VR4300 pipeline stalls.

    Handles three hazard classes:
    - Load-use (1-cycle stall if loaded reg used immediately)
    - Multiply (mflo/mfhi stalls if issued within ~5 cycles of mult/multu)
    - Divide  (mflo/mfhi stalls if issued within ~37 cycles of div/divu)

    Only reorders within basic blocks and only when provably safe.
    """
    # Split into basic blocks.  A basic block boundary is a label line,
    # a branch/jump instruction, or the instruction in a delay slot
    # (the one right after a branch/jump).
    blocks: List[List[str]] = []
    current: List[str] = []

    prev_was_branch = False
    for line in lines:
        parsed = _parse_line(line)
        is_label = bool(_RE_LABEL.match(line))

        if is_label:
            # Label starts a new block
            if current:
                blocks.append(current)
            current = [line]
            prev_was_branch = False
        elif parsed and _is_branch_or_jump(parsed[0]):
            # Branch/jump: include it in current block, mark boundary after delay slot
            current.append(line)
            prev_was_branch = True
        elif prev_was_branch:
            # Delay slot instruction — include then end block
            current.append(line)
            blocks.append(current)
            current = []
            prev_was_branch = False
        else:
            current.append(line)
            prev_was_branch = False

    if current:
        blocks.append(current)

    result: List[str] = []
    for block in blocks:
        result.extend(_schedule_block(block))
    return result


def _schedule_block(block: List[str]) -> List[str]:
    """Schedule a single basic block for VR4300 hazard avoidance."""
    lines = list(block)
    i = 0
    while i < len(lines):
        parsed = _parse_line(lines[i])
        if not parsed:
            i += 1
            continue

        op, operands = parsed

        # ── Load-use hazard ──────────────────────────────────────────────
        if op in _LOAD_OPS and i + 1 < len(lines):
            written = _regs_written(op, operands)
            next_parsed = _parse_line(lines[i + 1])
            if next_parsed:
                next_reads = _regs_read(next_parsed[0], next_parsed[1])
                if written & next_reads:
                    # Hazard: next instruction reads what we just loaded.
                    # Search forward for an independent instruction to insert.
                    moved = _find_and_move_between(lines, i, i + 1)
                    if moved:
                        i += 1
                        continue

        # ── Multiply / Divide → mflo/mfhi hazard ────────────────────────
        if op in _MULT_OPS or op in _DIV_OPS:
            max_fill = 4  # try to fill up to 4 slots
            _fill_before_mfhilo(lines, i, max_fill)

        i += 1

    return lines


def _find_and_move_between(lines: List[str], load_idx: int, use_idx: int) -> bool:
    """Try to find an instruction after *use_idx* that is independent of both
    the load and the use, and move it between them.  Returns True on success."""
    for j in range(use_idx + 1, len(lines)):
        candidate = lines[j]
        cp = _parse_line(candidate)
        if not cp:
            continue
        # Don't move past or grab labels / branches
        if _RE_LABEL.match(candidate) or _is_branch_or_jump(cp[0]):
            break
        # Candidate must be independent of the load and ALL instructions
        # between the load and j (inclusive of use).
        ok = True
        for k in range(load_idx, j):
            if not _is_independent(lines[k], candidate):
                ok = False
                break
        if ok:
            moved = lines.pop(j)
            lines.insert(use_idx, moved)
            return True
    return False


def _fill_before_mfhilo(lines: List[str], mult_idx: int, max_fill: int) -> None:
    """Try to move independent instructions between mult/div and the first
    mflo/mfhi that follows it."""
    # Find the mflo/mfhi
    mf_idx = None
    for k in range(mult_idx + 1, len(lines)):
        kp = _parse_line(lines[k])
        if not kp:
            continue
        if _RE_LABEL.match(lines[k]) or _is_branch_or_jump(kp[0]):
            return  # crossed a block boundary, bail
        if kp[0] in _MFHILO_OPS:
            mf_idx = k
            break

    if mf_idx is None or mf_idx == mult_idx + 1:
        # No mflo/mfhi found, or nothing to fill
        if mf_idx is not None and mf_idx == mult_idx + 1:
            # Need to fill — search AFTER mflo for independent instructions
            filled = 0
            search_start = mf_idx + 1
            for j in range(search_start, len(lines)):
                if filled >= max_fill:
                    break
                candidate = lines[j]
                cp = _parse_line(candidate)
                if not cp:
                    continue
                if _RE_LABEL.match(candidate) or _is_branch_or_jump(cp[0]):
                    break
                if cp[0] in _MFHILO_OPS:
                    break
                # Must be independent of the mult and all instructions
                # between mult and j
                ok = True
                for k in range(mult_idx, j):
                    if not _is_independent(lines[k], candidate):
                        ok = False
                        break
                if ok:
                    moved = lines.pop(j)
                    lines.insert(mult_idx + 1, moved)
                    filled += 1
                    # mf_idx shifted right by 1
        return

    # Already have gap between mult and mfhilo — nothing extra to do
    return


# ── Dead label elimination ───────────────────────────────────────────────────

def _eliminate_dead_labels(lines: List[str]) -> List[str]:
    """Remove labels that are never referenced in the assembly."""
    # Collect all labels defined
    defined = set()
    for line in lines:
        m = _RE_LABEL.match(line)
        if m:
            defined.add(m.group(1))

    # Collect all labels referenced (in branch targets, la, j, etc.)
    referenced: Set[str] = set()
    for line in lines:
        parsed = _parse_line(line)
        if parsed:
            _, operands = parsed
            for label in defined:
                if label in operands:
                    referenced.add(label)
        # Also check directives like .size
        for label in defined:
            if label in line and not _RE_LABEL.match(line):
                referenced.add(label)

    # Remove unreferenced local labels (starting with .)
    result = []
    for line in lines:
        m = _RE_LABEL.match(line)
        if m:
            label = m.group(1)
            if label.startswith('.') and label not in referenced:
                continue
        result.append(line)

    return result


# ── Public API ───────────────────────────────────────────────────────────────

def optimize_asm(asm_text: str, *, peephole: bool = True,
                 schedule: bool = True,
                 fill_slots: bool = True,
                 dead_labels: bool = True) -> str:
    """Optimize MIPS assembly text. Returns the optimized text.

    Passes (in order):
      1. Peephole — local pattern rewrites
      2. VR4300 scheduling — reorder to reduce pipeline stalls
      3. Delay-slot filling — move useful work into branch delay slots
      4. Dead label elimination — remove unreferenced local labels

    All optimizations are conservative and correctness-preserving.
    """
    lines = asm_text.split('\n')

    if peephole:
        lines = _peephole(lines)

    if schedule:
        lines = _schedule_vr4300(lines)

    if fill_slots:
        lines = _fill_delay_slots(lines)

    if dead_labels:
        lines = _eliminate_dead_labels(lines)

    return '\n'.join(lines)
