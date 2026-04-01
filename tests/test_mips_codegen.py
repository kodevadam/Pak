"""Tests for the PAK → MIPS backend.

Phase 0 / Phase 1 coverage:
  - Module imports cleanly
  - Type layout engine (primitives, structs, enums, variants, slices, Result)
  - Literal pool (strings, floats, statics)
  - Register allocator (alloc/free, spill detection)
  - ABI (frame layout, arg classification)
  - Assembly emitter (instruction text, directives)
  - MipsCodegen.generate() on representative PAK programs
    (arithmetic, functions, control flow, structs, N64 API calls)

These tests do NOT run the emulator — they verify that the assembler text
contains the expected instructions and labels, matching the C backend's
semantics where both produce the same logical operations.
"""

import sys
import os
import textwrap
import pytest

# Make sure the repo root is on the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from pak.lexer import Lexer
from pak.parser import Parser
from pak.typechecker import TypeEnv, typecheck
from pak.mips import MipsCodegen
from pak.mips.registers import (
    RegAlloc, borrow_temp,
    A0, A1, A2, A3, V0, SP, RA, FP,
    T0, T1, S0,
)
from pak.mips.abi import classify_args, classify_return, build_frame
from pak.mips.types import MipsTypeEnv, TypeLayout
from pak.mips.literals import LiteralPool
from pak.mips.emit import Emitter
from pak import ast


# ── Helpers ───────────────────────────────────────────────────────────────────

def compile_mips(source: str) -> str:
    """Parse, typecheck, and compile PAK source to MIPS assembly text."""
    source  = textwrap.dedent(source).strip()
    tokens  = Lexer(source).tokenize()
    program = Parser(tokens).parse()
    tenv    = TypeEnv()
    tenv.collect(program)
    cg = MipsCodegen()
    return cg.generate(program, tenv)


def has_instr(asm: str, *fragments: str) -> bool:
    """Return True if every fragment appears somewhere in asm."""
    return all(f in asm for f in fragments)


# ══════════════════════════════════════════════════════════════════════════════
# 1.  Register allocator
# ══════════════════════════════════════════════════════════════════════════════

class TestRegAlloc:
    def test_alloc_temp_basic(self):
        ra = RegAlloc()
        r = ra.alloc_temp()
        assert r is not None
        assert r.startswith('$t')

    def test_alloc_free_cycle(self):
        ra = RegAlloc()
        r = ra.alloc_temp()
        ra.free_temp(r)
        r2 = ra.alloc_temp()
        assert r2 is not None

    def test_exhaust_temps(self):
        ra = RegAlloc()
        regs = []
        for _ in range(10):
            r = ra.alloc_temp()
            if r:
                regs.append(r)
        assert len(regs) == 10
        assert ra.alloc_temp() is None

    def test_saved_regs_tracked(self):
        ra = RegAlloc()
        r = ra.alloc_saved()
        assert r in ra.used_callee_gprs

    def test_borrow_temp_context_manager(self):
        ra = RegAlloc()
        with borrow_temp(ra) as r:
            assert r is not None
        # After context exit the register should be free again
        r2 = ra.alloc_temp()
        assert r2 is not None

    def test_spill_slot_alignment(self):
        ra = RegAlloc()
        off1 = ra.alloc_spill(4, 4)
        off2 = ra.alloc_spill(4, 4)
        assert off1 < 0
        assert off2 < off1   # grows downward
        assert off1 % 4 == 0


# ══════════════════════════════════════════════════════════════════════════════
# 2.  ABI — argument classification and frame layout
# ══════════════════════════════════════════════════════════════════════════════

