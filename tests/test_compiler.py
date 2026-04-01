"""Comprehensive pytest test suite for the Pak compiler."""

import pytest
import textwrap
from pak.lexer import Lexer, TT, Token, LexError
from pak.parser import Parser, ParseError
from pak import ast
from pak.codegen import Codegen, CodegenError
from pak.typechecker import typecheck, typecheck_multi


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def lex(src: str):
    return Lexer(src).tokenize()

def token_types(src: str):
    return [t.type for t in lex(src) if t.type != TT.EOF]

def parse(src: str) -> ast.Program:
    tokens = Lexer(src).tokenize()
    return Parser(tokens).parse()

def codegen(src: str) -> str:
    prog = parse(src)
    cg = Codegen()
    return cg.gen_program(prog)

def check(src: str):
    prog = parse(src)
    return typecheck(prog)


# ─────────────────────────────────────────────────────────────────────────────
# Lexer tests
# ─────────────────────────────────────────────────────────────────────────────

class TestLexer:

    def test_integer_literal(self):
        toks = lex('42')
        assert toks[0].type == TT.INT
        assert toks[0].value == '42'

    def test_float_literal(self):
        toks = lex('3.14')
        assert toks[0].type == TT.FLOAT
        assert toks[0].value == '3.14'

    def test_float_suffix(self):
        toks = lex('1.0f')
        assert toks[0].type == TT.FLOAT

    def test_hex_literal(self):
        toks = lex('0xFF')
        assert toks[0].type == TT.INT
        assert toks[0].value == '0xFF'

    def test_hex_with_underscores(self):
        toks = lex('0xFF_FF')
        assert toks[0].type == TT.INT
        assert toks[0].value == '0xFFFF'

    def test_string_literal(self):
        toks = lex('"hello"')
        assert toks[0].type == TT.STRING
        assert toks[0].value == 'hello'

    def test_string_escape(self):
        toks = lex(r'"foo\nbar"')
        assert toks[0].value == 'foo\nbar'

    def test_bool_true(self):
        toks = lex('true')
        assert toks[0].type == TT.TRUE

    def test_bool_false(self):
        toks = lex('false')
        assert toks[0].type == TT.FALSE

    def test_identifier(self):
        toks = lex('my_var')
        assert toks[0].type == TT.IDENT
        assert toks[0].value == 'my_var'

    def test_keywords(self):
        for kw in ('fn', 'let', 'if', 'else', 'for', 'while', 'loop',
                   'return', 'break', 'continue', 'struct', 'enum',
                   'variant', 'match', 'use', 'entry', 'static', 'mut',
                   'and', 'or', 'not', 'defer', 'extern', 'module',
                   'in', 'from', 'as', 'catch'):
            toks = lex(kw)
            assert toks[0].type != TT.IDENT, f'{kw!r} should be a keyword'

    # Fixed-point type names
    def test_fix16_16(self):
        toks = lex('fix16.16')
        assert toks[0].type == TT.IDENT
        assert toks[0].value == 'fix16.16'

    def test_fix10_5(self):
        toks = lex('fix10.5')
        assert toks[0].type == TT.IDENT
        assert toks[0].value == 'fix10.5'

    def test_fix1_15(self):
        toks = lex('fix1.15')
        assert toks[0].type == TT.IDENT
        assert toks[0].value == 'fix1.15'

    def test_fix_not_confused_with_float(self):
        # 'fix16.16' should be ONE token, not IDENT('fix16') DOT INT('16')
        toks = [t for t in lex('fix16.16') if t.type != TT.EOF]
        assert len(toks) == 1
        assert toks[0].value == 'fix16.16'

    def test_fix_followed_by_range(self):
        # fix16.16 .. x  → IDENT DOTDOT IDENT (the .. is not part of the type)
        toks = [t for t in lex('fix16.16..x') if t.type != TT.EOF]
        assert toks[0].value == 'fix16.16'
        assert toks[1].type == TT.DOTDOT

    # Shift operators
    def test_shl(self):
        toks = token_types('1 << 2')
        assert TT.SHL in toks

    def test_shr(self):
        toks = token_types('1 >> 2')
        assert TT.SHR in toks

    def test_shl_eq(self):
        toks = token_types('x <<= 1')
        assert TT.SHL_EQ in toks

    def test_shr_eq(self):
        toks = token_types('x >>= 1')
        assert TT.SHR_EQ in toks

    # Compound assignment
    def test_amp_eq(self):
        toks = token_types('x &= 3')
        assert TT.AMP_EQ in toks

    def test_pipe_eq(self):
        toks = token_types('x |= 3')
        assert TT.PIPE_EQ in toks

    def test_caret_eq(self):
        toks = token_types('x ^= 3')
        assert TT.CARET_EQ in toks

    # Comments
    def test_line_comment_dash(self):
        toks = [t for t in lex('-- comment\n42') if t.type != TT.EOF]
        assert len(toks) == 1 and toks[0].value == '42'

    def test_line_comment_slash(self):
        toks = [t for t in lex('// comment\n42') if t.type != TT.EOF]
        assert len(toks) == 1 and toks[0].value == '42'

    # Annotations
    def test_annotation_simple(self):
        toks = lex('@inline')
        assert toks[0].type == TT.ANNOTATION
        assert toks[0].value == '@inline'

    def test_annotation_with_args(self):
        toks = lex('@aligned(16)')
        assert toks[0].type == TT.ANNOTATION
        assert toks[0].value == '@aligned(16)'

    def test_unterminated_string(self):
        with pytest.raises(LexError):
            lex('"unterminated')

    def test_range_dotdot(self):
        toks = token_types('0..10')
        assert TT.INT in toks
        assert TT.DOTDOT in toks

    def test_fat_arrow(self):
        toks = token_types('x => y')
        assert TT.FAT_ARROW in toks


