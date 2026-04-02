"""Normalized C AST representation.

This module defines a simplified, parser-independent intermediate representation
of C source code. It abstracts over pycparser and tree-sitter AST formats so that
the mapping pipeline (type_mapper, expr_mapper, etc.) is decoupled from the
specific parser library in use.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Optional, Tuple, Any, Union


# ── C Types ──────────────────────────────────────────────────────────────────

@dataclass
class CType:
    """Base class for all C type representations."""


@dataclass
class CPrimitive(CType):
    """A primitive/built-in C type.

    name examples: 'int', 'float', 'void', 'char', 'unsigned int',
                   'long long', 'unsigned char', etc.
    """
    name: str


@dataclass
class CPointer(CType):
    """A pointer type (T *)."""
    inner: CType
    is_const: bool = False     # const T * — the pointed-to value is const
    is_volatile: bool = False  # volatile T *


@dataclass
class CArray(CType):
    """A fixed-size or flexible array type (T[N] or T[])."""
    inner: CType
    size: Optional[int] = None  # None = unknown / flexible array member


@dataclass
class CStruct(CType):
    """An inline struct type (anonymous or named)."""
    name: Optional[str]
    fields: List['CField'] = field(default_factory=list)


@dataclass
class CUnion(CType):
    """An inline union type."""
    name: Optional[str]
    fields: List['CField'] = field(default_factory=list)


@dataclass
class CEnum(CType):
    """An inline enum type."""
    name: Optional[str]
    values: List[Tuple[str, Optional[int]]] = field(default_factory=list)


@dataclass
class CFuncPtr(CType):
    """A function pointer type: ret (*)(params)."""
    ret: CType
    params: List[CType] = field(default_factory=list)


@dataclass
class CTypeRef(CType):
    """A reference to a named type (typedef, struct tag, enum tag)."""
    name: str


@dataclass
class CField:
    """A struct/union field declaration."""
    name: str
    typ: CType
    bitsize: Optional[int] = None  # bit-field width in bits


# ── C Declarations ────────────────────────────────────────────────────────────

@dataclass
class CDecl:
    """Base class for top-level declarations."""


@dataclass
class CTypeDef(CDecl):
    """typedef T Name;"""
    name: str
    typ: CType


@dataclass
class CStructDecl(CDecl):
    """struct Name { fields... };"""
    name: str
    fields: List[CField]
    attrs: List[str] = field(default_factory=list)  # e.g. ['aligned(4)', 'packed']


@dataclass
class CUnionDecl(CDecl):
    """union Name { fields... };"""
    name: str
    fields: List[CField]
    attrs: List[str] = field(default_factory=list)


@dataclass
class CEnumDecl(CDecl):
    """enum Name { VALUES... };"""
    name: str
    values: List[Tuple[str, Optional[int]]]
    base_type: Optional[str] = None  # GCC: 'enum Name : uint8_t'


@dataclass
class CParam:
    """A function parameter."""
    name: Optional[str]
    typ: CType
    is_variadic: bool = False  # True for the '...' parameter


@dataclass
class CFuncSignature:
    """A function declaration (signature only, no body)."""
    name: str
    ret: CType
    params: List[CParam]
    is_static: bool = False
    is_inline: bool = False
    is_variadic: bool = False
    is_extern: bool = False


@dataclass
class CFuncDecl(CDecl):
    """A function declaration (forward declaration)."""
    sig: CFuncSignature


@dataclass
class CFuncDef(CDecl):
    """A function definition (declaration + body)."""
    sig: CFuncSignature
    body: 'CCompound'


@dataclass
class CVarDecl(CDecl):
    """A global or local variable declaration."""
    name: str
    typ: CType
    init: Optional['CExpr'] = None
    is_static: bool = False
    is_extern: bool = False
    is_const: bool = False


@dataclass
class CFile:
    """The root of a parsed C translation unit."""
    decls: List[CDecl] = field(default_factory=list)
    # Macros captured by the preprocessor (name → expanded text)
    macros: dict = field(default_factory=dict)


# ── C Expressions ─────────────────────────────────────────────────────────────

@dataclass
class CExpr:
    """Base class for all C expressions."""


@dataclass
class CConst(CExpr):
    """A literal constant."""
    value: str    # raw source text (e.g., '42', '3.14f', '"hello"', '\'a\'')
    kind: str     # 'int', 'float', 'string', 'char'


@dataclass
class CId(CExpr):
    """An identifier reference."""
    name: str


@dataclass
class CBinOp(CExpr):
    """A binary expression: left op right."""
    op: str       # '+', '-', '*', '/', '%', '&', '|', '^', '<<', '>>', etc.
    left: CExpr
    right: CExpr


@dataclass
class CUnaryOp(CExpr):
    """A unary expression: op expr (prefix) or expr op (postfix)."""
    op: str       # '-', '~', '!', '&', '*', '++', '--', 'p++', 'p--'
    expr: CExpr
    postfix: bool = False  # True for x++, x--


@dataclass
class CAssign(CExpr):
    """An assignment expression: target op= value."""
    op: str       # '=', '+=', '-=', '*=', '/=', '%=', '&=', '|=', '^=', '<<=', '>>='
    target: CExpr
    value: CExpr


@dataclass
class CCall(CExpr):
    """A function call expression."""
    func: CExpr
    args: List[CExpr] = field(default_factory=list)


@dataclass
class CArrayRef(CExpr):
    """Array subscript: base[index]."""
    base: CExpr
    index: CExpr


@dataclass
class CStructRef(CExpr):
    """Struct member access: base.field or base->field."""
    base: CExpr
    member: str
    arrow: bool = False  # True for ->


@dataclass
class CCast(CExpr):
    """Explicit type cast: (T)expr."""
    typ: CType
    expr: CExpr


@dataclass
class CTernary(CExpr):
    """Ternary operator: cond ? then : otherwise."""
    cond: CExpr
    then: CExpr
    otherwise: CExpr


@dataclass
class CComma(CExpr):
    """Comma operator: expr1, expr2, ..., exprN (value is exprN)."""
    exprs: List[CExpr] = field(default_factory=list)


@dataclass
class CSizeof(CExpr):
    """sizeof operator: sizeof(T) or sizeof expr."""
    target: Any  # CType or CExpr


@dataclass
class COffsetof(CExpr):
    """offsetof(StructType, field)."""
    struct_type: CType
    member: str


@dataclass
class CInitList(CExpr):
    """An initializer list: { item1, item2, ... }
    Items are either CExpr (positional) or (str, CExpr) (named: .field = expr).
    """
    items: List[Any] = field(default_factory=list)


# ── C Statements ──────────────────────────────────────────────────────────────

@dataclass
class CStmt:
    """Base class for all C statements."""


@dataclass
class CCompound(CStmt):
    """A compound statement (block): { items... }
    Items are either CVarDecl (local variable) or CStmt (statement).
    """
    items: List[Any] = field(default_factory=list)


@dataclass
class CExprStmt(CStmt):
    """An expression used as a statement: expr;"""
    expr: CExpr


@dataclass
class CIf(CStmt):
    """An if/else statement."""
    cond: CExpr
    then: CStmt
    otherwise: Optional[CStmt] = None


@dataclass
class CWhile(CStmt):
    """A while loop."""
    cond: CExpr
    body: CStmt


@dataclass
class CDoWhile(CStmt):
    """A do-while loop."""
    cond: CExpr
    body: CStmt


@dataclass
class CFor(CStmt):
    """A for loop.
    init may be None, a list of CVarDecl, or a CExprStmt.
    """
    init: Optional[Any]
    cond: Optional[CExpr]
    step: Optional[CExpr]
    body: CStmt


@dataclass
class CSwitch(CStmt):
    """A switch statement."""
    cond: CExpr
    cases: List['CCase'] = field(default_factory=list)


@dataclass
class CCase(CStmt):
    """A single case (or default) within a switch.
    value=None means 'default'.
    """
    value: Optional[CExpr]
    stmts: List[Any] = field(default_factory=list)  # CStmt items
    has_break: bool = True  # does this case end with a break?


@dataclass
class CReturn(CStmt):
    """A return statement."""
    value: Optional[CExpr] = None


@dataclass
class CBreak(CStmt):
    """A break statement."""


@dataclass
class CContinue(CStmt):
    """A continue statement."""


@dataclass
class CGoto(CStmt):
    """A goto statement."""
    label: str


@dataclass
class CLabel(CStmt):
    """A label."""
    name: str
    stmt: Optional[CStmt] = None


@dataclass
class CEmpty(CStmt):
    """An empty statement (just a semicolon)."""