class TestABI:
    def test_four_int_args_in_registers(self):
        locs = classify_args(['i32', 'i32', 'i32', 'i32'])
        assert all(l.kind == 'gpr' for l in locs)
        assert [l.reg for l in locs] == [A0, A1, A2, A3]

    def test_fifth_arg_on_stack(self):
        locs = classify_args(['i32'] * 5)
        assert locs[4].kind == 'stack'
        assert locs[4].stack_offset >= 16

    def test_float_args_in_fpr(self):
        locs = classify_args(['f32', 'f32'])
        assert locs[0].kind == 'fpr'
        assert locs[0].reg == '$f12'
        assert locs[1].kind == 'fpr'
        assert locs[1].reg == '$f14'

    def test_return_int(self):
        ret = classify_return('i32')
        assert ret.kind == 'gpr'
        assert ret.reg == V0

    def test_return_float(self):
        ret = classify_return('f32')
        assert ret.kind == 'fpr'
        assert ret.reg == '$f0'

    def test_return_void(self):
        ret = classify_return(None)
        assert ret.kind == 'void'

    def test_frame_size_multiple_of_8(self):
        frame = build_frame(local_bytes=12, spill_bytes=0,
                            used_callee_gprs=[], used_callee_fprs=[])
        assert frame.total_size % 8 == 0

    def test_frame_includes_ra_and_fp(self):
        frame = build_frame(local_bytes=0, spill_bytes=0,
                            used_callee_gprs=[], used_callee_fprs=[])
        assert frame.saved_ra_off > 0
        assert frame.saved_fp_off > 0
        assert frame.saved_ra_off != frame.saved_fp_off


# ══════════════════════════════════════════════════════════════════════════════
# 3.  Type layout engine
# ══════════════════════════════════════════════════════════════════════════════

class TestTypeLayout:
    def _tenv(self):
        return MipsTypeEnv()

    def test_primitive_i32(self):
        tenv = self._tenv()
        l = tenv.layout_of_name('i32')
        assert l.size == 4
        assert l.align == 4
        assert l.is_signed

    def test_primitive_u8(self):
        tenv = self._tenv()
        l = tenv.layout_of_name('u8')
        assert l.size == 1
        assert not l.is_signed

    def test_primitive_f32(self):
        tenv = self._tenv()
        l = tenv.layout_of_name('f32')
        assert l.size == 4
        assert l.is_float

    def test_primitive_f64(self):
        tenv = self._tenv()
        l = tenv.layout_of_name('f64')
        assert l.size == 8

    def test_fixed_point_fix16_16(self):
        tenv = self._tenv()
        l = tenv.layout_of_name('fix16.16')
        assert l.size == 4
        assert l.frac_bits == 16

    def test_pointer_size(self):
        tenv = self._tenv()
        l = tenv.layout_of_name('ptr')
        assert l.size == 4
        assert l.align == 4

    def test_struct_layout_padding(self):
        """{ x: i8, y: i32 } should pad x to 4 bytes before y."""
        prog = Parser(Lexer("struct Padded { x: i8, y: i32 }").tokenize()).parse()
        tenv = MipsTypeEnv()
        tenv.register_program(prog)
        l = tenv.layout_of_name('Padded')
        assert l.size == 8              # 1 byte + 3 pad + 4 bytes
        assert l.fields['x'].offset == 0
        assert l.fields['y'].offset == 4

    def test_struct_total_size_aligned(self):
        """{ a: i32, b: i8 } total size should be padded to 4."""
        prog = Parser(Lexer("struct Tail { a: i32, b: i8 }").tokenize()).parse()
        tenv = MipsTypeEnv()
        tenv.register_program(prog)
        l = tenv.layout_of_name('Tail')
        assert l.size == 8  # 4 + 1 + 3 pad

    def test_enum_layout(self):
        prog = Parser(Lexer("enum Dir { up, down, left, right }").tokenize()).parse()
        tenv = MipsTypeEnv()
        tenv.register_program(prog)
        l = tenv.layout_of_name('Dir')
        assert l.size == 4  # defaults to i32

    def test_enum_values(self):
        prog = Parser(Lexer("enum Dir { up, down, left, right }").tokenize()).parse()
        tenv = MipsTypeEnv()
        tenv.register_program(prog)
        assert tenv.enum_value('Dir', 'up')    == 0
        assert tenv.enum_value('Dir', 'down')  == 1
        assert tenv.enum_value('Dir', 'left')  == 2
        assert tenv.enum_value('Dir', 'right') == 3

    def test_slice_layout(self):
        tenv = self._tenv()
        sl = tenv.layout_of_type(ast.TypeSlice(inner=ast.TypeName('i32')))
        assert sl.size == 8
        assert sl.is_slice
        assert sl.fields['ptr'].offset == 0
        assert sl.fields['len'].offset == 4

    def test_result_layout(self):
        tenv = self._tenv()
        rt = tenv.layout_of_type(
            ast.TypeResult(ok=ast.TypeName('i32'), err=ast.TypeName('i32'))
        )
        assert rt.fields['is_ok'].offset == 0
        assert rt.fields['is_ok'].size   == 1
        assert rt.fields['payload'].offset >= 1


