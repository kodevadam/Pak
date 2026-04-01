"""Pak semantic analysis and type checker.

Performs two passes over the AST:
  1. Collect all top-level declarations into a TypeEnv.
  2. Walk every function/entry body checking:
       - Variable existence and type
       - Struct field existence
       - Function call arity
       - Exhaustive match (E301)
       - Use-after-move (E401)
       - DMA without cache writeback (E201)
       - Unaligned buffers passed to DMA (E202)

Errors are accumulated (not thrown) so the user sees all problems at once.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any, Set
from . import ast


# ── Error codes ───────────────────────────────────────────────────────────────

@dataclass
class PakError:
    code: str
    message: str
    hint: str
    line: int
    col: int
    filename: str = ''

    def __str__(self):
        loc = f'{self.filename}:{self.line}:{self.col}' if self.filename else f'{self.line}:{self.col}'
        lines = [f'error[{self.code}]: {self.message}', f'  --> {loc}']
        if self.hint:
            lines.append(f'  help: {self.hint}')
        return '\n'.join(lines)


# ── Type environment ──────────────────────────────────────────────────────────

class TypeEnv:
    """Global declarations collected in pass 1."""

    def __init__(self):
        self.structs:  Dict[str, ast.StructDecl]  = {}
        self.enums:    Dict[str, ast.EnumDecl]     = {}
        self.variants: Dict[str, ast.VariantDecl]  = {}
        self.fns:      Dict[str, ast.FnDecl]       = {}
        # variant_name → enum/variant name (for exhaustive-match lookup)
        self.enum_cases:    Dict[str, str] = {}  # case → EnumDecl name
        self.variant_cases: Dict[str, str] = {}  # case → VariantDecl name

    def collect(self, program: ast.Program):
        for decl in program.decls:
            if isinstance(decl, ast.StructDecl):
                self.structs[decl.name] = decl
            elif isinstance(decl, ast.EnumDecl):
                self.enums[decl.name] = decl
                for v in decl.variants:
                    self.enum_cases[v.name] = decl.name
            elif isinstance(decl, ast.VariantDecl):
                self.variants[decl.name] = decl
                for c in decl.cases:
                    self.variant_cases[c.name] = decl.name
            elif isinstance(decl, ast.FnDecl):
                self.fns[decl.name] = decl
            elif isinstance(decl, ast.ImplBlock):
                for m in decl.methods:
                    prefixed = f'{decl.type_name}_{m.name}'
                    self.fns[prefixed] = m
            elif isinstance(decl, (ast.ConstDecl, ast.ExternConst)):
                pass  # names registered in _check_top

    def struct_fields(self, name: str) -> Optional[Dict[str, Any]]:
        """Return {field_name: type} for a struct, or None."""
        s = self.structs.get(name)
        if not s:
            return None
        return {f.name: f.type for f in s.fields}

    def fn_params(self, name: str) -> Optional[List[ast.Param]]:
        fn = self.fns.get(name)
        return fn.params if fn else None

    def all_cases(self, type_name: str) -> Optional[List[str]]:
        """Return the full case list for an enum or variant."""
        if type_name in self.enums:
            return [v.name for v in self.enums[type_name].variants]
        if type_name in self.variants:
            return [c.name for c in self.variants[type_name].cases]
        return None


# ── Scope stack ───────────────────────────────────────────────────────────────

class Scope:
    def __init__(self):
        self._stack: List[Dict[str, Any]] = [{}]  # {name: type_node}
        self._moved: Set[str] = set()

    def push(self):
        self._stack.append({})

    def pop(self):
        # Remove moved names that were declared in this scope
        local_names = set(self._stack[-1].keys())
        self._moved -= local_names
        self._stack.pop()

    def declare(self, name: str, typ):
        self._stack[-1][name] = typ
        self._moved.discard(name)

    def lookup(self, name: str) -> Optional[Any]:
        for frame in reversed(self._stack):
            if name in frame:
                return frame[name]
        return None

    def mark_moved(self, name: str):
        self._moved.add(name)

    def is_moved(self, name: str) -> bool:
        return name in self._moved

    def is_declared(self, name: str) -> bool:
        return self.lookup(name) is not None


# ── Fixed-point type helpers ──────────────────────────────────────────────────

FIXPOINT_SHIFTS = {
    'fix16.16': 16,
    'fix10.5':   5,
    'fix1.15':  15,
}


def is_fixpoint(typ) -> bool:
    return isinstance(typ, ast.TypeName) and typ.name in FIXPOINT_SHIFTS


def fixpoint_shift(typ) -> int:
    if isinstance(typ, ast.TypeName):
        return FIXPOINT_SHIFTS.get(typ.name, 0)
    return 0


# ── Type checker ──────────────────────────────────────────────────────────────

# Module names that are not variables (don't trigger "unknown variable" errors)
# Matches every module key used in codegen.MODULE_API
MODULE_NAMESPACES = {
    # n64 subsystems
    'display', 'controller', 'joypad', 'rdpq', 'rdpq_tex', 'rdpq_font', 'rdpq_mode',
    'sprite', 'surface', 'audio', 'mixer', 'xm64', 'wav64', 'timer', 'dma', 'cache',
    'debug', 'math', 'mem', 'vi', 'rsp', 'eeprom', 'backup', 'sram', 'flashram',
    'rtc', 'cpak', 'tpak', 'rumble', 'mouse', 'vru', 'disk', 'system', 'exception',
    # Tiny3D
    't3d',
    # Pak runtime helpers
    'str', 'arena',
    # Generic namespace prefix
    'n64',
}

# C types that are always available (from includes)
BUILTIN_TYPES = {
    'i8', 'i16', 'i32', 'i64', 'u8', 'u16', 'u32', 'u64',
    'f32', 'f64', 'bool', 'byte', 'fix16.16', 'fix10.5', 'fix1.15',
    'Vec2', 'Vec3', 'Vec4', 'Mat4', 'Str', 'CStr', 'PakStr', 'PakArena',
    'Arena', 'void', 'c_char', 'T3DVec2', 'T3DVec3', 'T3DVec4', 'T3DMat4',
}

# Annotations that imply 16-byte alignment
DMA_SAFE_ANNS = {'@dma_safe', '@aligned(16)'}

# libdragon DMA function names
DMA_FNS = {
    ('dma', 'read'), ('dma', 'write'),
    ('cache', 'writeback'), ('cache', 'invalidate'), ('cache', 'writeback_inv'),
}


class TypeChecker:
    def __init__(self, env: TypeEnv, filename: str = ''):
        self.env = env
        self.filename = filename
        self.errors: List[PakError] = []
        self.scope = Scope()
        self._current_fn: Optional[ast.FnDecl] = None
        # Track dma-safe variables (have @dma_safe or @aligned(16))
        self._aligned_vars: Set[str] = set()
        # Track variables that had cache.writeback called on them
        self._cache_written: Set[str] = set()

    def err(self, code: str, msg: str, node, hint: str = ''):
        self.errors.append(PakError(
            code=code, message=msg, hint=hint,
            line=getattr(node, 'line', 0),
            col=getattr(node, 'col', 0),
            filename=self.filename,
        ))

    # ── Pass 2: check bodies ─────────────────────────────────────────────────

    def check(self, program: ast.Program) -> List[PakError]:
        for decl in program.decls:
            self._check_top(decl)
        return self.errors

    def _check_top(self, decl):
        if isinstance(decl, ast.FnDecl):
            self._check_fn(decl)
        elif isinstance(decl, ast.EntryBlock):
            self._check_block(decl.body)
        elif isinstance(decl, ast.StaticDecl):
            self._check_static(decl)
        elif isinstance(decl, ast.LetDecl):
            self._check_let(decl)
        elif isinstance(decl, ast.ImplBlock):
            for m in decl.methods:
                self._check_fn(m)
        elif isinstance(decl, ast.ConstDecl):
            if decl.value:
                self._check_expr(decl.value)
            self.scope.declare(decl.name, decl.type or ast.TypeName(name='auto'))
        elif isinstance(decl, ast.ExternConst):
            self.scope.declare(decl.name, decl.type)

    def _check_fn(self, fn: ast.FnDecl):
        if not fn.body:
            return
        old_fn = self._current_fn
        self._current_fn = fn
        self.scope.push()
        for p in fn.params:
            self.scope.declare(p.name, p.type)
            if _has_annotation(p, '@dma_safe') or _has_annotation(p, '@aligned(16)'):
                self._aligned_vars.add(p.name)
        self._check_block_stmts(fn.body.stmts)
        self.scope.pop()
        self._current_fn = old_fn

    def _check_block(self, block: ast.Block):
        self.scope.push()
        self._check_block_stmts(block.stmts)
        self.scope.pop()

    def _check_block_stmts(self, stmts):
        for stmt in stmts:
            self._check_stmt(stmt)

    def _check_stmt(self, stmt):
        if isinstance(stmt, ast.LetDecl):
            self._check_let(stmt)
        elif isinstance(stmt, ast.StaticDecl):
            self._check_static(stmt)
        elif isinstance(stmt, ast.ExprStmt):
            self._check_expr(stmt.expr)
            self._check_dma_call(stmt.expr)
        elif isinstance(stmt, ast.Return):
            if stmt.value:
                self._check_expr(stmt.value)
        elif isinstance(stmt, ast.IfStmt):
            self._check_expr(stmt.condition)
            self._check_block(stmt.then)
            for ec, eb in stmt.elif_branches:
                self._check_expr(ec)
                self._check_block(eb)
            if stmt.else_branch:
                self._check_block(stmt.else_branch)
        elif isinstance(stmt, ast.NullCheckStmt):
            self._check_expr(stmt.expr)
            self.scope.push()
            self.scope.declare(stmt.binding, ast.TypeName(name='auto'))
            self._check_block_stmts(stmt.then.stmts)
            self.scope.pop()
            if stmt.else_branch:
                self._check_block(stmt.else_branch)
        elif isinstance(stmt, ast.LoopStmt):
            self._check_block(stmt.body)
        elif isinstance(stmt, ast.WhileStmt):
            self._check_expr(stmt.condition)
            self._check_block(stmt.body)
        elif isinstance(stmt, ast.ForStmt):
            self._check_expr(stmt.iterable)
            self.scope.push()
            self.scope.declare(stmt.binding, ast.TypeName(name='auto'))
            if stmt.index:
                self.scope.declare(stmt.index, ast.TypeName(name='i32'))
            self._check_block_stmts(stmt.body.stmts)
            self.scope.pop()
        elif isinstance(stmt, ast.MatchStmt):
            self._check_match(stmt)
        elif isinstance(stmt, ast.DeferStmt):
            self._check_block(stmt.body)
        elif isinstance(stmt, (ast.Break, ast.Continue)):
            pass
        elif isinstance(stmt, ast.Block):
            self._check_block(stmt)
        elif isinstance(stmt, ast.ConstDecl):
            if stmt.value:
                self._check_expr(stmt.value)
            self.scope.declare(stmt.name, stmt.type or ast.TypeName(name='auto'))
        elif isinstance(stmt, ast.AsmStmt):
            pass  # raw asm — nothing to check

    def _check_let(self, s: ast.LetDecl):
        if s.value:
            self._check_expr(s.value)
        typ = s.type
        if typ is None and s.value:
            typ = self._infer_type(s.value)
        self.scope.declare(s.name, typ or ast.TypeName(name='auto'))
        anns = s.annotations or []
        if any(a in DMA_SAFE_ANNS or a.startswith('@aligned') for a in anns):
            self._aligned_vars.add(s.name)

    def _check_static(self, s: ast.StaticDecl):
        if s.value:
            self._check_expr(s.value)
        self.scope.declare(s.name, s.type or ast.TypeName(name='auto'))
        anns = s.annotations or []
        if any(a in DMA_SAFE_ANNS or a.startswith('@aligned') for a in anns):
            self._aligned_vars.add(s.name)

    def _check_expr(self, expr):
        """Recursively validate an expression."""
        if expr is None:
            return
        if isinstance(expr, ast.Ident):
            name = expr.name
            if name == '_':
                return
            if name in MODULE_NAMESPACES:
                return
            if not self.scope.is_declared(name):
                # Could be an enum type name — allow it
                if name in self.env.enums or name in self.env.variants or name in self.env.structs:
                    return
                # Could be a function name
                if name in self.env.fns:
                    return
                self.err('E010', f"unknown name '{name}'", expr,
                         hint=f"declare it with 'let {name} = ...'")
                return
            if self.scope.is_moved(name):
                self.err('E401', f"use of '{name}' after it was moved", expr,
                         hint=f"If you need to use '{name}' after passing it, pass a pointer: &{name}")

        elif isinstance(expr, ast.DotAccess):
            self._check_expr(expr.obj)
            # Check struct field existence
            if isinstance(expr.obj, ast.Ident):
                self._check_field_access(expr.obj, expr.field, expr)

        elif isinstance(expr, ast.Call):
            for a in expr.args:
                self._check_expr(a)
            self._check_call_arity(expr)
            # Track cache operations
            if isinstance(expr.func, ast.DotAccess):
                if isinstance(expr.func.obj, ast.Ident):
                    mod, fn = expr.func.obj.name, expr.func.field
                    if (mod, fn) in {('cache', 'writeback'), ('cache', 'writeback_inv')}:
                        # Mark first arg as cache-written
                        if expr.args:
                            a = expr.args[0]
                            name = self._expr_base_name(a)
                            if name:
                                self._cache_written.add(name)

        elif isinstance(expr, ast.BinaryOp):
            self._check_expr(expr.left)
            self._check_expr(expr.right)

        elif isinstance(expr, ast.UnaryOp):
            self._check_expr(expr.operand)

        elif isinstance(expr, ast.Assign):
            self._check_expr(expr.target)
            self._check_expr(expr.value)

        elif isinstance(expr, ast.AddrOf):
            self._check_expr(expr.expr)

        elif isinstance(expr, ast.Deref):
            self._check_expr(expr.expr)

        elif isinstance(expr, ast.IndexAccess):
            self._check_expr(expr.obj)
            self._check_expr(expr.index)

        elif isinstance(expr, ast.SliceExpr):
            self._check_expr(expr.obj)
            if expr.start:
                self._check_expr(expr.start)
            if expr.end:
                self._check_expr(expr.end)

        elif isinstance(expr, ast.Cast):
            self._check_expr(expr.expr)

        elif isinstance(expr, ast.StructLit):
            self._check_struct_lit(expr)
            for _, v in expr.fields:
                self._check_expr(v)

        elif isinstance(expr, ast.ArrayLit):
            for el in expr.elements:
                self._check_expr(el)
            if expr.repeat:
                self._check_expr(expr.repeat)

        elif isinstance(expr, ast.CatchExpr):
            self._check_expr(expr.expr)
            self.scope.push()
            if expr.binding:
                self.scope.declare(expr.binding, ast.TypeName(name='auto'))
            self._check_block_stmts(expr.handler.stmts)
            self.scope.pop()

        elif isinstance(expr, ast.NamedArg):
            self._check_expr(expr.value)

        elif isinstance(expr, ast.RangeExpr):
            self._check_expr(expr.start)
            if expr.end:
                self._check_expr(expr.end)

        elif isinstance(expr, ast.OkExpr):
            self._check_expr(expr.value)

        elif isinstance(expr, ast.ErrExpr):
            self._check_expr(expr.value)

        elif isinstance(expr, ast.SizeOf):
            pass  # no sub-expressions

        elif isinstance(expr, ast.OffsetOf):
            pass  # no sub-expressions to check

        elif isinstance(expr, ast.AsmExpr):
            for _, e in expr.outputs:
                self._check_expr(e)
            for _, e in expr.inputs:
                self._check_expr(e)

        elif isinstance(expr, ast.Closure):
            self.scope.push()
            for p in expr.params:
                self.scope.declare(p.name, p.type)
            self._check_block_stmts(expr.body.stmts)
            self.scope.pop()

    # ── Field access checking ─────────────────────────────────────────────────

    def _check_field_access(self, obj_ident: ast.Ident, field: str, node):
        """If we know the struct type of obj_ident, verify field exists."""
        typ = self.scope.lookup(obj_ident.name)
        struct_name = self._unwrap_type_name(typ)
        if struct_name and struct_name in self.env.structs:
            fields = self.env.struct_fields(struct_name)
            if fields is not None and field not in fields:
                self.err('E011',
                         f"struct '{struct_name}' has no field '{field}'",
                         node,
                         hint=f"Available fields: {', '.join(fields.keys())}")

    # ── Call arity checking ───────────────────────────────────────────────────

    def _check_call_arity(self, call: ast.Call):
        """Check that user-defined functions are called with the right number of args."""
        if not isinstance(call.func, ast.Ident):
            return
        name = call.func.name
        params = self.env.fn_params(name)
        if params is None:
            return  # external or unknown
        n_args = len(call.args)
        n_params = len(params)
        if n_args != n_params:
            self.err('E012',
                     f"function '{name}' takes {n_params} argument(s), got {n_args}",
                     call,
                     hint=f"Expected: {name}({', '.join(p.name + ': ' + _type_str(p.type) for p in params)})")

    # ── Struct literal checking ───────────────────────────────────────────────

    def _check_struct_lit(self, lit: ast.StructLit):
        decl = self.env.structs.get(lit.type_name)
        if not decl:
            return  # might be a C struct — don't error
        known = {f.name for f in decl.fields}
        given = {name for name, _ in lit.fields}
        unknown = given - known
        for u in sorted(unknown):
            self.err('E013',
                     f"struct '{lit.type_name}' has no field '{u}'",
                     lit,
                     hint=f"Valid fields: {', '.join(sorted(known))}")
        missing = known - given
        if missing:
            self.err('E014',
                     f"struct '{lit.type_name}' missing fields: {', '.join(sorted(missing))}",
                     lit,
                     hint=f"Add the missing fields or initialise them to a default value")

    # ── Exhaustive match (E301) ───────────────────────────────────────────────

    def _check_match(self, stmt: ast.MatchStmt):
        self._check_expr(stmt.expr)
        # Collect covered patterns
        has_wildcard = False
        covered: Set[str] = set()
        for arm in stmt.arms:
            self.scope.push()
            pat = arm.pattern
            if isinstance(pat, ast.Ident) and pat.name == '_':
                has_wildcard = True
            elif isinstance(pat, ast.EnumVariantAccess):
                covered.add(pat.name)
            elif isinstance(pat, ast.DotAccess) and isinstance(pat.obj, ast.Ident):
                covered.add(pat.field)
            if isinstance(arm.body, ast.Block):
                self._check_block_stmts(arm.body.stmts)
            self.scope.pop()

        if has_wildcard:
            return

        # Determine the matched type
        match_type = self._infer_match_type(stmt.expr)
        if match_type is None:
            return  # can't determine — skip exhaustiveness check
        all_cases = self.env.all_cases(match_type)
        if all_cases is None:
            return

        missing = [c for c in all_cases if c not in covered]
        if missing:
            self.err('E301',
                     f"non-exhaustive match on '{match_type}'",
                     stmt,
                     hint=f"Add missing cases: {', '.join('.' + m for m in missing)}"
                          f", or add a default: _ => {{}}")

    def _infer_match_type(self, expr) -> Optional[str]:
        """Best-effort: return the enum/variant type name being matched."""
        if isinstance(expr, ast.Ident):
            typ = self.scope.lookup(expr.name)
            return self._unwrap_type_name(typ)
        if isinstance(expr, ast.DotAccess):
            # e.g. self.state
            if isinstance(expr.obj, ast.Ident):
                typ = self.scope.lookup(expr.obj.name)
                struct_name = self._unwrap_type_name(typ)
                if struct_name:
                    fields = self.env.struct_fields(struct_name)
                    if fields and expr.field in fields:
                        return self._unwrap_type_name(fields[expr.field])
        return None

    # ── DMA safety checks (E201, E202) ───────────────────────────────────────

    def _check_dma_call(self, expr):
        """Check DMA calls for cache writeback (E201) and alignment (E202)."""
        if not isinstance(expr, ast.Call):
            return
        if not isinstance(expr.func, ast.DotAccess):
            return
        if not isinstance(expr.func.obj, ast.Ident):
            return
        mod, fn = expr.func.obj.name, expr.func.field
        if (mod, fn) not in DMA_FNS:
            return

        for arg in expr.args:
            name = self._expr_base_name(arg)
            if not name:
                continue

            # E201: DMA without cache writeback
            if name not in self._cache_written and name not in self._aligned_vars:
                self.err('E201',
                         f"possible stale cache before DMA transfer of '{name}'",
                         expr,
                         hint=f"Add before the transfer: cache.writeback(&{name})")

            # E202: Unaligned buffer
            if name not in self._aligned_vars:
                self.err('E202',
                         f"buffer '{name}' may not be 16-byte aligned for DMA",
                         expr,
                         hint=f"Declare it with @aligned(16): @aligned(16) let {name}: ...")

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _infer_type(self, expr) -> Optional[Any]:
        """Best-effort type inference for an expression."""
        if isinstance(expr, ast.IntLit):
            return ast.TypeName(name='i32')
        if isinstance(expr, ast.FloatLit):
            return ast.TypeName(name='f32')
        if isinstance(expr, ast.BoolLit):
            return ast.TypeName(name='bool')
        if isinstance(expr, ast.StringLit):
            return ast.TypeName(name='Str')
        if isinstance(expr, ast.Ident):
            return self.scope.lookup(expr.name)
        if isinstance(expr, ast.AddrOf):
            inner = self._infer_type(expr.expr)
            if inner:
                return ast.TypePointer(inner=inner, mutable=expr.mutable)
        if isinstance(expr, ast.StructLit):
            return ast.TypeName(name=expr.type_name)
        if isinstance(expr, ast.EnumVariantAccess):
            enum_name = self.env.enum_cases.get(expr.name)
            if enum_name:
                return ast.TypeName(name=enum_name)
        return None

    def _unwrap_type_name(self, typ) -> Optional[str]:
        """Extract the base type name from a type node, unwrapping pointers."""
        if isinstance(typ, ast.TypeName):
            return typ.name
        if isinstance(typ, ast.TypePointer):
            return self._unwrap_type_name(typ.inner)
        return None

    def _expr_base_name(self, expr) -> Optional[str]:
        """Return the base variable name of an expression (for DMA tracking)."""
        if isinstance(expr, ast.Ident):
            return expr.name
        if isinstance(expr, ast.AddrOf):
            return self._expr_base_name(expr.expr)
        if isinstance(expr, ast.DotAccess):
            return self._expr_base_name(expr.obj)
        return None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _has_annotation(node, ann: str) -> bool:
    anns = getattr(node, 'annotations', []) or []
    return ann in anns


def _type_str(typ) -> str:
    if isinstance(typ, ast.TypeName):
        return typ.name
    if isinstance(typ, ast.TypePointer):
        prefix = '?*' if typ.nullable else '*'
        return prefix + _type_str(typ.inner)
    if isinstance(typ, ast.TypeSlice):
        return '[]' + _type_str(typ.inner)
    if isinstance(typ, ast.TypeArray):
        return f'[N]{_type_str(typ.inner)}'
    return '?'


# ── Public API ────────────────────────────────────────────────────────────────

def typecheck(program: ast.Program, filename: str = '') -> List[PakError]:
    """Run the type checker on a parsed program. Returns list of errors."""
    env = TypeEnv()
    env.collect(program)
    checker = TypeChecker(env, filename)
    return checker.check(program)


def typecheck_multi(programs: List[tuple]) -> Dict[str, List[PakError]]:
    """
    Type-check multiple programs sharing a common environment.
    programs: list of (filename, ast.Program)
    Returns {filename: [errors]}
    """
    env = TypeEnv()
    for _, prog in programs:
        env.collect(prog)

    results = {}
    for filename, prog in programs:
        checker = TypeChecker(env, filename)
        results[filename] = checker.check(prog)
    return results