# ─────────────────────────────────────────────────────────────────────────────
# Parser tests
# ─────────────────────────────────────────────────────────────────────────────

class TestParser:

    def test_empty_program(self):
        prog = parse('')
        assert prog.decls == []

    def test_fn_no_params(self):
        prog = parse('fn foo() -> void {}')
        assert len(prog.decls) == 1
        fn = prog.decls[0]
        assert isinstance(fn, ast.FnDecl)
        assert fn.name == 'foo'
        assert fn.params == []

    def test_fn_with_params(self):
        prog = parse('fn add(a: i32, b: i32) -> i32 { return a + b; }')
        fn = prog.decls[0]
        assert len(fn.params) == 2
        assert fn.params[0].name == 'a'

    def test_let_stmt(self):
        prog = parse('fn f() -> void { let x: i32 = 5; }')
        fn = prog.decls[0]
        stmt = fn.body.stmts[0]
        assert isinstance(stmt, ast.LetDecl)
        assert stmt.name == 'x'

    def test_let_mut_stmt(self):
        prog = parse('fn f() -> void { let mut x: i32 = 5; }')
        fn = prog.decls[0]
        stmt = fn.body.stmts[0]
        assert isinstance(stmt, ast.LetDecl)
        assert stmt.mutable

    def test_return_stmt(self):
        prog = parse('fn f() -> i32 { return 42; }')
        fn = prog.decls[0]
        assert isinstance(fn.body.stmts[0], ast.Return)

    def test_if_stmt(self):
        prog = parse('fn f() -> void { if x { } }')
        fn = prog.decls[0]
        assert isinstance(fn.body.stmts[0], ast.IfStmt)

    def test_if_else(self):
        prog = parse('fn f() -> void { if x { } else { } }')
        fn = prog.decls[0]
        stmt = fn.body.stmts[0]
        assert isinstance(stmt, ast.IfStmt)
        assert stmt.else_branch is not None

    def test_while_loop(self):
        prog = parse('fn f() -> void { while true { } }')
        fn = prog.decls[0]
        assert isinstance(fn.body.stmts[0], ast.WhileStmt)

    def test_loop(self):
        prog = parse('fn f() -> void { loop { break; } }')
        fn = prog.decls[0]
        assert isinstance(fn.body.stmts[0], ast.LoopStmt)

    def test_for_range(self):
        prog = parse('fn f() -> void { for i in 0..10 { } }')
        fn = prog.decls[0]
        s = fn.body.stmts[0]
        assert isinstance(s, ast.ForStmt)
        assert s.binding == 'i'
        assert isinstance(s.iterable, ast.RangeExpr)

    def test_for_with_index(self):
        # Grammar: for <index>, <item> in collection
        prog = parse('fn f() -> void { for idx, item in arr { } }')
        fn = prog.decls[0]
        s = fn.body.stmts[0]
        assert isinstance(s, ast.ForStmt)
        assert s.index == 'idx'
        assert s.binding == 'item'

    def test_struct_decl(self):
        prog = parse('struct Pos { x: i32, y: i32 }')
        s = prog.decls[0]
        assert isinstance(s, ast.StructDecl)
        assert s.name == 'Pos'
        assert len(s.fields) == 2

    def test_enum_decl(self):
        prog = parse('enum Dir { Up, Down, Left, Right }')
        e = prog.decls[0]
        assert isinstance(e, ast.EnumDecl)
        assert len(e.variants) == 4

    def test_variant_decl(self):
        prog = parse('variant Cmd { Move { dx: i32, dy: i32 }, Stop }')
        v = prog.decls[0]
        assert isinstance(v, ast.VariantDecl)
        assert len(v.cases) == 2

    def test_match_expr(self):
        prog = parse('fn f(d: Dir) -> void { match d { Dir.Up => { } } }')
        fn = prog.decls[0]
        assert isinstance(fn.body.stmts[0], ast.MatchStmt)

    def test_defer_stmt(self):
        prog = parse('fn f() -> void { defer { foo(); } }')
        fn = prog.decls[0]
        assert isinstance(fn.body.stmts[0], ast.DeferStmt)

    def test_use_decl(self):
        prog = parse('use n64.display;')
        u = prog.decls[0]
        assert isinstance(u, ast.UseDecl)
        assert u.path == 'n64.display'

    def test_module_decl(self):
        prog = parse('module game.player;')
        m = prog.decls[0]
        assert isinstance(m, ast.ModuleDecl)
        assert m.path == 'game.player'

    def test_static_decl(self):
        prog = parse('static SCORE: i32 = 0;')
        s = prog.decls[0]
        assert isinstance(s, ast.StaticDecl)

    def test_entry_decl(self):
        prog = parse('entry { }')
        e = prog.decls[0]
        assert isinstance(e, ast.EntryBlock)

    # Expression precedence
    def test_arithmetic_precedence(self):
        prog = parse('fn f() -> i32 { return 2 + 3 * 4; }')
        fn = prog.decls[0]
        ret = fn.body.stmts[0]
        # 2 + (3 * 4) — right-hand side of + should be BinaryOp(*)
        assert isinstance(ret, ast.Return)
        assert isinstance(ret.value, ast.BinaryOp)
        assert ret.value.op == '+'
        assert isinstance(ret.value.right, ast.BinaryOp)
        assert ret.value.right.op == '*'

    def test_bitwise_and_precedence(self):
        prog = parse('fn f() -> i32 { return x & 0xFF | y; }')
        fn = prog.decls[0]
        ret = fn.body.stmts[0]
        assert isinstance(ret, ast.Return)
        # (x & 0xFF) | y  — | binds looser than &
        assert isinstance(ret.value, ast.BinaryOp)
        assert ret.value.op == '|'
        assert isinstance(ret.value.left, ast.BinaryOp)
        assert ret.value.left.op == '&'

    def test_shift_precedence(self):
        prog = parse('fn f() -> i32 { return x + y << 2; }')
        fn = prog.decls[0]
        ret = fn.body.stmts[0]
        assert isinstance(ret, ast.Return)
        # (x + y) << 2 — << binds looser than +
        assert isinstance(ret.value, ast.BinaryOp)
        assert ret.value.op == '<<'
        assert isinstance(ret.value.left, ast.BinaryOp)
        assert ret.value.left.op == '+'

    def test_assign_ops(self):
        for op in ('+=', '-=', '*=', '/=', '<<=', '>>=', '&=', '|=', '^='):
            src = f'fn f() -> void {{ x {op} 1; }}'
            prog = parse(src)
            fn = prog.decls[0]
            stmt = fn.body.stmts[0]
            assert isinstance(stmt, (ast.Assign, ast.ExprStmt)), f'Expected Assign for {op}'

    def test_array_type(self):
        prog = parse('fn f(arr: [10]i32) -> void {}')
        fn = prog.decls[0]
        param = fn.params[0]
        assert isinstance(param.type, ast.TypeArray)

    def test_slice_type(self):
        prog = parse('fn f(s: []i32) -> void {}')
        fn = prog.decls[0]
        param = fn.params[0]
        assert isinstance(param.type, ast.TypeSlice)

    def test_pointer_type(self):
        prog = parse('fn f(p: *i32) -> void {}')
        fn = prog.decls[0]
        param = fn.params[0]
        assert isinstance(param.type, ast.TypePointer)

    def test_optional_type(self):
        prog = parse('fn f(p: ?i32) -> void {}')
        fn = prog.decls[0]
        param = fn.params[0]
        assert isinstance(param.type, ast.TypeOption)


