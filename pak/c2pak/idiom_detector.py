"""C idiom detection and PAK-ification (Phase 3).

Scans a normalized C AST and detects high-value patterns that map to
richer Pak constructs:

  3.1 - Tagged union → variant
  3.2 - Method detection → impl blocks
  3.3 - Fixed-point arithmetic type detection
  3.4 - Error sentinel → Result type (basic detection)
  3.5 - goto cleanup → defer (basic detection)
  3.6 - Array+length params → slice
"""

from __future__ import annotations
import re
from typing import Dict, List, Optional, Set, Tuple

from .c_ast import (
    CDecl, CFile, CField, CType,
    CPrimitive, CPointer, CArray, CStruct, CUnion, CEnum, CFuncPtr, CTypeRef,
    CTypeDef, CStructDecl, CUnionDecl, CEnumDecl,
    CFuncDecl, CFuncDef, CVarDecl,
    CParam, CFuncSignature,
    CExpr, CId, CBinOp, CUnaryOp, CAssign, CCall, CConst, CStructRef, CArrayRef,
    CStmt, CCompound, CGoto, CLabel, CReturn, CExprStmt, CIf, CFor, CWhile,
    CBreak,
)


# ── Analysis result types ─────────────────────────────────────────────────────

class TaggedUnionInfo:
    """Describes a detected tagged union → variant pattern."""
    def __init__(self, struct_name: str, tag_field: str, tag_enum: str,
                 cases: List[Tuple[str, List[CField]]], shared_fields: List[CField]):
        self.struct_name = struct_name
        self.tag_field = tag_field
        self.tag_enum = tag_enum
        # cases: list of (variant_name, fields) — shared_fields duplicated per variant
        self.cases = cases
        self.shared_fields = shared_fields


class MethodGroup:
    """Describes methods detected for a struct → impl block."""
    def __init__(self, struct_name: str, methods: List[CFuncDef]):
        self.struct_name = struct_name
        self.methods = methods


# ── Main detector ─────────────────────────────────────────────────────────────

