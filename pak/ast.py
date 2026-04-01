"""Pak AST node definitions."""

from dataclasses import dataclass, field
from typing import List, Optional, Any


# Base class uses slots trick: we put line/col at the end via keyword-only
# Simpler: just put all required fields before optional ones in each node.
# We don't inherit from a base - nodes are standalone dataclasses.

# ── Types ────────────────────────────────────────────────────────────────────

@dataclass
class TypeName:
    name: str
    line: int = 0
    col: int = 0

@dataclass
class TypePointer:
    inner: Any
    nullable: bool = False
    mutable: bool = False
    line: int = 0
    col: int = 0

@dataclass
class TypeSlice:
    inner: Any
    line: int = 0
    col: int = 0

@dataclass
class TypeArray:
    size: Any
    inner: Any
    line: int = 0
    col: int = 0

@dataclass
class TypeResult:
    ok: Any
    err: Any
    line: int = 0
    col: int = 0

@dataclass
class TypeOption:
    inner: Any
    line: int = 0
    col: int = 0

@dataclass
class TypeFn:
    params: List[Any]
    ret: Optional[Any]
    line: int = 0
    col: int = 0


# ── Expressions ──────────────────────────────────────────────────────────────

@dataclass
class IntLit:
    value: int
    raw: str = ''
    line: int = 0
    col: int = 0

@dataclass
class FloatLit:
    value: float
    line: int = 0
    col: int = 0

@dataclass
class BoolLit:
    value: bool
    line: int = 0
    col: int = 0

@dataclass
class StringLit:
    value: str
    line: int = 0
    col: int = 0

@dataclass
class NoneLit:
    line: int = 0
    col: int = 0

@dataclass
class UndefinedLit:
    line: int = 0
    col: int = 0

@dataclass
class Ident:
    name: str
    line: int = 0
    col: int = 0

@dataclass
class DotAccess:
    obj: Any
    field: str
    line: int = 0
    col: int = 0

@dataclass
class IndexAccess:
    obj: Any
    index: Any
    line: int = 0
    col: int = 0

@dataclass
class SliceExpr:
    obj: Any
    start: Optional[Any]
    end: Optional[Any]
    line: int = 0
    col: int = 0

@dataclass
class Call:
    func: Any
    args: List[Any]
    line: int = 0
    col: int = 0

@dataclass
class StructLit:
    type_name: str
    fields: List[Any]  # list of (name, expr) tuples
    line: int = 0
    col: int = 0

@dataclass
class ArrayLit:
    elements: List[Any]
    repeat: Optional[Any] = None
    line: int = 0
    col: int = 0

@dataclass
class UnaryOp:
    op: str
    operand: Any
    line: int = 0
    col: int = 0

@dataclass
class BinaryOp:
    op: str
    left: Any
    right: Any
    line: int = 0
    col: int = 0

@dataclass
class Assign:
    target: Any
    value: Any
    op: str = '='
    line: int = 0
    col: int = 0

@dataclass
class AddrOf:
    expr: Any
    mutable: bool = False
    line: int = 0
    col: int = 0

@dataclass
class Deref:
    expr: Any
    line: int = 0
    col: int = 0

@dataclass
class Cast:
    expr: Any
    type: Any
    line: int = 0
    col: int = 0

@dataclass
class RangeExpr:
    start: Any
    end: Optional[Any]
    line: int = 0
    col: int = 0

@dataclass
class EnumVariantAccess:
    name: str
    line: int = 0
    col: int = 0

@dataclass
class NamedArg:
    name: str
    value: Any
    line: int = 0
    col: int = 0

@dataclass
class CatchExpr:
    expr: Any
    binding: Optional[str]
    handler: Any
    line: int = 0
    col: int = 0

@dataclass
class NullCheck:
    expr: Any
    binding: Optional[str]
    line: int = 0
    col: int = 0


# ── Statements ───────────────────────────────────────────────────────────────