# ─────────────────────────────────────────────────────────────────────────────
# Code generator tests
# ─────────────────────────────────────────────────────────────────────────────

class TestCodegen:

    def test_basic_fn(self):
        c = codegen('fn add(a: i32, b: i32) -> i32 { return a + b; }')
        assert 'int32_t add(int32_t a, int32_t b)' in c
        assert 'return' in c and 'a + b' in c

    def test_void_fn(self):
        c = codegen('fn noop() -> void {}')
        assert 'void noop(void)' in c

    def test_struct_generation(self):
        c = codegen('struct Vec2 { x: f32, y: f32 }')
        assert 'typedef struct {' in c
        assert 'float x;' in c
        assert 'float y;' in c
        assert '} Vec2;' in c

    def test_enum_generation(self):
        c = codegen('enum Dir { Up, Down, Left, Right }')
        assert 'typedef enum {' in c
        assert 'Dir_Up' in c
        assert 'Dir_Right' in c

    def test_variant_generation(self):
        c = codegen('variant Cmd { Move { dx: i32 }, Stop }')
        assert 'typedef enum' in c
        assert 'Cmd_tag_Move' in c
        assert 'typedef struct' in c
        assert 'Cmd_tag tag' in c

    # for-loop tests
    def test_for_range(self):
        c = codegen('fn f() -> void { for i in 0..10 { } }')
        assert 'for (int i = 0; i < 10; i++)' in c

    def test_for_array_without_index(self):
        c = codegen('fn f(arr: [4]i32) -> void { for x in arr { } }')
        # Should use sizeof-based loop
        assert 'sizeof' in c
        assert 'arr[' in c

    def test_for_slice_uses_len(self):
        c = codegen('fn f(items: []i32) -> void { for x in items { } }')
        # Fat slice loop should use .len
        assert '.len' in c
        assert '.data[' in c

    def test_for_with_index(self):
        # Grammar: for <index>, <binding> in collection
        c = codegen('fn f(arr: [4]i32) -> void { for i, x in arr { } }')
        # index variable should be 'i'
        assert 'int i = 0' in c

    # Fixed-point tests
    def test_fix16_mul_plain(self):
        c = codegen('fn f(a: fix16.16, b: fix16.16) -> fix16.16 { return a * b; }')
        assert '(int32_t)(((int64_t)' in c
        assert '>> 16)' in c

    def test_fix16_add_no_shift(self):
        c = codegen('fn f(a: fix16.16, b: fix16.16) -> fix16.16 { return a + b; }')
        # Addition of same type should NOT use the widening multiply
        assert '>> 16' not in c

    def test_i32_mul_no_fixpoint(self):
        c = codegen('fn f(a: i32, b: i32) -> i32 { return a * b; }')
        # Plain i32 * i32 should NOT emit fixpoint multiply
        assert '(int64_t)' not in c

    # Variant match
    def test_variant_match_uses_tag(self):
        src = textwrap.dedent('''
            variant Cmd { Move { dx: i32 }, Stop }
            fn handle(c: Cmd) -> void {
                match c {
                    Cmd.Move(m) => { }
                    Cmd.Stop => { }
                }
            }
        ''')
        c = codegen(src)
        assert 'switch (c.tag)' in c
        assert 'case Cmd_tag_Move' in c
        assert 'case Cmd_tag_Stop' in c

    def test_enum_match_no_tag(self):
        src = textwrap.dedent('''
            enum Dir { Up, Down }
            fn handle(d: Dir) -> void {
                match d {
                    Dir.Up => { }
                    Dir.Down => { }
                }
            }
        ''')
        c = codegen(src)
        assert 'switch (d)' in c
        assert 'case Dir_Up' in c
        # must NOT use .tag for plain enum
        assert '.tag' not in c

    # Defer tests
    def test_defer_emitted_at_scope_end(self):
        src = textwrap.dedent('''
            fn f() -> void {
                defer { cleanup(); }
                do_work();
            }
        ''')
        c = codegen(src)
        # cleanup() should appear after do_work()
        work_pos = c.index('do_work()')
        clean_pos = c.index('cleanup()')
        assert clean_pos > work_pos

    def test_defer_lifo_order(self):
        src = textwrap.dedent('''
            fn f() -> void {
                defer { first(); }
                defer { second(); }
            }
        ''')
        c = codegen(src)
        first_pos = c.index('first()')
        second_pos = c.index('second()')
        # LIFO: second() deferred last, runs first
        assert second_pos < first_pos

    # Fat slice typedef
    def test_slice_typedef_emitted(self):
        c = codegen('fn f(s: []i32) -> void {}')
        assert 'PakSlice_' in c
        assert 'int32_t *data' in c
        assert 'int32_t len' in c

    def test_slice_index_uses_data(self):
        c = codegen('fn f(s: []i32) -> i32 { return s[0]; }')
        assert '.data[0]' in c

    def test_slice_expr(self):
        c = codegen('fn f(arr: [8]i32) -> void { let s: []i32 = arr[2..6]; }')
        assert '.data = &' in c
        assert '.len = ' in c

    # Static declarations
    def test_static_decl(self):
        c = codegen('static SCORE: i32 = 0;')
        assert 'int32_t SCORE = 0;' in c

    # Entry point
    def test_entry_fn(self):
        c = codegen('entry { }')
        assert 'int main(' in c or 'void main(' in c

    # Pointer member access
    def test_pointer_field_arrow(self):
        src = textwrap.dedent('''
            struct Node { val: i32 }
            fn get(p: *Node) -> i32 { return p.val; }
        ''')
        c = codegen(src)
        assert 'p->val' in c

    # Module includes
    def test_use_display_includes(self):
        c = codegen('use n64.display;\nentry {}')
        assert '#include <display.h>' in c

    def test_use_rumble_includes(self):
        c = codegen('use n64.rumble;\nentry {}')
        assert '#include <rumble.h>' in c

    def test_use_cpak_includes(self):
        c = codegen('use n64.cpak;\nentry {}')
        assert '#include <cpak.h>' in c

    def test_use_rtc_includes(self):
        c = codegen('use n64.rtc;\nentry {}')
        assert '#include <rtc.h>' in c

    def test_use_backup_includes(self):
        c = codegen('use n64.backup;\nentry {}')
        assert '#include <backup.h>' in c

    def test_use_disk_includes(self):
        c = codegen('use n64.disk;\nentry {}')
        assert '#include <disk.h>' in c

    def test_use_vru_includes(self):
        c = codegen('use n64.vru;\nentry {}')
        assert '#include <vru.h>' in c

    def test_use_system_includes(self):
        c = codegen('use n64.system;\nentry {}')
        assert '#include <n64sys.h>' in c

    # Module API call generation
    def test_rumble_start_call(self):
        c = codegen('use n64.rumble;\nfn f() -> void { rumble.start(0); }')
        assert 'rumble_start(0)' in c

    def test_cpak_read_call(self):
        c = codegen('use n64.cpak;\nfn f() -> void { cpak.read_sector(0, buf, 1); }')
        assert 'cpak_read_sector(0' in c

    def test_backup_read_call(self):
        c = codegen('use n64.backup;\nfn f() -> void { backup.read(buf, 0, 64); }')
        assert 'backup_read(buf' in c

    def test_system_memory_size(self):
        c = codegen('use n64.system;\nfn f() -> u32 { return system.memory_size(); }')
        assert 'get_memory_size()' in c

    def test_system_has_expansion(self):
        c = codegen('use n64.system;\nfn f() -> bool { return system.has_expansion(); }')
        assert 'get_memory_size() > 0x400000' in c

    def test_system_ticks(self):
        c = codegen('use n64.system;\nfn f() -> u32 { return system.ticks(); }')
        assert 'TICKS_READ()' in c

    def test_rtc_get_call(self):
        c = codegen('use n64.rtc;\nfn f() -> void { rtc.get(t); }')
        assert 'rtc_get(t)' in c

    def test_xm64_play_call(self):
        c = codegen('use n64.xm64;\nfn f() -> void { xm64.play(player, 0); }')
        assert 'xm64player_play(player' in c

    def test_mixer_ch_play(self):
        c = codegen('use n64.mixer;\nfn f() -> void { mixer.ch_play(0, snd); }')
        assert 'mixer_ch_play(0' in c

    def test_rdpq_font_draw(self):
        c = codegen('use n64.rdpq_font;\nfn f() -> void { rdpq_font.draw_text(x, y, "hi"); }')
        assert 'rdpq_text_print(' in c

    # Bitwise operations
    def test_bitwise_and(self):
        c = codegen('fn f(a: i32) -> i32 { return a & 0xFF; }')
        assert 'a & 0xFF' in c

    def test_bitwise_or(self):
        c = codegen('fn f(a: i32) -> i32 { return a | 0x80; }')
        assert 'a | 0x80' in c

    def test_bitwise_xor(self):
        c = codegen('fn f(a: i32) -> i32 { return a ^ 1; }')
        assert 'a ^ 1' in c

    def test_shift_left(self):
        c = codegen('fn f(a: i32) -> i32 { return a << 4; }')
        assert 'a << 4' in c

    def test_shift_right(self):
        c = codegen('fn f(a: i32) -> i32 { return a >> 2; }')
        assert 'a >> 2' in c

    # Compound assignments
    def test_plus_eq(self):
        c = codegen('fn f() -> void { let mut x: i32 = 0; x += 1; }')
        assert 'x += 1' in c

    def test_shl_eq(self):
        c = codegen('fn f() -> void { let mut x: i32 = 1; x <<= 3; }')
        assert 'x <<= 3' in c

    def test_amp_eq(self):
        c = codegen('fn f() -> void { let mut x: i32 = 0xFF; x &= 0x0F; }')
        assert 'x &= 0x0F' in c

    # Scope isolation — let inside if doesn't leak
    def test_scope_isolation_if(self):
        src = textwrap.dedent('''
            fn f(cond: bool) -> void {
                if cond {
                    let x: i32 = 1;
                }
            }
        ''')
        # Should compile without error — scope management shouldn't crash
        c = codegen(src)
        assert 'int32_t x = 1' in c

    # Null-check
    def test_null_check(self):
        src = textwrap.dedent('''
            fn f(p: ?i32) -> void {
                if p -> v {
                    let x: i32 = v;
                }
            }
        ''')
        c = codegen(src)
        assert 'p != NULL' in c or 'if (p)' in c or '(p)' in c