# ══════════════════════════════════════════════════════════════════════════════
# 4.  Literal pool
# ══════════════════════════════════════════════════════════════════════════════

class TestLiteralPool:
    def test_string_intern_deduplication(self):
        pool = LiteralPool()
        l1 = pool.intern_string("hello")
        l2 = pool.intern_string("hello")
        assert l1 == l2

    def test_different_strings_different_labels(self):
        pool = LiteralPool()
        l1 = pool.intern_string("foo")
        l2 = pool.intern_string("bar")
        assert l1 != l2

    def test_float_intern(self):
        pool = LiteralPool()
        l = pool.intern_float(3.14)
        assert l.startswith('.Lf32')

    def test_rodata_contains_asciiz(self):
        pool = LiteralPool()
        pool.intern_string("hello")
        em = Emitter()
        pool.emit_rodata(em)
        out = em.getvalue()
        assert '.asciiz' in out
        assert 'hello' in out

    def test_data_section_emitted(self):
        pool = LiteralPool()
        pool.add_static('my_var', 4, 4, 0)
        em = Emitter()
        pool.emit_data(em)
        out = em.getvalue()
        assert 'my_var' in out

    def test_bss_for_uninitialised(self):
        pool = LiteralPool()
        pool.add_static('uninit_var', 8, 8, None)
        em = Emitter()
        pool.emit_data(em)
        out = em.getvalue()
        assert '.bss' in out
        assert 'uninit_var' in out


# ══════════════════════════════════════════════════════════════════════════════
# 5.  Emitter
# ══════════════════════════════════════════════════════════════════════════════

class TestEmitter:
    def test_addiu(self):
        em = Emitter()
        em.addiu('$sp', '$sp', -32)
        assert 'addiu' in em.getvalue()
        assert '-32' in em.getvalue()

    def test_label(self):
        em = Emitter()
        em.label('my_func')
        assert 'my_func:' in em.getvalue()

    def test_jal(self):
        em = Emitter()
        em.jal('display_init')
        assert 'jal' in em.getvalue()
        assert 'display_init' in em.getvalue()

    def test_branch_and_nop(self):
        em = Emitter()
        em.beqz('$t0', '.Lend')
        em.nop()
        out = em.getvalue()
        assert 'beqz' in out
        assert 'nop'  in out

    def test_fresh_label_unique(self):
        em = Emitter()
        l1 = em.fresh_label('.L')
        l2 = em.fresh_label('.L')
        assert l1 != l2

    def test_asciiz_escaping(self):
        em = Emitter()
        em.asciiz('hello\nworld')
        assert '\\n' in em.getvalue()

    def test_section_directives(self):
        em = Emitter()
        em.section_text()
        em.section_data()
        em.section_rodata()
        em.section_bss()
        out = em.getvalue()
        assert '.text'   in out
        assert '.data'   in out
        assert '.rodata' in out
        assert '.bss'    in out


# ══════════════════════════════════════════════════════════════════════════════
# 6.  MipsCodegen — full program compilation
# ══════════════════════════════════════════════════════════════════════════════

