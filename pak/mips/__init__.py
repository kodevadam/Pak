"""PAK → MIPS direct transpiler backend.

Pipeline:
    PAK source → (lexer/parser/typechecker) → AST → MipsCodegen → .s file
                                                                        ↓
                                               libdragon assembler/linker → N64 ROM

Modules
-------
registers   - MIPS register definitions and linear-scan allocator
abi         - MIPS o32 calling convention (arg passing, frame layout)
emit        - Assembly emitter (instructions, directives, labels)
types       - Type layout engine (size, alignment, struct field offsets)
literals    - Constant pool (.rodata/.data section management)
builtins    - Inline expansions for sizeof/offsetof/align_of and fixed-point math
n64_runtime - Libdragon FFI: maps n64.module.fn() → jal <symbol> with o32 ABI
mips_codegen - Top-level orchestrator: walks AST, drives all sub-generators
"""

from .mips_codegen import MipsCodegen

__all__ = ["MipsCodegen"]
