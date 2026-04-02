"""C parser wrapper.

Wraps pycparser to produce a normalized C AST (c_ast.CFile).
Falls back to a helpful error if pycparser is not installed.

Usage:
    from pak.c2pak.c_parser import parse_c_source, parse_c_file

    c_file = parse_c_file(Path("foo.c"))  # CFile
"""

from __future__ import annotations
from pathlib import Path
from typing import Optional

from .c_ast import (
    CFile, CDecl, CType,
    CPrimitive, CPointer, CArray, CStruct, CUnion, CEnum, CFuncPtr, CTypeRef,
    CField,
    CTypeDef, CStructDecl, CUnionDecl, CEnumDecl,
    CParam, CFuncSignature, CFuncDecl, CFuncDef,
    CVarDecl,
    CExpr, CConst, CId, CBinOp, CUnaryOp, CAssign, CCall,
    CArrayRef, CStructRef, CCast, CTernary, CComma, CSizeof, CInitList,
    CStmt, CCompound, CExprStmt, CIf, CWhile, CDoWhile, CFor,
    CSwitch, CCase, CReturn, CBreak, CContinue, CGoto, CLabel, CEmpty,
)
from .c_preprocess import preprocess, SimpleMacro


# ── pycparser import (optional) ───────────────────────────────────────────────

try:
    import pycparser
    import pycparser.c_ast as _pc
    from pycparser.c_parser import CParser as _CParser, ParseError as _ParseError
    _HAVE_PYCPARSER = True
except ImportError:
    _HAVE_PYCPARSER = False
    _pc = None
    _CParser = None
    _ParseError = Exception


_PYCPARSER_MISSING = """\
pycparser is required for the C-to-Pak transpiler.
Install it with:  pip install pycparser
"""


# ── Public API ────────────────────────────────────────────────────────────────

def parse_c_source(source: str, filename: str = '<string>') -> CFile:
    """Parse a C source string into a normalized CFile AST.

    The source should already be preprocessed (or contain only simple #defines
    that the bundled preprocessor can handle).
    """
    if not _HAVE_PYCPARSER:
        raise ImportError(_PYCPARSER_MISSING)

    # Run our lightweight preprocessor to collect macros and strip directives
    cleaned, macros = preprocess(source)

    # Inject our prelude (typedef stubs for common N64/decomp types)
    # Prelude has no directives, so we don't need to preprocess it.
    full_source = _PYCPARSER_PRELUDE + cleaned

    try:
        parser = _CParser()
        ast = parser.parse(full_source, filename=filename)
    except _ParseError as e:
        raise ValueError(f'C parse error in {filename}: {e}') from e

    converter = _PycparserConverter(macros)
    return converter.convert_file(ast)


def parse_c_file(path: Path) -> CFile:
    """Parse a C file from disk into a normalized CFile AST."""
    source = path.read_text(encoding='utf-8')
    return parse_c_source(source, str(path))


# Preamble injected before the user's code to define common N64 typedefs
# so pycparser doesn't error on unknown types.
# NOTE: pycparser cannot handle #define directives — all stubs must be typedefs.
_PYCPARSER_PRELUDE = """\
typedef signed char s8;
typedef unsigned char u8;
typedef signed short s16;
typedef unsigned short u16;
typedef signed int s32;
typedef unsigned int u32;
typedef signed long long s64;
typedef unsigned long long u64;
typedef float f32;
typedef double f64;
typedef s8 int8_t;
typedef u8 uint8_t;
typedef s16 int16_t;
typedef u16 uint16_t;
typedef s32 int32_t;
typedef u32 uint32_t;
typedef s64 int64_t;
typedef u64 uint64_t;
typedef u32 size_t;
typedef s32 ptrdiff_t;
typedef void *__builtin_va_list;
typedef int bool;
typedef void *FILE;
typedef void *surface_t;
typedef int wchar_t;
typedef unsigned int uintptr_t;
typedef signed int intptr_t;
"""


# ── pycparser → normalized C AST converter ────────────────────────────────────