@dataclass
class Block:
    stmts: List[Any]
    line: int = 0
    col: int = 0

@dataclass
class LetDecl:
    name: str
    type: Optional[Any]
    value: Optional[Any]
    mutable: bool = True
    annotations: List[str] = field(default_factory=list)
    line: int = 0
    col: int = 0

@dataclass
class StaticDecl:
    name: str
    type: Optional[Any]
    value: Optional[Any]
    annotations: List[str] = field(default_factory=list)
    line: int = 0
    col: int = 0

@dataclass
class Return:
    value: Optional[Any]
    line: int = 0
    col: int = 0

@dataclass
class Break:
    line: int = 0
    col: int = 0

@dataclass
class Continue:
    line: int = 0
    col: int = 0

@dataclass
class IfStmt:
    condition: Any
    then: Any
    elif_branches: List[Any]
    else_branch: Optional[Any]
    line: int = 0
    col: int = 0

@dataclass
class NullCheckStmt:
    expr: Any
    binding: str
    then: Any
    else_branch: Optional[Any]
    line: int = 0
    col: int = 0

@dataclass
class LoopStmt:
    body: Any
    line: int = 0
    col: int = 0

@dataclass
class WhileStmt:
    condition: Any
    body: Any
    line: int = 0
    col: int = 0

@dataclass
class ForStmt:
    index: Optional[str]
    binding: str
    iterable: Any
    body: Any
    line: int = 0
    col: int = 0

@dataclass
class MatchArm:
    pattern: Any
    guard: Optional[Any]
    body: Any
    line: int = 0
    col: int = 0

@dataclass
class MatchStmt:
    expr: Any
    arms: List[Any]
    line: int = 0
    col: int = 0

@dataclass
class DeferStmt:
    body: Any
    line: int = 0
    col: int = 0

@dataclass
class ExprStmt:
    expr: Any
    line: int = 0
    col: int = 0


# ── Top-level declarations ────────────────────────────────────────────────────

@dataclass
class UseDecl:
    path: str
    line: int = 0
    col: int = 0

@dataclass
class AssetDecl:
    name: str
    asset_type: Optional[str]
    path: str
    line: int = 0
    col: int = 0

@dataclass
class StructField:
    name: str
    type: Any
    annotations: List[str] = field(default_factory=list)
    line: int = 0
    col: int = 0

@dataclass
class StructDecl:
    name: str
    fields: List[Any]
    annotations: List[str] = field(default_factory=list)
    line: int = 0
    col: int = 0

@dataclass
class EnumVariant:
    name: str
    value: Optional[Any] = None
    line: int = 0
    col: int = 0

@dataclass
class EnumDecl:
    name: str
    base_type: Optional[str]
    variants: List[Any]
    annotations: List[str] = field(default_factory=list)
    line: int = 0
    col: int = 0

@dataclass
class VariantCase:
    name: str
    fields: List[Any]
    line: int = 0
    col: int = 0

@dataclass
class VariantDecl:
    name: str
    cases: List[Any]
    annotations: List[str] = field(default_factory=list)
    line: int = 0
    col: int = 0

@dataclass
class Param:
    name: str
    type: Any
    mutable: bool = False
    line: int = 0
    col: int = 0

@dataclass
class FnDecl:
    name: str
    params: List[Any]
    ret_type: Optional[Any]
    body: Optional[Any]
    annotations: List[str] = field(default_factory=list)
    is_method: bool = False
    self_type: Optional[str] = None
    line: int = 0
    col: int = 0

@dataclass
class ExternBlock:
    abi: str
    decls: List[Any]
    line: int = 0
    col: int = 0

@dataclass
class ModuleDecl:
    path: str
    line: int = 0
    col: int = 0

@dataclass
class EntryBlock:
    body: Any
    line: int = 0
    col: int = 0

@dataclass
class Program:
    decls: List[Any]
    line: int = 0
    col: int = 0