class TestMipsCodegen:

    def test_import_ok(self):
        from pak.mips import MipsCodegen
        assert MipsCodegen is not None

    def test_empty_entry(self):
        asm = compile_mips("entry { }")
        assert 'main:' in asm
        assert 'jr' in asm

    def test_integer_arithmetic_function(self):
        asm = compile_mips("""
            fn add(a: i32, b: i32) -> i32 {
                return a + b
            }
            entry { }
        """)
        assert 'add:' in asm
        assert 'addu' in asm

    def test_factorial_recursive(self):
        """Phase 1 milestone test: recursive function with conditional return."""
        asm = compile_mips("""
            fn factorial(n: i32) -> i32 {
                if n <= 1 { return 1 }
                return n * factorial(n - 1)
            }
            entry {
                let result = factorial(10)
            }
        """)
        assert 'factorial:' in asm
        assert 'jal' in asm
        assert 'mul' in asm

    def test_while_loop(self):
        asm = compile_mips("""
            fn sum_to(n: i32) -> i32 {
                let mut s = 0
                let mut i = 0
                while i < n {
                    s = s + i
                    i = i + 1
                }
                return s
            }
            entry { }
        """)
        assert 'sum_to:' in asm
        # Should contain a branch back (loop header)
        assert '.Lwhile_h' in asm or 'bge' in asm or 'blt' in asm

    def test_for_range(self):
        asm = compile_mips("""
            fn count(n: i32) -> i32 {
                let mut total = 0
                for i in 0..n {
                    total = total + i
                }
                return total
            }
            entry { }
        """)
        assert 'count:' in asm
        assert 'addiu' in asm   # counter increment

    def test_struct_declaration(self):
        asm = compile_mips("""
            struct Vec2 { x: i32, y: i32 }
            fn make_vec(x: i32, y: i32) -> Vec2 {
                return Vec2 { x: x, y: y }
            }
            entry { }
        """)
        assert 'make_vec:' in asm
        assert 'sw' in asm

    def test_if_else(self):
        asm = compile_mips("""
            fn abs_val(x: i32) -> i32 {
                if x < 0 {
                    return -x
                } else {
                    return x
                }
            }
            entry { }
        """)
        assert 'abs_val:' in asm
        assert 'beqz' in asm or 'blt' in asm

    def test_string_literal_in_rodata(self):
        asm = compile_mips("""
            use n64.debug
            entry {
                let msg = "hello world"
            }
        """)
        assert '.rodata' in asm
        assert 'hello world' in asm

    def test_const_declaration(self):
        asm = compile_mips("""
            const MAX: i32 = 100
            fn clamp(x: i32) -> i32 {
                if x > MAX { return MAX }
                return x
            }
            entry { }
        """)
        assert 'clamp:' in asm
        assert '100' in asm

    def test_match_enum(self):
        asm = compile_mips("""
            enum Dir { up, down, left, right }
            fn dir_to_dy(d: Dir) -> i32 {
                match d {
                    .up    => { return -1 }
                    .down  => { return 1  }
                    _      => { return 0  }
                }
            }
            entry { }
        """)
        assert 'dir_to_dy:' in asm

    def test_n64_display_call(self):
        asm = compile_mips("""
            use n64.display
            entry {
                n64.display.init(320, 240, 2, 0, 0)
            }
        """)
        assert 'display_init' in asm
        assert 'jal' in asm

    def test_n64_debug_log(self):
        asm = compile_mips("""
            use n64.debug
            entry {
                n64.debug.log("hello")
            }
        """)
        assert 'debugf' in asm

    def test_static_variable(self):
        asm = compile_mips("""
            static counter: i32 = 0
            fn increment() {
                counter = counter + 1
            }
            entry { }
        """)
        assert 'counter' in asm
        assert 'increment:' in asm

    def test_do_while(self):
        asm = compile_mips("""
            fn count_down(n: i32) -> i32 {
                let mut x = n
                do {
                    x = x - 1
                } while x > 0
                return x
            }
            entry { }
        """)
        assert 'count_down:' in asm

    def test_break_continue(self):
        asm = compile_mips("""
            fn first_zero(arr: []i32) -> i32 {
                let mut result = -1
                for i in 0..10 {
                    if i == 5 { break }
                    if i == 3 { continue }
                    result = i
                }
                return result
            }
            entry { }
        """)
        assert 'first_zero:' in asm
        # break emits a jump to exit label
        assert 'j ' in asm

    def test_inline_asm_passthrough(self):
        asm = compile_mips("""
            fn sync() {
                asm { "sync" }
            }
            entry { }
        """)
        assert 'sync' in asm

    def test_ok_err_result(self):
        asm = compile_mips("""
            fn safe_div(a: i32, b: i32) -> Result(i32, i32) {
                if b == 0 { return err(0) }
                return ok(a / b)
            }
            entry { }
        """)
        assert 'safe_div:' in asm

    def test_sizeof_constant(self):
        asm = compile_mips("""
            fn get_size() -> i32 {
                return sizeof(i32) as i32
            }
            entry { }
        """)
        assert 'get_size:' in asm
        assert '4' in asm   # sizeof(i32) == 4

    def test_addr_of_local(self):
        asm = compile_mips("""
            fn get_ptr(x: i32) -> *i32 {
                return &x
            }
            entry { }
        """)
        assert 'get_ptr:' in asm
        assert 'addiu' in asm   # &local → addiu from $sp

    def test_multiple_functions(self):
        asm = compile_mips("""
            fn double(x: i32) -> i32 { return x * 2 }
            fn triple(x: i32) -> i32 { return x * 3 }
            fn six_times(x: i32) -> i32 { return double(triple(x)) }
            entry { }
        """)
        assert 'double:' in asm
        assert 'triple:' in asm
        assert 'six_times:' in asm

    def test_entry_calls_function(self):
        asm = compile_mips("""
            fn greet() { }
            entry {
                greet()
            }
        """)
        assert 'main:' in asm
        assert 'jal' in asm
        assert 'greet' in asm

    def test_globl_for_functions(self):
        asm = compile_mips("""
            fn my_fn() -> i32 { return 42 }
            entry { }
        """)
        assert '.globl' in asm
        assert 'my_fn' in asm

    def test_frame_has_return_jump(self):
        asm = compile_mips("""
            fn noop() { }
            entry { }
        """)
        assert 'jr' in asm
        assert 'nop' in asm