class _PycparserConverter:
    """Walks a pycparser AST and produces a normalized CFile."""

    def __init__(self, macros: dict):
        self.macros = macros
        # typedef name → CType (built up as we process declarations)
        self._typedefs: dict[str, CType] = {}
        self._anon_counter = 0

    # ── Top-level ─────────────────────────────────────────────────────────────

    def convert_file(self, ast) -> CFile:
        decls: list[CDecl] = []
        for node in ast.ext:
            converted = self._convert_top(node)
            if converted is not None:
                if isinstance(converted, list):
                    decls.extend(converted)
                else:
                    decls.append(converted)
        cf = CFile(decls=decls, macros=self.macros)
        return cf

    def _convert_top(self, node) -> 'CDecl | list[CDecl] | None':
        """Convert a top-level pycparser node."""
        t = type(node).__name__
        if t == 'Decl':
            return self._convert_decl_top(node)
        elif t == 'FuncDef':
            return self._convert_funcdef(node)
        elif t == 'Typedef':
            return self._convert_typedef(node)
        return None

    # ── Types ─────────────────────────────────────────────────────────────────

    def _convert_type(self, node) -> CType:
        """Convert a pycparser type node to a CType."""
        t = type(node).__name__
        if t == 'TypeDecl':
            return self._convert_type(node.type)
        elif t == 'IdentifierType':
            name = ' '.join(node.names)
            # Single-token names that are not C keywords are typedef references
            if self._is_user_typedef(name):
                return CTypeRef(name)
            return CPrimitive(name)
        elif t == 'PtrDecl':
            quals = node.quals or []
            inner = self._convert_type(node.type)
            is_const = 'const' in quals
            is_vol = 'volatile' in quals
            return CPointer(inner=inner, is_const=is_const, is_volatile=is_vol)
        elif t == 'ArrayDecl':
            inner = self._convert_type(node.type)
            size = None
            if node.dim is not None:
                size = self._eval_const_int(node.dim)
            return CArray(inner=inner, size=size)
        elif t == 'Struct':
            return self._convert_struct_type(node)
        elif t == 'Union':
            return self._convert_union_type(node)
        elif t == 'Enum':
            return self._convert_enum_type(node)
        elif t == 'FuncDecl':
            return self._convert_func_ptr_type(node)
        elif t == 'Typename':
            return self._convert_type(node.type)
        else:
            # Unknown type node — fall back to a named reference
            return CPrimitive('/* unknown */')

    def _convert_struct_type(self, node) -> CType:
        name = node.name
        if node.decls is None:
            # Forward reference or reference by name
            return CTypeRef(name or f'_Anon{self._next_anon()}')
        fields = self._convert_fields(node.decls)
        return CStruct(name=name, fields=fields)

    def _convert_union_type(self, node) -> CType:
        name = node.name
        if node.decls is None:
            return CTypeRef(name or f'_Anon{self._next_anon()}')
        fields = self._convert_fields(node.decls)
        return CUnion(name=name, fields=fields)

    def _convert_enum_type(self, node) -> CType:
        name = node.name
        if node.values is None:
            return CTypeRef(name or f'_AnonEnum{self._next_anon()}')
        values = []
        next_val = 0
        for enumerator in node.values.enumerators:
            if enumerator.value is not None:
                v = self._eval_const_int(enumerator.value)
                if v is None:
                    v = next_val
                values.append((enumerator.name, v))
                next_val = v + 1
            else:
                values.append((enumerator.name, None))
                next_val += 1
        return CEnum(name=name, values=values)

    def _convert_func_ptr_type(self, node) -> CType:
        ret = self._convert_type(node.type)
        params: list[CType] = []
        if node.args:
            for p in node.args.params:
                if type(p).__name__ == 'EllipsisParam':
                    break
                params.append(self._convert_type(p.type))
        return CFuncPtr(ret=ret, params=params)

    def _convert_fields(self, decls) -> list[CField]:
        fields = []
        for decl in (decls or []):
            t = type(decl).__name__
            if t == 'Decl':
                name = decl.name or f'_f{self._next_anon()}'
                typ = self._convert_type(decl.type)
                bitsize = None
                if decl.bitsize is not None:
                    bitsize = self._eval_const_int(decl.bitsize)
                fields.append(CField(name=name, typ=typ, bitsize=bitsize))
        return fields

    # ── Top-level declarations ─────────────────────────────────────────────────

    def _convert_typedef(self, node) -> 'CDecl | None':
        name = node.name
        typ = self._convert_type(node.type)
        self._typedefs[name] = typ
        return CTypeDef(name=name, typ=typ)

    def _convert_decl_top(self, node) -> 'CDecl | list[CDecl] | None':
        """Convert a top-level Decl node."""
        t = type(node.type).__name__
        if t == 'FuncDecl':
            sig = self._build_func_sig(node)
            return CFuncDecl(sig=sig)
        elif t in ('Struct', 'Union', 'Enum'):
            return self._convert_tag_decl(node)
        else:
            # Global variable
            name = node.name
            if name is None:
                return None
            typ = self._convert_type(node.type)
            init = None
            if node.init is not None:
                init = self._convert_expr(node.init)
            is_const = 'const' in (node.quals or [])
            is_static = 'static' in (node.storage or [])
            is_extern = 'extern' in (node.storage or [])
            return CVarDecl(name=name, typ=typ, init=init,
                            is_static=is_static, is_extern=is_extern,
                            is_const=is_const)

    def _convert_tag_decl(self, node) -> 'CDecl | None':
        """Convert struct/union/enum tag declarations."""
        inner = node.type
        t = type(inner).__name__
        if t == 'Struct':
            if inner.decls is None:
                return None  # forward decl only
            fields = self._convert_fields(inner.decls)
            name = inner.name or node.name or f'_Anon{self._next_anon()}'
            attrs = self._extract_attrs(node)
            return CStructDecl(name=name, fields=fields, attrs=attrs)
        elif t == 'Union':
            if inner.decls is None:
                return None
            fields = self._convert_fields(inner.decls)
            name = inner.name or node.name or f'_Anon{self._next_anon()}'
            attrs = self._extract_attrs(node)
            return CUnionDecl(name=name, fields=fields, attrs=attrs)
        elif t == 'Enum':
            if inner.values is None:
                return None
            values = []
            next_val = 0
            for en in inner.values.enumerators:
                if en.value is not None:
                    v = self._eval_const_int(en.value)
                    if v is None:
                        v = next_val
                    values.append((en.name, v))
                    next_val = v + 1
                else:
                    values.append((en.name, None))
                    next_val += 1
            name = inner.name or node.name or f'_AnonEnum{self._next_anon()}'
            return CEnumDecl(name=name, values=values)
        return None

    def _extract_attrs(self, node) -> list[str]:
        """Extract __attribute__ values from a Decl node."""
        attrs = []
        # pycparser stores attributes in node.align list as NamedInitializer or similar
        # This is a best-effort extraction
        return attrs

    def _convert_funcdef(self, node) -> CFuncDef:
        sig = self._build_func_sig(node.decl)
        body = self._convert_compound(node.body)
        return CFuncDef(sig=sig, body=body)

    def _build_func_sig(self, decl_node) -> CFuncSignature:
        name = decl_node.name or '?'
        func_decl = decl_node.type
        # Unwrap TypeDecl wrappers
        while type(func_decl).__name__ == 'TypeDecl':
            func_decl = func_decl.type
        if type(func_decl).__name__ != 'FuncDecl':
            # Shouldn't happen, but be safe
            return CFuncSignature(name=name, ret=CPrimitive('void'), params=[])
        ret = self._convert_type(func_decl.type)
        params = []
        is_variadic = False
        if func_decl.args:
            for p in func_decl.args.params:
                if type(p).__name__ == 'EllipsisParam':
                    is_variadic = True
                    break
                pname = p.name
                ptyp = self._convert_type(p.type)
                params.append(CParam(name=pname, typ=ptyp))
        storage = decl_node.storage or []
        funcspec = decl_node.funcspec or []
        is_static = 'static' in storage
        is_inline = 'inline' in funcspec or '__inline__' in funcspec
        is_extern = 'extern' in storage
        return CFuncSignature(
            name=name, ret=ret, params=params,
            is_static=is_static, is_inline=is_inline,
            is_variadic=is_variadic, is_extern=is_extern,
        )

    # ── Statements ────────────────────────────────────────────────────────────

    def _convert_stmt(self, node) -> CStmt:
        if node is None:
            return CEmpty()
        t = type(node).__name__
        if t == 'Compound':
            return self._convert_compound(node)
        elif t == 'If':
            return CIf(
                cond=self._convert_expr(node.cond),
                then=self._convert_stmt(node.iftrue),
                otherwise=self._convert_stmt(node.iffalse) if node.iffalse else None,
            )
        elif t == 'While':
            return CWhile(
                cond=self._convert_expr(node.cond),
                body=self._convert_stmt(node.stmt),
            )
        elif t == 'DoWhile':
            return CDoWhile(
                cond=self._convert_expr(node.cond),
                body=self._convert_stmt(node.stmt),
            )
        elif t == 'For':
            init = self._convert_for_init(node.init)
            cond = self._convert_expr(node.cond) if node.cond else None
            step = self._convert_expr(node.next) if node.next else None
            body = self._convert_stmt(node.stmt)
            return CFor(init=init, cond=cond, step=step, body=body)
        elif t == 'Switch':
            cond = self._convert_expr(node.cond)
            cases = self._convert_switch_body(node.stmt)
            return CSwitch(cond=cond, cases=cases)
        elif t == 'Return':
            val = self._convert_expr(node.expr) if node.expr else None
            return CReturn(value=val)
        elif t == 'Break':
            return CBreak()
        elif t == 'Continue':
            return CContinue()
        elif t == 'Goto':
            return CGoto(label=node.name)
        elif t == 'Label':
            stmt = self._convert_stmt(node.stmt) if node.stmt else None
            return CLabel(name=node.name, stmt=stmt)
        elif t == 'Decl':
            # Local variable declaration used as a statement
            return self._convert_local_decl(node)
        elif t == 'DeclList':
            items = []
            for d in node.decls:
                items.append(self._convert_local_decl(d))
            return CCompound(items=items)
        elif t == 'EmptyStatement':
            return CEmpty()
        else:
            # Expression statement
            try:
                expr = self._convert_expr(node)
                return CExprStmt(expr=expr)
            except Exception:
                return CEmpty()

    def _convert_compound(self, node) -> CCompound:
        items = []
        for item in (node.block_items or []):
            t = type(item).__name__
            if t == 'Decl':
                items.append(self._convert_local_decl(item))
            elif t == 'DeclList':
                for d in item.decls:
                    items.append(self._convert_local_decl(d))
            else:
                items.append(self._convert_stmt(item))
        return CCompound(items=items)

    def _convert_local_decl(self, node) -> CVarDecl:
        name = node.name or f'_v{self._next_anon()}'
        typ = self._convert_type(node.type)
        init = None
        if node.init is not None:
            init = self._convert_expr(node.init)
        is_const = 'const' in (node.quals or [])
        is_static = 'static' in (node.storage or [])
        return CVarDecl(name=name, typ=typ, init=init,
                        is_static=is_static, is_const=is_const)

    def _convert_for_init(self, node):
        if node is None:
            return None
        t = type(node).__name__
        if t == 'DeclList':
            return [self._convert_local_decl(d) for d in node.decls]
        elif t == 'Decl':
            return [self._convert_local_decl(node)]
        else:
            return CExprStmt(expr=self._convert_expr(node))

    def _convert_switch_body(self, node) -> list[CCase]:
        """Convert a Compound node (switch body) into a list of CCase."""
        cases: list[CCase] = []
        current_case: CCase | None = None
        for item in (node.block_items or []):
            t = type(item).__name__
            if t == 'Case':
                val = self._convert_expr(item.expr)
                current_case = CCase(value=val, stmts=[], has_break=False)
                cases.append(current_case)
                # Process stmts within the case
                for s in (item.stmts or []):
                    self._add_to_case(current_case, s)
            elif t == 'Default':
                current_case = CCase(value=None, stmts=[], has_break=False)
                cases.append(current_case)
                for s in (item.stmts or []):
                    self._add_to_case(current_case, s)
            else:
                if current_case is not None:
                    self._add_to_case(current_case, item)
        return cases

    def _add_to_case(self, case: CCase, item):
        t = type(item).__name__
        if t == 'Break':
            case.has_break = True
        elif t == 'Case':
            val = self._convert_expr(item.expr)
            # Nested case — just add to current for simplicity
            for s in (item.stmts or []):
                self._add_to_case(case, s)
        elif t == 'Default':
            for s in (item.stmts or []):
                self._add_to_case(case, s)
        else:
            case.stmts.append(self._convert_stmt(item))

    # ── Expressions ───────────────────────────────────────────────────────────

    def _convert_expr(self, node) -> CExpr:
        if node is None:
            return CId('none')
        t = type(node).__name__
        if t == 'Constant':
            kind = node.type or 'int'
            return CConst(value=node.value, kind=kind)
        elif t == 'ID':
            return CId(name=node.name)
        elif t == 'BinaryOp':
            return CBinOp(
                op=node.op,
                left=self._convert_expr(node.left),
                right=self._convert_expr(node.right),
            )
        elif t == 'UnaryOp':
            op = node.op
            postfix = op in ('p++', 'p--')
            if postfix:
                op = op[1:]  # strip 'p' prefix
            return CUnaryOp(op=op, expr=self._convert_expr(node.expr), postfix=postfix)
        elif t == 'Assignment':
            return CAssign(
                op=node.op,
                target=self._convert_expr(node.lvalue),
                value=self._convert_expr(node.rvalue),
            )
        elif t == 'FuncCall':
            func = self._convert_expr(node.name)
            args = []
            if node.args:
                for a in node.args.exprs:
                    args.append(self._convert_expr(a))
            return CCall(func=func, args=args)
        elif t == 'ArrayRef':
            return CArrayRef(
                base=self._convert_expr(node.name),
                index=self._convert_expr(node.subscript),
            )
        elif t == 'StructRef':
            arrow = (node.type == '->')
            return CStructRef(
                base=self._convert_expr(node.name),
                member=node.field.name,
                arrow=arrow,
            )
        elif t == 'Cast':
            typ = self._convert_type(node.to_type)
            return CCast(typ=typ, expr=self._convert_expr(node.expr))
        elif t == 'TernaryOp':
            return CTernary(
                cond=self._convert_expr(node.cond),
                then=self._convert_expr(node.iftrue),
                otherwise=self._convert_expr(node.iffalse),
            )
        elif t == 'ExprList':
            exprs = [self._convert_expr(e) for e in node.exprs]
            if len(exprs) == 1:
                return exprs[0]
            return CComma(exprs=exprs)
        elif t == 'NamedInitializer':
            # named struct initializer .field = value
            field_name = node.name[0].name if node.name else '_'
            val = self._convert_expr(node.expr)
            # Return as a special marker tuple-wrapped in CInitList? Or just the val.
            # We'll return as-is and let decl_mapper interpret it.
            return val  # simplified
        elif t == 'CompoundLiteral':
            typ = self._convert_type(node.type)
            items = self._convert_init_list(node.init)
            return CInitList(items=items)
        elif t == 'InitList':
            items = self._convert_init_list(node)
            return CInitList(items=items)
        elif t == 'UnaryOp' and node.op == 'sizeof':
            return CSizeof(target=self._convert_expr(node.expr))
        elif t == 'Typename':
            # sizeof(type) — return CSizeof with a type
            typ = self._convert_type(node)
            return CSizeof(target=typ)
        else:
            # Fallback
            return CId(f'/* unhandled:{t} */')

    def _convert_init_list(self, node) -> list:
        items = []
        for item in (node.exprs or []):
            t = type(item).__name__
            if t == 'NamedInitializer':
                field_name = item.name[0].name if item.name else '_'
                val = self._convert_expr(item.expr)
                items.append((field_name, val))
            else:
                items.append(self._convert_expr(item))
        return items

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _eval_const_int(self, node) -> Optional[int]:
        """Try to evaluate a constant integer expression."""
        t = type(node).__name__
        if t == 'Constant':
            try:
                v = node.value
                if v.startswith('0x') or v.startswith('0X'):
                    return int(v, 16)
                elif v.startswith('0b') or v.startswith('0B'):
                    return int(v, 2)
                elif v.startswith('0') and len(v) > 1:
                    try:
                        return int(v, 8)
                    except ValueError:
                        return int(v, 10)
                return int(v.rstrip('uUlL'))
            except (ValueError, AttributeError):
                return None
        elif t == 'UnaryOp' and node.op == '-':
            v = self._eval_const_int(node.expr)
            return -v if v is not None else None
        elif t == 'BinaryOp':
            l = self._eval_const_int(node.left)
            r = self._eval_const_int(node.right)
            if l is not None and r is not None:
                try:
                    return eval(f'{l}{node.op}{r}')
                except Exception:
                    return None
        return None

    def _next_anon(self) -> int:
        self._anon_counter += 1
        return self._anon_counter

    # C built-in type keywords that should NOT become CTypeRef
    _C_KEYWORDS = frozenset({
        'void', 'char', 'short', 'int', 'long', 'float', 'double',
        'signed', 'unsigned', 'bool', '_Bool',
        'int8_t', 'int16_t', 'int32_t', 'int64_t',
        'uint8_t', 'uint16_t', 'uint32_t', 'uint64_t',
        's8', 's16', 's32', 's64', 'u8', 'u16', 'u32', 'u64',
        'f32', 'f64', 'size_t', 'ptrdiff_t',
    })

    def _is_user_typedef(self, name: str) -> bool:
        """Return True if *name* is a single-token user-defined type (not a C keyword)."""
        # If it contains spaces it's a compound C type (e.g. 'unsigned int')
        if ' ' in name:
            return False
        # If it's a known C primitive keyword, keep as CPrimitive
        if name in self._C_KEYWORDS:
            return False
        # If we've seen it as a typedef already, it's definitely user-defined
        if name in self._typedefs:
            return True
        # Any CamelCase or all-uppercase single-word names are likely typedefs
        # (heuristic: starts with uppercase letter OR looks like a N64 decomp type)
        if name[0].isupper() or name.startswith('__'):
            return True
        return False
