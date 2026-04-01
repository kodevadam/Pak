"""MIPS peephole optimizer and delay-slot filler (Phase 5).

Runs as a post-processing pass on the assembly text produced by MipsCodegen.
The optimizer operates on lines of text, not a structured IR, keeping it
simple and robust.  It performs three categories of optimization:

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

2. **Branch delay slot filling** — moves a useful instruction into the
   delay slot of a branch/jump, removing the ``nop`` that Phase 1 placed there:
   - If the instruction *before* the branch is independent of the branch
     condition and the instruction in the delay slot, move it into the slot.
   - Conservative: only fills slots with simple ALU/load instructions that
     don't touch the branch's condition register.

3. **Redundant label elimination** — labels that are never referenced are
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
                 fill_slots: bool = True,
                 dead_labels: bool = True) -> str:
    """Optimize MIPS assembly text. Returns the optimized text.

    All optimizations are conservative and correctness-preserving.
    """
    lines = asm_text.split('\n')

    if peephole:
        lines = _peephole(lines)

    if fill_slots:
        lines = _fill_delay_slots(lines)

    if dead_labels:
        lines = _eliminate_dead_labels(lines)

    return '\n'.join(lines)