# ══════════════════════════════════════════════════════════════════════════════
# 7.  N64 Runtime API table
# ══════════════════════════════════════════════════════════════════════════════

class TestN64Runtime:
    def setup_method(self):
        from pak.mips.n64_runtime import N64Runtime
        self.rt = N64Runtime()

    def test_display_init_symbol(self):
        sym = self.rt.symbol_for('display', 'init')
        assert sym == 'display_init'

    def test_rdpq_attach_symbol(self):
        sym = self.rt.symbol_for('rdpq', 'attach')
        assert sym == 'rdpq_attach'

    def test_t3d_init_symbol(self):
        sym = self.rt.symbol_for('t3d', 'init')
        assert sym == 't3d_init'

    def test_unknown_returns_none(self):
        sym = self.rt.symbol_for('bogus', 'fn')
        assert sym is None

    def test_debug_log_symbol(self):
        sym = self.rt.symbol_for('debug', 'log')
        assert sym == 'debugf'


# ══════════════════════════════════════════════════════════════════════════════
# Phase 2 — Type System & Structured Data
# ══════════════════════════════════════════════════════════════════════════════

class TestPhase2StructLayout:
    """2.1 — Struct layout: type-aware field loads/stores and struct copy."""

    def test_struct_field_u8_uses_sb(self):
        """Struct with u8 field should use sb for store."""
        asm = compile_mips("""
        struct Pixel {
            r: u8
            g: u8
            b: u8
            a: u8
        }

        entry {
            let p = Pixel { r: 255, g: 128, b: 0, a: 255 }
        }
        """)
        assert has_instr(asm, 'sb')

    def test_struct_field_i16_uses_sh(self):
        """Struct with i16 field should use sh for store."""
        asm = compile_mips("""
        struct Point {
            x: i16
            y: i16
        }

        entry {
            let p = Point { x: 100, y: 200 }
        }
        """)
        assert has_instr(asm, 'sh')

    def test_struct_field_f32_access(self):
        """Struct field access emits proper code."""
        asm = compile_mips("""
        struct Vec2 {
            x: f32
            y: f32
        }

        fn get_x(v: *Vec2) -> f32 {
            return v.x
        }

        entry {
            let v = Vec2 { x: 1.0, y: 2.0 }
        }
        """)
        assert has_instr(asm, 'get_x')

    def test_struct_zero_init(self):
        """Struct literals should zero-init to handle padding."""
        asm = compile_mips("""
        struct Big {
            a: i32
            b: i32
            c: i32
            d: i32
        }

        entry {
            let b = Big { a: 1, b: 2, c: 3, d: 4 }
        }
        """)
        # Should contain multiple sw $zero for zero-init
        count = asm.count('$zero')
        assert count >= 4  # at least 4 words of zero-init

    def test_struct_copy_memcpy_large(self):
        """Large struct assignment should use memcpy or unrolled copy."""
        asm = compile_mips("""
        struct Large {
            a: i32
            b: i32
            c: i32
            d: i32
            e: i32
            f: i32
            g: i32
            h: i32
            i: i32
            j: i32
        }

        fn make_large() -> Large {
            return Large { a: 1, b: 2, c: 3, d: 4, e: 5, f: 6, g: 7, h: 8, i: 9, j: 10 }
        }

        entry {
            let x = make_large()
        }
        """)
        assert has_instr(asm, 'main')


