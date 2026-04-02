"""C type → Pak type string mapper (Phase 1).

Maps normalized CType objects to their Pak source representation.
Also maintains a typedef resolution table built during a first pass
over the declarations.
"""

from __future__ import annotations
from typing import Dict, Optional

from .c_ast import (
    CType, CPrimitive, CPointer, CArray, CStruct, CUnion, CEnum,
    CFuncPtr, CTypeRef, CField, CVarDecl, CTypeDef, CStructDecl, CUnionDecl,
)


# ── Primitive type mapping table ──────────────────────────────────────────────

# Maps C primitive type spellings → Pak type names.
# Keys are normalized (sorted/joined words).
_PRIMITIVE_MAP: Dict[str, str] = {
    # void
    'void': 'void',
    # bool
    'bool': 'bool',
    '_Bool': 'bool',

    # char / signed char → i8
    'char': 'i8',
    'signed char': 'i8',
    's8': 'i8',
    'int8_t': 'i8',

    # unsigned char → u8
    'unsigned char': 'u8',
    'u8': 'u8',
    'uint8_t': 'u8',
    'byte': 'u8',

    # short / signed short → i16
    'short': 'i16',
    'short int': 'i16',
    'signed short': 'i16',
    'signed short int': 'i16',
    's16': 'i16',
    'int16_t': 'i16',

    # unsigned short → u16
    'unsigned short': 'u16',
    'unsigned short int': 'u16',
    'u16': 'u16',
    'uint16_t': 'u16',

    # int / signed int → i32
    'int': 'i32',
    'signed': 'i32',
    'signed int': 'i32',
    'long': 'i32',     # on N64/MIPS, long = 32 bits
    'long int': 'i32',
    'signed long': 'i32',
    'signed long int': 'i32',
    's32': 'i32',
    'int32_t': 'i32',
    'ptrdiff_t': 'i32',

    # unsigned int → u32
    'unsigned': 'u32',
    'unsigned int': 'u32',
    'unsigned long': 'u32',
    'unsigned long int': 'u32',
    'u32': 'u32',
    'uint32_t': 'u32',
    'size_t': 'u32',

    # long long → i64
    'long long': 'i64',
    'long long int': 'i64',
    'signed long long': 'i64',
    'signed long long int': 'i64',
    's64': 'i64',
    'int64_t': 'i64',

    # unsigned long long → u64
    'unsigned long long': 'u64',
    'unsigned long long int': 'u64',
    'u64': 'u64',
    'uint64_t': 'u64',

    # float → f32
    'float': 'f32',
    'f32': 'f32',

    # double → f64
    'double': 'f64',
    'long double': 'f64',
    'f64': 'f64',

    # fixed-point (N64 decomp)
    'fix16': 'fix16.16',
    'fixed16': 'fix16.16',
    's16_16': 'fix16.16',
    'q16': 'fix16.16',
    'fix1_15': 'fix1.15',
    's1_15': 'fix1.15',
    'q1_15': 'fix1.15',
    'fix10_5': 'fix10.5',
    's10_5': 'fix10.5',

    # Pak passthrough
    'i8': 'i8',
    'i16': 'i16',
    'i32': 'i32',
    'i64': 'i64',
    'fix16.16': 'fix16.16',
    'fix1.15': 'fix1.15',
    'fix10.5': 'fix10.5',
}