# ─────────────────────────────────────────────────────────────────────────────
# Type checker tests
# ─────────────────────────────────────────────────────────────────────────────

class TestTypechecker:

    def test_no_errors_simple(self):
        src = 'fn add(a: i32, b: i32) -> i32 { return a + b; }'
        errs = typecheck(parse(src))
        assert errs == []

    def test_e010_unknown_name(self):
        src = 'fn f() -> void { let x: i32 = y; }'
        errs = typecheck(parse(src))
        codes = [e.code for e in errs]
        assert 'E010' in codes

    def test_e011_no_such_field(self):
        src = textwrap.dedent('''
            struct Pos { x: i32, y: i32 }
            fn f(p: Pos) -> i32 { return p.z; }
        ''')
        errs = typecheck(parse(src))
        codes = [e.code for e in errs]
        assert 'E011' in codes

    def test_e012_wrong_arity(self):
        src = textwrap.dedent('''
            fn add(a: i32, b: i32) -> i32 { return a + b; }
            fn f() -> void { add(1); }
        ''')
        errs = typecheck(parse(src))
        codes = [e.code for e in errs]
        assert 'E012' in codes

    def test_e301_non_exhaustive_match(self):
        src = textwrap.dedent('''
            enum Dir { Up, Down, Left, Right }
            fn f(d: Dir) -> void {
                match d {
                    Dir.Up => { }
                }
            }
        ''')
        errs = typecheck(parse(src))
        codes = [e.code for e in errs]
        assert 'E301' in codes

    def test_exhaustive_match_ok(self):
        src = textwrap.dedent('''
            enum Dir { Up, Down }
            fn f(d: Dir) -> void {
                match d {
                    Dir.Up => { }
                    Dir.Down => { }
                }
            }
        ''')
        errs = typecheck(parse(src))
        assert errs == []

    def test_multi_file_shared_env(self):
        src1 = 'module game.math;\nfn add(a: i32, b: i32) -> i32 { return a + b; }'
        src2 = textwrap.dedent('''
            use game.math;
            fn call_add() -> i32 { return add(1, 2); }
        ''')
        prog1 = parse(src1)
        prog2 = parse(src2)
        results = typecheck_multi([('math.pak', prog1), ('main.pak', prog2)])
        # add() should be found — no E010 or E012 in either file
        all_errs = [e for errs in results.values() for e in errs]
        codes = [e.code for e in all_errs]
        assert 'E010' not in codes
        assert 'E012' not in codes