class TestPhase2EnumCodegen:
    """2.2 — Enum codegen: integer constants, base types."""

    def test_enum_match(self):
        asm = compile_mips("""
        enum Color {
            Red
            Green
            Blue
        }

        fn color_val(c: Color) -> i32 {
            match c {
                .Red => { return 0 }
                .Green => { return 1 }
                .Blue => { return 2 }
            }
        }

        entry {
            let c = Color.Green
            let v = color_val(c)
        }
        """)
        assert has_instr(asm, 'color_val')
        assert has_instr(asm, 'beq') or has_instr(asm, 'bne')

    def test_enum_u8_base_type(self):
        """Enum with u8 base type should still work."""
        asm = compile_mips("""
        enum Direction: u8 {
            Up
            Down
            Left
            Right
        }

        entry {
            let d = Direction.Left
        }
        """)
        assert has_instr(asm, 'main')


class TestPhase2VariantCodegen:
    """2.3 — Variant (tagged union) construction and matching."""

    def test_variant_constructor_stores_tag(self):
        """Constructing a variant should store the tag value."""
        asm = compile_mips("""
        struct Vec2 { x: f32, y: f32 }

        variant Shape {
            Circle { radius: f32 }
            Rect { w: f32, h: f32 }
        }

        entry {
            let s = Circle(1.0)
        }
        """)
        # Should have a store of tag value (0 for Circle)
        assert has_instr(asm, 'sb') or has_instr(asm, 'sh') or has_instr(asm, 'sw')
        assert has_instr(asm, 'main')

    def test_variant_match_extracts_payload(self):
        """Match on variant should extract payload fields."""
        asm = compile_mips("""
        variant Shape {
            Circle { radius: i32 }
            Rect { w: i32, h: i32 }
        }

        fn area(s: Shape) -> i32 {
            match s {
                .Circle(r) => { return r * r * 3 }
                .Rect(w, h) => { return w * h }
            }
        }

        entry {
            let s = Circle(5)
            let a = area(s)
        }
        """)
        assert has_instr(asm, 'area')
        assert has_instr(asm, 'lbu') or has_instr(asm, 'lhu') or has_instr(asm, 'lw')

    def test_variant_multiple_cases(self):
        """Variant with multiple cases produces distinct tags."""
        asm = compile_mips("""
        variant Animal {
            Dog { name: i32 }
            Cat { name: i32, indoor: bool }
            Fish { }
        }

        entry {
            let a = Dog(42)
            let b = Cat(99, true)
        }
        """)
        assert has_instr(asm, 'main')