class TypeMapper:
    """Maps CType objects to Pak type strings.

    Build up a typedef table first, then call map_type() to convert.
    """

    def __init__(self):
        # typedef name → CType (allows resolving typedef chains)
        self._typedefs: Dict[str, CType] = {}
        # struct name → ordered list of field names (for named initializer support)
        self._struct_fields: Dict[str, list] = {}

    def register_typedef(self, name: str, typ: CType):
        """Register a typedef so it can be resolved later."""
        self._typedefs[name] = typ

    def register_typedefs_from_decls(self, decls):
        """Walk a list of CDecl objects and register all CTypeDef entries."""
        for decl in decls:
            if isinstance(decl, CTypeDef):
                self.register_typedef(decl.name, decl.typ)

    def register_struct_fields_from_decls(self, decls):
        """Walk decls and record field names for each struct/union (for named initializers)."""
        for decl in decls:
            if isinstance(decl, CStructDecl) and decl.fields:
                self._struct_fields[decl.name] = [f.name for f in decl.fields]
            elif isinstance(decl, CUnionDecl) and decl.fields:
                self._struct_fields[decl.name] = [f.name for f in decl.fields]
            elif isinstance(decl, CTypeDef):
                if isinstance(decl.typ, CStruct) and decl.typ.fields:
                    self._struct_fields[decl.name] = [f.name for f in decl.typ.fields]

    def get_struct_fields(self, name: str) -> list:
        """Return ordered field names for a struct/union, or []."""
        return self._struct_fields.get(name, [])

    def map_type(self, typ: CType, context: str = '') -> str:
        """Convert a CType to its Pak type string.

        context: optional hint for pointer mutability ('param', 'field', etc.)
        """
        return self._map(typ, mutable_hint=False)

    def map_type_mutable(self, typ: CType) -> str:
        """Convert a CType assuming mutable context (e.g. pointer that is written through)."""
        return self._map(typ, mutable_hint=True)

    def _map(self, typ: CType, mutable_hint: bool = False) -> str:
        if isinstance(typ, CPrimitive):
            return self._map_primitive(typ.name)
        elif isinstance(typ, CTypeRef):
            return self._map_typeref(typ.name, mutable_hint)
        elif isinstance(typ, CPointer):
            return self._map_pointer(typ, mutable_hint)
        elif isinstance(typ, CArray):
            return self._map_array(typ)
        elif isinstance(typ, CStruct):
            return typ.name or '_AnonStruct'
        elif isinstance(typ, CUnion):
            return typ.name or '_AnonUnion'
        elif isinstance(typ, CEnum):
            return typ.name or '_AnonEnum'
        elif isinstance(typ, CFuncPtr):
            return self._map_funcptr(typ)
        else:
            return '/* unknown */'

    def _map_primitive(self, name: str) -> str:
        # Normalize whitespace
        normalized = ' '.join(name.split())
        if normalized in _PRIMITIVE_MAP:
            return _PRIMITIVE_MAP[normalized]
        # Try without signed/unsigned prefix for lookup
        return _PRIMITIVE_MAP.get(normalized, normalized)

    def _map_typeref(self, name: str, mutable_hint: bool) -> str:
        # Check if this is a known typedef → resolve
        if name in self._typedefs:
            resolved = self._typedefs[name]
            # For simple primitive aliases just return the mapped name
            if isinstance(resolved, CPrimitive):
                return self._map_primitive(resolved.name)
            # For struct/enum/union typedef aliases, keep the alias name
            # as Pak uses the type name directly
            if isinstance(resolved, (CStruct, CUnion, CEnum)):
                return resolved.name or name
        # Check if it's a primitive spelled as a typedef (s8, u16, etc.)
        if name in _PRIMITIVE_MAP:
            return _PRIMITIVE_MAP[name]
        return name

    def _map_pointer(self, typ: CPointer, mutable_hint: bool) -> str:
        inner = self._map(typ.inner, mutable_hint=False)
        # void * → *u8
        if inner == 'void':
            inner = 'u8'
        if typ.is_const:
            # const T * → *T (immutable pointer in Pak)
            return f'*{inner}'
        else:
            # non-const T * → *mut T if likely written through, else *T
            # Default to *mut T since most C pointers in decomp are mutable
            return f'*mut {inner}'

    def _map_pointer_const(self, typ: CPointer) -> str:
        inner = self._map(typ.inner)
        if inner == 'void':
            inner = 'u8'
        return f'*{inner}'

    def _map_array(self, typ: CArray) -> str:
        inner = self._map(typ.inner)
        if typ.size is not None:
            return f'[{typ.size}]{inner}'
        # Unknown/flexible size → slice
        return f'[]{inner}'

    def _map_funcptr(self, typ: CFuncPtr) -> str:
        ret = self._map(typ.ret)
        params = ', '.join(self._map(p) for p in typ.params)
        if ret == 'void':
            return f'fn({params})'
        return f'fn({params}) -> {ret}'

    def field_type(self, field: CField) -> str:
        """Map a struct field's type to a Pak type string."""
        return self._map(field.typ)

    def is_void(self, typ: CType) -> bool:
        """Return True if this type maps to void."""
        return self._map(typ).strip() == 'void'

    def is_pointer_to(self, typ: CType, type_name: str) -> bool:
        """Return True if typ is a pointer to a struct/typedef named type_name."""
        if isinstance(typ, CPointer):
            inner = typ.inner
            if isinstance(inner, CTypeRef):
                return inner.name == type_name
            if isinstance(inner, CStruct):
                return inner.name == type_name
        return False