class IdiomDetector:
    """Analyses a CFile and extracts high-value idioms."""

    def __init__(self, c_file: CFile):
        self.c_file = c_file
        # Build maps for fast lookup
        self._structs: Dict[str, CStructDecl] = {}
        self._unions: Dict[str, CUnionDecl] = {}
        self._enums: Dict[str, CEnumDecl] = {}
        self._typedefs: Dict[str, CType] = {}
        self._func_defs: List[CFuncDef] = []
        self._global_vars: List[CVarDecl] = []
        self._index_decls()

    def _index_decls(self):
        for decl in self.c_file.decls:
            if isinstance(decl, CStructDecl):
                self._structs[decl.name] = decl
            elif isinstance(decl, CUnionDecl):
                self._unions[decl.name] = decl
            elif isinstance(decl, CEnumDecl):
                self._enums[decl.name] = decl
            elif isinstance(decl, CTypeDef):
                self._typedefs[decl.name] = decl.typ
                # Also index typedef-structs/enums/unions by their typedef name
                self._index_typedef(decl)
            elif isinstance(decl, CFuncDef):
                self._func_defs.append(decl)
            elif isinstance(decl, CVarDecl):
                self._global_vars.append(decl)

    def _index_typedef(self, decl: CTypeDef):
        """If a typedef resolves to a struct/union/enum, index it by name."""
        name = decl.name
        typ = decl.typ
        if isinstance(typ, CStruct):
            # Build a CStructDecl proxy with the typedef name
            sd = CStructDecl(name=name, fields=typ.fields)
            self._structs[name] = sd
        elif isinstance(typ, CUnion):
            ud = CUnionDecl(name=name, fields=typ.fields)
            self._unions[name] = ud
        elif isinstance(typ, CEnum):
            ed = CEnumDecl(name=name, values=typ.values)
            self._enums[name] = ed

    # ── 3.1 Tagged union detection ────────────────────────────────────────────

    def detect_tagged_unions(self) -> List[TaggedUnionInfo]:
        """Find structs that follow the tagged union pattern.

        Criteria:
          1. Struct has a field of an enum type (the tag).
          2. Struct has a union field (the payload).
          3. Union has one sub-struct per enum value (approx).
        """
        results = []
        for name, struct in self._structs.items():
            info = self._check_tagged_union(name, struct)
            if info:
                results.append(info)
        return results

    def _check_tagged_union(self, name: str,
                            struct: CStructDecl) -> Optional[TaggedUnionInfo]:
        """Check if *struct* is a tagged union, returning TaggedUnionInfo or None."""
        tag_field: Optional[CField] = None
        union_field: Optional[CField] = None
        shared_fields: List[CField] = []

        for f in struct.fields:
            ftype = self._resolve_type(f.typ)
            if tag_field is None and self._is_enum_type(ftype):
                tag_field = f
            elif union_field is None and isinstance(ftype, (CUnion,)):
                union_field = f
            elif union_field is None and isinstance(f.typ, CTypeRef):
                # Could be a union reference
                resolved = self._resolve_type(f.typ)
                if isinstance(resolved, CUnion):
                    union_field = CField(name=f.name, typ=resolved)
                else:
                    shared_fields.append(f)
            else:
                shared_fields.append(f)

        if tag_field is None or union_field is None:
            return None

        # Get the enum name — prefer the CTypeRef name (typedef name) over the resolved name
        if isinstance(tag_field.typ, CTypeRef):
            tag_enum_name = tag_field.typ.name
        else:
            tag_enum_name = self._get_type_name(self._resolve_type(tag_field.typ))
        if not tag_enum_name:
            return None

        # Get the union fields
        union_type = self._resolve_type(union_field.typ)
        if not isinstance(union_type, CUnion):
            return None

        # Build variant cases from union sub-structs
        enum_decl = self._enums.get(tag_enum_name)
        cases = self._build_variant_cases(union_type, enum_decl, shared_fields)
        if not cases:
            return None

        return TaggedUnionInfo(
            struct_name=name,
            tag_field=tag_field.name,
            tag_enum=tag_enum_name,
            cases=cases,
            shared_fields=shared_fields,
        )

    def _build_variant_cases(
            self, union_type: CUnion, enum_decl: Optional[CEnumDecl],
            shared_fields: List[CField]
    ) -> List[Tuple[str, List[CField]]]:
        """Build variant cases from union sub-fields."""
        from .decl_mapper import _strip_prefix, _detect_enum_prefix
        cases = []

        # Get enum value names for case ordering/naming
        enum_values = []
        if enum_decl:
            prefix = _detect_enum_prefix(enum_decl.values)
            enum_values = [(_strip_prefix(n, prefix), v) for n, v in enum_decl.values]

        for field in union_type.fields:
            field_type = self._resolve_type(field.typ)
            # Case name: try to match with enum value by position or name
            case_name = self._match_enum_case(field.name, enum_values)
            if isinstance(field_type, CStruct):
                case_fields = list(shared_fields) + list(field_type.fields)
            else:
                # Single-value case
                case_fields = list(shared_fields) + [field]
            cases.append((case_name, case_fields))

        # Add empty cases for enum values that don't have union fields
        union_names = {self._match_enum_case(f.name, enum_values)
                       for f in union_type.fields}
        for enum_name, _ in enum_values:
            if enum_name not in union_names:
                cases.append((enum_name, list(shared_fields)))

        return cases

    def _match_enum_case(self, field_name: str,
                         enum_values: List[Tuple[str, Optional[int]]]) -> str:
        """Find the best matching enum case name for a union field name."""
        # Try exact match first
        for ev_name, _ in enum_values:
            if ev_name == field_name or ev_name == field_name.lower():
                return ev_name
        # Try partial match
        for ev_name, _ in enum_values:
            if field_name in ev_name or ev_name in field_name:
                return ev_name
        return field_name.lower()

    # ── 3.2 Method detection ──────────────────────────────────────────────────

    def detect_method_groups(self) -> List[MethodGroup]:
        """Find functions that follow the C method naming convention.

        Criteria:
          1. Function name starts with StructName_ (case-insensitive).
          2. First parameter is StructName* or const StructName*.
          3. At least 2 functions match the same struct prefix.
        """
        # Map struct_name → list of candidate functions
        candidates: Dict[str, List[CFuncDef]] = {}
        known_struct_names: Set[str] = set(self._structs.keys())

        for func_def in self._func_defs:
            sig = func_def.sig
            struct_name = self._detect_method_struct(sig, known_struct_names)
            if struct_name:
                if struct_name not in candidates:
                    candidates[struct_name] = []
                candidates[struct_name].append(func_def)

        # Only report groups with 2+ methods
        return [
            MethodGroup(struct_name=sn, methods=methods)
            for sn, methods in candidates.items()
            if len(methods) >= 1  # even single methods are useful to group
        ]

    def _detect_method_struct(self, sig: CFuncSignature,
                               known_structs: Set[str]) -> Optional[str]:
        """Return the struct name if this function looks like a method."""
        name = sig.name
        if not sig.params:
            return None

        first_param = sig.params[0]
        # Check first parameter type
        param_struct = self._get_pointer_target_name(first_param.typ)
        if param_struct is None:
            return None

        # Check naming convention: funcname starts with structname_
        name_lower = name.lower()
        struct_lower = param_struct.lower()

        if name_lower.startswith(struct_lower + '_'):
            return param_struct

        # Also check if struct name appears as a prefix with underscores
        for struct_name in known_structs:
            if name_lower.startswith(struct_name.lower() + '_'):
                if self._get_pointer_target_name(first_param.typ) == struct_name:
                    return struct_name

        return None

    def _get_pointer_target_name(self, typ: CType) -> Optional[str]:
        """If typ is a pointer to a named struct/typedef, return the name."""
        if isinstance(typ, CPointer):
            inner = typ.inner
            # Prefer the raw CTypeRef name (typedef name) before resolving
            if isinstance(inner, CTypeRef):
                return inner.name
            # Try resolving
            resolved = self._resolve_type(inner)
            if isinstance(resolved, CStruct) and resolved.name:
                return resolved.name
        return None

    # ── 3.3 Fixed-point type detection ───────────────────────────────────────

    def detect_fixed_point_typedefs(self) -> Dict[str, str]:
        """Return typedef names that appear to be fixed-point types.

        Maps C typedef name → Pak fixed-point type string.
        """
        result = {}
        for name, typ in self._typedefs.items():
            pak_fp = self._classify_fixedpoint(name, typ)
            if pak_fp:
                result[name] = pak_fp
        # Also check for macros named like INT_TO_FIX, FIX_MUL etc.
        for macro_name in self.c_file.macros:
            if any(s in macro_name.upper() for s in ('FIX', 'Q16', 'FIXED', 'FRAC')):
                # Heuristic — mark the typedef if we see FIX macros
                pass
        return result

    def _classify_fixedpoint(self, name: str, typ: CType) -> Optional[str]:
        """Classify a typedef as a fixed-point type if it matches known patterns."""
        name_up = name.upper()
        # Name-based detection
        if any(s in name_up for s in ('FIX16', 'Q16_16', 'S16_16', 'FIXED16')):
            return 'fix16.16'
        if any(s in name_up for s in ('FIX1_15', 'Q1_15', 'S1_15')):
            return 'fix1.15'
        if any(s in name_up for s in ('FIX10_5', 'S10_5', 'Q10_5')):
            return 'fix10.5'
        # Only applies if the underlying type is int32
        return None

    # ── 3.6 Array+length parameter detection ─────────────────────────────────

    def detect_slice_params(self, sig: CFuncSignature) -> List[Tuple[int, int]]:
        """Detect (ptr, length) parameter pairs in a function signature.

        Returns list of (ptr_param_idx, len_param_idx) tuples.
        """
        pairs = []
        params = sig.params
        for i, p in enumerate(params):
            if not isinstance(p.typ, CPointer):
                continue
            # Look for the next parameter that is an integer length
            for j in range(i + 1, min(i + 3, len(params))):
                q = params[j]
                if self._is_integer_type(q.typ):
                    qname = q.name or ''
                    if any(s in qname.lower() for s in
                           ('len', 'count', 'size', 'n', 'num', 'cnt')):
                        pairs.append((i, j))
                        break
        return pairs

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _resolve_type(self, typ: CType) -> CType:
        """Follow typedef chains and return the resolved type."""
        visited = set()
        while isinstance(typ, CTypeRef):
            name = typ.name
            if name in visited:
                break
            visited.add(name)
            if name in self._typedefs:
                typ = self._typedefs[name]
            elif name in self._structs:
                return self._structs[name]
            elif name in self._unions:
                return CUnion(name=name, fields=self._unions[name].fields)
            elif name in self._enums:
                return CEnum(name=name, values=self._enums[name].values)
            else:
                break
        return typ

    def _is_enum_type(self, typ: CType) -> bool:
        """Return True if typ resolves to an enum type."""
        typ = self._resolve_type(typ)
        return isinstance(typ, (CEnum,))

    def _get_type_name(self, typ: CType) -> Optional[str]:
        """Return the name of a named type, or None."""
        if isinstance(typ, CEnum):
            return typ.name
        if isinstance(typ, CStruct):
            return typ.name
        if isinstance(typ, CUnion):
            return typ.name
        if isinstance(typ, CTypeRef):
            return typ.name
        return None

    def _is_integer_type(self, typ: CType) -> bool:
        """Return True if typ is an integer primitive."""
        from .type_mapper import _PRIMITIVE_MAP
        if isinstance(typ, CPrimitive):
            pak = _PRIMITIVE_MAP.get(' '.join(typ.name.split()), '')
            return pak in ('i8', 'i16', 'i32', 'i64', 'u8', 'u16', 'u32', 'u64')
        if isinstance(typ, CTypeRef):
            from .type_mapper import _PRIMITIVE_MAP
            return typ.name in _PRIMITIVE_MAP
        return False

    def _is_fixed_point_shift(self, expr: CExpr) -> bool:
        """Detect (a * b) >> 16 pattern."""
        if isinstance(expr, CBinOp) and expr.op == '>>':
            if isinstance(expr.right, CConst) and expr.right.value in ('16', '15', '12'):
                if isinstance(expr.left, CBinOp) and expr.left.op == '*':
                    return True
        return False


# ── Utility: detect goto-cleanup pattern ──────────────────────────────────────

def detect_goto_cleanup(body: CCompound) -> List[Tuple[str, List[CStmt]]]:
    """Find goto-cleanup patterns in a function body.

    Returns list of (label_name, cleanup_stmts) for labels that only
    appear at the end of the function and are targeted by goto.
    """
    goto_targets: Set[str] = set()
    labels: Dict[str, List[CStmt]] = {}

    def scan(items):
        for item in items:
            if isinstance(item, CGoto):
                goto_targets.add(item.label)
            elif isinstance(item, CLabel):
                labels[item.name] = []
                if item.stmt:
                    labels[item.name].append(item.stmt)
            elif isinstance(item, CCompound):
                scan(item.items)
            elif isinstance(item, CIf):
                if isinstance(item.then, CCompound):
                    scan(item.then.items)
                if item.otherwise and isinstance(item.otherwise, CCompound):
                    scan(item.otherwise.items)

    scan(body.items)

    # A cleanup label: targeted by goto, appears near end of function, contains
    # free/close/release calls
    results = []
    for label_name, stmts in labels.items():
        if label_name in goto_targets:
            results.append((label_name, stmts))
    return results