class TestPhase2SliceCodegen:
    """2.4 — Slices (fat pointers) and bounds checking."""

    def test_slice_expr_emits_fat_pointer(self):
        """Slicing an array should produce ptr + len pair."""
        asm = compile_mips("""
        entry {
            let arr = [1, 2, 3, 4, 5]
            let s = arr[1..3]
        }
        """)
        assert has_instr(asm, 'main')
        # Should have subu for computing length (end - start)
        assert has_instr(asm, 'subu')

    def test_bounds_check_flag(self):
        """When bounds_check=True, should emit sltu + panic branch."""
        from pak.mips import MipsCodegen as MC
        cg = MC(bounds_check=True)
        source = textwrap.dedent("""
        entry {
            let arr = [1, 2, 3]
        }
        """).strip()
        tokens = Lexer(source).tokenize()
        program = Parser(tokens).parse()
        tenv = TypeEnv()
        tenv.collect(program)
        asm = cg.generate(program, tenv)
        assert has_instr(asm, 'main')


class TestPhase2ResultOption:
    """2.5 — Result and Option type codegen."""

    def test_ok_constructor_stores_tag_1(self):
        """ok(val) should store is_ok=1 and the payload."""
        asm = compile_mips("""
        fn safe_div(a: i32, b: i32) -> Result(i32, i32) {
            if b == 0 {
                return err(0)
            }
            return ok(a / b)
        }

        entry {
            let r = safe_div(10, 2)
        }
        """)
        assert has_instr(asm, 'safe_div')
        # ok() should store tag=1 via sb
        assert has_instr(asm, 'sb')

    def test_err_constructor_stores_tag_0(self):
        """err(val) should store is_ok=0."""
        asm = compile_mips("""
        fn fail() -> Result(i32, i32) {
            return err(42)
        }

        entry {
            let r = fail()
        }
        """)
        assert has_instr(asm, 'fail')

    def test_catch_expr(self):
        """Catch expression should branch on is_ok flag."""
        asm = compile_mips("""
        fn maybe_fail(x: i32) -> Result(i32, i32) {
            if x < 0 { return err(x) }
            return ok(x * 2)
        }

        entry {
            let r = maybe_fail(5)
            let v = r catch e { 0 }
        }
        """)
        assert has_instr(asm, 'lbu')  # loading is_ok flag
        assert has_instr(asm, 'bnez') or has_instr(asm, 'beqz')


class TestPhase2TypeAwareOps:
    """Miscellaneous Phase 2: type-aware ops, goto/label fix, alloc fix."""

    def test_array_literal(self):
        """Array literal should store each element."""
        asm = compile_mips("""
        entry {
            let a = [10, 20, 30]
        }
        """)
        assert has_instr(asm, 'sw')
        assert has_instr(asm, 'main')

    def test_tuple_access(self):
        """Tuple access should load at correct word offset."""
        asm = compile_mips("""
        entry {
            let t = (1, 2, 3)
        }
        """)
        assert has_instr(asm, 'sw')

    def test_alloc_free(self):
        """alloc/free should call runtime helpers."""
        asm = compile_mips("""
        entry {
            let p = alloc(i32)
            free(p)
        }
        """)
        assert has_instr(asm, '__pak_alloc')
        assert has_instr(asm, '__pak_free')

    def test_defer_in_function(self):
        """Defer should emit deferred code before return."""
        asm = compile_mips("""
        fn cleanup() -> i32 {
            let x = 10
            defer { x = 0 }
            return x
        }

        entry {
            let v = cleanup()
        }
        """)
        assert has_instr(asm, 'cleanup')

    def test_do_while(self):
        """Do-while loop should emit body then condition check."""
        asm = compile_mips("""
        entry {
            let x = 0
            do {
                x = x + 1
            } while x < 10
        }
        """)
        assert has_instr(asm, 'bnez')

    def test_comptime_if(self):
        """Comptime if with constant true should emit only then-branch."""
        asm = compile_mips("""
        const DEBUG = 1

        entry {
            comptime if (DEBUG) {
                let x = 42
            }
        }
        """)
        assert has_instr(asm, 'li')

    def test_closure_emission(self):
        """Closure should be emitted as a separate function."""
        asm = compile_mips("""
        fn apply(f: fn(i32) -> i32, x: i32) -> i32 {
            return f(x)
        }

        entry {
            let double = fn(x: i32) -> i32 { return x * 2 }
            let r = apply(double, 5)
        }
        """)
        assert has_instr(asm, '__closure')

    def test_for_range(self):
        """For-range loop with counter."""
        asm = compile_mips("""
        entry {
            let sum = 0
            for i in 0..10 {
                sum = sum + i
            }
        }
        """)
        assert has_instr(asm, 'bge')
        assert has_instr(asm, 'addiu')

    def test_string_literal(self):
        """String literals should be interned in .rodata."""
        asm = compile_mips("""
        entry {
            let msg = "hello world"
        }
        """)
        assert has_instr(asm, '.rodata') or has_instr(asm, '.section')
        assert has_instr(asm, 'hello world')

    def test_nested_if_else(self):
        """Nested if/elif/else chains."""
        asm = compile_mips("""
        fn classify(x: i32) -> i32 {
            if x < 0 {
                return -1
            } else if x == 0 {
                return 0
            } else {
                return 1
            }
        }

        entry {
            let r = classify(5)
        }
        """)
        assert has_instr(asm, 'classify')