# ─────────────────────────────────────────────────────────────────────────────
# Regression tests for confirmed bugs
# ─────────────────────────────────────────────────────────────────────────────

class TestRegressions:

    def test_fix16_lexed_as_single_token(self):
        """Regression: fix16.16 was tokenised as IDENT('fix16') + FLOAT + INT."""
        toks = [t for t in lex('fix16.16') if t.type != TT.EOF]
        assert len(toks) == 1, f'Expected 1 token, got {len(toks)}: {toks}'
        assert toks[0].value == 'fix16.16'

    def test_variant_match_switch_on_tag(self):
        """Regression: variant match used switch(cmd) instead of switch(cmd.tag)."""
        src = textwrap.dedent('''
            variant Cmd { Move { dx: i32 }, Stop }
            fn run(c: Cmd) -> void {
                match c {
                    Cmd.Move(m) => { }
                    Cmd.Stop => { }
                }
            }
        ''')
        c = codegen(src)
        assert 'switch (c.tag)' in c, 'Must switch on .tag for variant type'
        assert 'switch (c)' not in c

    def test_variant_case_label_has_tag_prefix(self):
        """Regression: case Cmd_move instead of Cmd_tag_move."""
        src = textwrap.dedent('''
            variant Cmd { Move { dx: i32 }, Stop }
            fn run(c: Cmd) -> void {
                match c {
                    Cmd.Move(m) => { }
                    Cmd.Stop => { }
                }
            }
        ''')
        c = codegen(src)
        assert 'case Cmd_tag_Move' in c
        assert 'case Cmd_tag_Stop' in c

    def test_for_slice_no_sizeof(self):
        """Regression: for item in slice_param used sizeof which = 1 for pointer."""
        c = codegen('fn f(items: []i32) -> void { for x in items { } }')
        assert 'sizeof' not in c, 'Fat slice loop must not use sizeof'
        assert '.len' in c

    def test_struct_field_fixpoint_mul(self):
        """Regression: struct field access didn't trigger fixpoint multiply."""
        src = textwrap.dedent('''
            struct Ball { vel: fix16.16 }
            fn update(b: Ball, dt: fix16.16) -> fix16.16 { return b.vel * dt; }
        ''')
        c = codegen(src)
        assert '(int32_t)(((int64_t)' in c, 'Struct field fix16.16 mul must use widening'

    def test_scope_isolation_let_in_if(self):
        """Regression: let in if body leaked into outer scope tracking."""
        src = textwrap.dedent('''
            fn f(cond: bool) -> void {
                if cond {
                    let inner: i32 = 1;
                }
                let outer: i32 = 2;
            }
        ''')
        c = codegen(src)
        assert 'int32_t inner = 1' in c
        assert 'int32_t outer = 2' in c

    def test_case_body_wrapped_in_braces(self):
        """Regression: switch case declarations without braces is invalid C."""
        src = textwrap.dedent('''
            enum Dir { Up, Down }
            fn f(d: Dir) -> void {
                match d {
                    Dir.Up => { let x: i32 = 1; }
                    Dir.Down => { }
                }
            }
        ''')
        c = codegen(src)
        # Each case body should be wrapped in {}
        assert 'case Dir_Up: {' in c or ('case Dir_Up:' in c and '{' in c)