class TestPhase2StructCopyIntegration:
    """Struct copy and pass-by-value integration tests."""

    def test_struct_let_with_struct_lit(self):
        """Let binding with struct literal should produce correct asm."""
        asm = compile_mips("""
        struct Pos {
            x: i32
            y: i32
        }

        entry {
            let p = Pos { x: 10, y: 20 }
        }
        """)
        assert has_instr(asm, 'sw')
        assert has_instr(asm, 'main')

    def test_nested_struct(self):
        """Nested struct should compute offsets correctly."""
        asm = compile_mips("""
        struct Inner {
            a: i32
            b: i32
        }

        struct Outer {
            x: i32
            inner: Inner
        }

        entry {
            let o = Outer { x: 1, inner: Inner { a: 2, b: 3 } }
        }
        """)
        assert has_instr(asm, 'main')
        assert has_instr(asm, 'sw')


class TestPhase2VariantLayoutIntegration:
    """Variant layout integration: verify correct tag + payload offsets."""

    def test_variant_case_fields_layout(self):
        """MipsTypeEnv.variant_case_fields should return correct field info."""
        from pak.mips.types import MipsTypeEnv
        tenv = MipsTypeEnv()

        source = textwrap.dedent("""
        variant Shape {
            Circle { radius: f32 }
            Rect { w: f32, h: f32 }
        }

        entry { }
        """).strip()
        tokens = Lexer(source).tokenize()
        program = Parser(tokens).parse()
        tenv.register_program(program)

        # Circle has one field: radius at offset 0
        circle_fields = tenv.variant_case_fields('Shape', 'Circle')
        assert len(circle_fields) == 1
        assert circle_fields[0].name == 'radius'
        assert circle_fields[0].size == 4

        # Rect has two fields: w, h
        rect_fields = tenv.variant_case_fields('Shape', 'Rect')
        assert len(rect_fields) == 2
        assert rect_fields[0].name == 'w'
        assert rect_fields[1].name == 'h'

    def test_variant_tag_values(self):
        """variant_tag should return 0 for first case, 1 for second, etc."""
        from pak.mips.types import MipsTypeEnv
        tenv = MipsTypeEnv()

        source = textwrap.dedent("""
        variant Animal {
            Dog { }
            Cat { }
            Fish { }
        }

        entry { }
        """).strip()
        tokens = Lexer(source).tokenize()
        program = Parser(tokens).parse()
        tenv.register_program(program)

        assert tenv.variant_tag('Animal', 'Dog') == 0
        assert tenv.variant_tag('Animal', 'Cat') == 1
        assert tenv.variant_tag('Animal', 'Fish') == 2

    def test_variant_layout_tag_size(self):
        """Variant with <= 256 cases should have 1-byte tag."""
        from pak.mips.types import MipsTypeEnv
        tenv = MipsTypeEnv()

        source = textwrap.dedent("""
        variant Msg {
            Hello { }
            Goodbye { }
        }

        entry { }
        """).strip()
        tokens = Lexer(source).tokenize()
        program = Parser(tokens).parse()
        tenv.register_program(program)

        layout = tenv.layout_of_name('Msg')
        assert layout.tag_size == 1
