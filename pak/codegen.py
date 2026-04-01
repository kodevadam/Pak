"""Pak → C code generator."""

from typing import Optional, List, Any, Callable
from . import ast


# ── Module → C API mapping ────────────────────────────────────────────────────
# Maps "module.function" → C function name (or callable that takes args list
# and returns a full C call string).

def _passthrough(fn: str):
    """Map directly to a C function name."""
    return fn

def _method_call(c_fn: str, first_arg_addr: bool = False):
    """Generate a C function call, optionally taking address of first arg."""
    def _gen(args):
        if first_arg_addr and args:
            return f'{c_fn}(&{args[0]}, {", ".join(args[1:])})'
        return f'{c_fn}({", ".join(args)})'
    return _gen

# (module, function) → C function name string OR callable(args) → str
MODULE_API: dict = {
    # n64.display
    ('display', 'init'):           'display_init',
    ('display', 'get'):            'display_get',
    ('display', 'show'):           'display_show',
    ('display', 'close'):          'display_close',

    # n64.controller / joypad
    ('controller', 'init'):        'joypad_init',
    ('controller', 'read'):        lambda args: f'joypad_get_status({args[0]})' if args else 'joypad_get_status(0)',
    ('controller', 'poll'):        'joypad_poll',

    # n64.rdpq
    ('rdpq', 'init'):              'rdpq_init',
    ('rdpq', 'close'):             'rdpq_close',
    ('rdpq', 'attach'):            'rdpq_attach',
    ('rdpq', 'attach_clear'):      'rdpq_attach_clear',
    ('rdpq', 'detach'):            'rdpq_detach',
    ('rdpq', 'detach_show'):       'rdpq_detach_show',
    ('rdpq', 'set_mode_standard'): 'rdpq_set_mode_standard',
    ('rdpq', 'set_mode_copy'):     'rdpq_set_mode_copy',
    ('rdpq', 'set_mode_fill'):     'rdpq_set_mode_fill',
    ('rdpq', 'fill_rectangle'):    'rdpq_fill_rectangle',
    ('rdpq', 'sync_full'):         'rdpq_sync_full',
    ('rdpq', 'sync_pipe'):         'rdpq_sync_pipe',
    ('rdpq', 'sync_tile'):         'rdpq_sync_tile',
    ('rdpq', 'sync_load'):         'rdpq_sync_load',
    ('rdpq', 'set_scissor'):       'rdpq_set_scissor',

    # n64.sprite
    ('sprite', 'load'):            'sprite_load',
    ('sprite', 'blit'):            lambda args: (
        f'rdpq_sprite_blit({args[0]}, {args[1]}, {args[2]}, NULL)'
        if len(args) >= 3 else f'rdpq_sprite_blit({", ".join(args)}, NULL)'
    ),

    # n64.timer
    ('timer', 'init'):             'timer_init',
    ('timer', 'delta'):            lambda args: '_pak_delta_time()',
    ('timer', 'get_ticks'):        'get_ticks',

    # n64.audio
    ('audio', 'init'):             'audio_init',
    ('audio', 'close'):            'audio_close',
    ('audio', 'get_buffer'):       'audio_get_buffer',

    # n64.debug
    ('debug', 'log'):              'debugf',
    ('debug', 'assert'):           'assert',

    # n64.dma
    ('dma', 'read'):               'dma_read',
    ('dma', 'write'):              'dma_write',
    ('dma', 'wait'):               'dma_wait',

    # n64.cache
    ('cache', 'writeback'):        'data_cache_hit_writeback',
    ('cache', 'invalidate'):       'data_cache_hit_invalidate',
    ('cache', 'writeback_inv'):    'data_cache_hit_writeback_invalidate',

    # t3d.core
    ('t3d', 'init'):               't3d_init',
    ('t3d', 'destroy'):            't3d_destroy',
    ('t3d', 'frame_start'):        't3d_frame_start',
    ('t3d', 'frame_end'):          'rspq_block_run',
    ('t3d', 'screen_projection'):  't3d_screen_projection',
    ('t3d', 'viewport_create'):    't3d_viewport_create',
    ('t3d', 'viewport_set_projection'): 't3d_viewport_set_projection',

    # t3d.model
    ('t3d', 'model_load'):         't3d_model_load',
    ('t3d', 'model_free'):         't3d_model_free',
    ('t3d', 'model_draw'):         't3d_model_draw',

    # t3d.math
    ('t3d', 'mat4_identity'):      lambda args: f't3d_mat4_identity({_addr(args, 0)})',
    ('t3d', 'mat4_rotate_y'):      lambda args: f't3d_mat4_rotate({_addr(args, 0)}, &(T3DVec3){{{{0,1,0}}}}, {args[1]})',
    ('t3d', 'mat4_rotate_x'):      lambda args: f't3d_mat4_rotate({_addr(args, 0)}, &(T3DVec3){{{{1,0,0}}}}, {args[1]})',
    ('t3d', 'mat4_rotate_z'):      lambda args: f't3d_mat4_rotate({_addr(args, 0)}, &(T3DVec3){{{{0,0,1}}}}, {args[1]})',
    ('t3d', 'mat4_translate'):     lambda args: f't3d_mat4_translate({_addr(args, 0)}, {args[1]}, {args[2]}, {args[3]})',
    ('t3d', 'mat4_scale'):         lambda args: f't3d_mat4_scale({_addr(args, 0)}, {args[1]}, {args[2]}, {args[3]})',

    # t3d.light
    ('t3d', 'light_set_ambient'):  't3d_light_set_ambient',
    ('t3d', 'light_set_directional'): 't3d_light_set_directional',

    # t3d.viewport
    ('t3d', 'viewport_attach'):    't3d_viewport_attach',
    ('t3d', 'viewport_set_fov'):   't3d_viewport_set_fov',
    ('t3d', 'set_camera'):         't3d_set_camera',
    ('t3d', 'look_at'):            't3d_look_at',
}


def _addr(args, i):
    """Return &args[i] if not already a pointer expression."""
    if i < len(args):
        a = args[i]
        if a.startswith('&') or a.startswith('*'):
            return a
        return f'&{a}'
    return 'NULL'


# ── Type mappings ─────────────────────────────────────────────────────────────

PRIMITIVE_TYPES = {
    'i8': 'int8_t',
    'i16': 'int16_t',
    'i32': 'int32_t',
    'i64': 'int64_t',
    'u8': 'uint8_t',
    'u16': 'uint16_t',
    'u32': 'uint32_t',
    'u64': 'uint64_t',
    'f32': 'float',
    'f64': 'double',
    'bool': 'bool',
    'byte': 'uint8_t',
    'fix16.16': 'int32_t',
    'fix10.5': 'int16_t',
    'fix1.15': 'int16_t',
    'Vec2': 'T3DVec2',
    'Vec3': 'T3DVec3',
    'Vec4': 'T3DVec4',
    'Mat4': 'T3DMat4',
    'Str': 'const char *',
    'c_char': 'char',
    'Arena': 'void *',
    'void': 'void',
}

USE_INCLUDES = {
    'n64.display': '#include <display.h>',
    'n64.controller': '#include <joypad.h>',
    'n64.rdpq': '#include <rdpq.h>\n#include <rdpq_gfx.h>',
    'n64.sprite': '#include <rdpq_sprite.h>',
    'n64.audio': '#include <audio.h>\n#include <xm64.h>\n#include <wav64.h>',
    'n64.timer': '#include <n64sys.h>',
    'n64.dma': '#include <dma.h>',
    'n64.cache': '#include <n64sys.h>',
    'n64.eeprom': '#include <eeprom.h>',
    'n64.debug': '#include <debug.h>',
    'n64.math': '#include <n64sys.h>',
    'n64.mem': '#include <malloc.h>',
    't3d.core': '#include <t3d/t3d.h>',
    't3d.model': '#include <t3d/t3dmodel.h>',
    't3d.math': '#include <t3d/t3dmath.h>',
    't3d.anim': '#include <t3d/t3danim.h>',
    't3d.light': '#include <t3d/t3dlight.h>',
    't3d.viewport': '#include <t3d/t3d.h>',
    't3d.skeleton': '#include <t3d/t3dskeleton.h>',
    'n64.surface': '#include <surface.h>',
    't3d.math': '#include <t3d/t3dmath.h>',
}


class CodegenError(Exception):
    pass


class Codegen:
    def __init__(self, filename: str = '<unknown>'):
        self.filename = filename
        self.indent = 0
        self.lines: List[str] = []
        self.includes: List[str] = []
        self.forward_decls: List[str] = []
        self.uses: List[str] = []
        # Track assets
        self.assets: List[ast.AssetDecl] = []
        # Track module name
        self.module_name: str = ''
        # Track function names for forward decl
        self.fn_names: List[str] = []
        # Map variant_name → enum_name for dot-access resolution
        self.enum_variants: dict = {}  # variant_case → enum_name
        # Scope stack: list of {name: type_node} for pointer-member access
        self.scopes: List[dict] = [{}]

    # ── Scope helpers ─────────────────────────────────────────────────────────

    def scope_push(self):
        self.scopes.append({})

    def scope_pop(self):
        self.scopes.pop()

    def scope_set(self, name: str, typ):
        self.scopes[-1][name] = typ

    def scope_get(self, name: str):
        for s in reversed(self.scopes):
            if name in s:
                return s[name]
        return None

    def is_pointer(self, name: str) -> bool:
        """Return True if the variable is a pointer type."""
        t = self.scope_get(name)
        return isinstance(t, ast.TypePointer)

    def emit(self, line: str = ''):
        if line:
            self.lines.append('    ' * self.indent + line)
        else:
            self.lines.append('')

    def emit_raw(self, line: str):
        self.lines.append(line)

    def inc(self):
        self.indent += 1

    def dec(self):
        self.indent -= 1

    def gen_type(self, t) -> str:
        if t is None:
            return 'void'
        if isinstance(t, ast.TypeName):
            return PRIMITIVE_TYPES.get(t.name, t.name)
        if isinstance(t, ast.TypePointer):
            inner = self.gen_type(t.inner)
            q = '' if t.mutable else 'const '
            # Don't add const for mutable pointers
            if t.mutable:
                return f'{inner} *'
            if t.nullable:
                return f'{inner} *'
            return f'{inner} *'
        if isinstance(t, ast.TypeSlice):
            # Slices become pointer + we lose length info in C (simplification)
            return f'{self.gen_type(t.inner)} *'
        if isinstance(t, ast.TypeArray):
            inner = self.gen_type(t.inner)
            size = self.gen_expr(t.size)
            return f'{inner}[{size}]'
        if isinstance(t, ast.TypeResult):
            # Simplified: just use the ok type (errors become out params or return codes)
            return self.gen_type(t.ok)
        if isinstance(t, ast.TypeOption):
            return self.gen_type(t.inner) + ' *'
        if isinstance(t, ast.TypeFn):
            ret = self.gen_type(t.ret) if t.ret else 'void'
            params = ', '.join(self.gen_type(p) for p in t.params)
            return f'{ret} (*)({params})'
        return 'void *'

    def gen_array_decl(self, name: str, t) -> str:
        """Generate 'type name[size]' for array types."""
        if isinstance(t, ast.TypeArray):
            inner = self.gen_type(t.inner)
            size = self.gen_expr(t.size)
            return f'{inner} {name}[{size}]'
        return f'{self.gen_type(t)} {name}'

    def gen_expr(self, e) -> str:
        if e is None:
            return ''
        if isinstance(e, ast.IntLit):
            if e.raw:
                return e.raw
            return str(e.value)
        if isinstance(e, ast.FloatLit):
            return f'{e.value}f'
        if isinstance(e, ast.BoolLit):
            return 'true' if e.value else 'false'
        if isinstance(e, ast.StringLit):
            escaped = e.value.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n')
            return f'"{escaped}"'
        if isinstance(e, ast.NoneLit):
            return 'NULL'
        if isinstance(e, ast.UndefinedLit):
            return '/* undefined */'
        if isinstance(e, ast.Ident):
            return e.name
        if isinstance(e, ast.DotAccess):
            obj_str = self.gen_expr(e.obj)
            if isinstance(e.obj, ast.Ident):
                n = e.obj.name
                # Enum type name access: Direction.up → Direction_up
                if n in self.enum_variants.values():
                    return f'{obj_str}_{e.field}'
                # Enum variant shortcut (field is a known variant)
                if e.field in self.enum_variants:
                    return f'{obj_str}_{e.field}'
                # Module namespace — not a variable, keep as-is (resolved in Call)
                if (n, e.field) in MODULE_API:
                    return f'{obj_str}.{e.field}'  # placeholder; Call handles it
                # Pointer variable: p.field → p->field
                if self.is_pointer(n):
                    return f'{obj_str}->{e.field}'
            # Chained access on a non-ident expression
            return f'{obj_str}.{e.field}'
        if isinstance(e, ast.IndexAccess):
            return f'{self.gen_expr(e.obj)}[{self.gen_expr(e.index)}]'
        if isinstance(e, ast.SliceExpr):
            start = self.gen_expr(e.start) if e.start else '0'
            return f'&{self.gen_expr(e.obj)}[{start}]'
        if isinstance(e, ast.NamedArg):
            return self.gen_expr(e.value)
        if isinstance(e, ast.Call):
            args_strs = [self.gen_expr(a) for a in e.args]
            # Module API call: module.function(args) → C API
            if isinstance(e.func, ast.DotAccess) and isinstance(e.func.obj, ast.Ident):
                mod = e.func.obj.name
                fn = e.func.field
                key = (mod, fn)
                if key in MODULE_API:
                    mapping = MODULE_API[key]
                    if callable(mapping):
                        return mapping(args_strs)
                    return f'{mapping}({", ".join(args_strs)})'
            func = self.gen_expr(e.func)
            args = ', '.join(args_strs)
            return f'{func}({args})'
        if isinstance(e, ast.StructLit):
            fields = ', '.join(f'.{name} = {self.gen_expr(val)}' for name, val in e.fields)
            return f'({e.type_name}){{{fields}}}'
        if isinstance(e, ast.ArrayLit):
            if e.repeat is not None:
                # [val; N] - zero init or repeated value
                val = self.gen_expr(e.elements[0])
                return f'{{/* [{val}; {self.gen_expr(e.repeat)}] */}}'
            elements = ', '.join(self.gen_expr(el) for el in e.elements)
            return f'{{{elements}}}'
        if isinstance(e, ast.UnaryOp):
            if e.op == '!':
                return f'!{self.gen_expr(e.operand)}'
            return f'{e.op}{self.gen_expr(e.operand)}'
        if isinstance(e, ast.BinaryOp):
            left = self.gen_expr(e.left)
            right = self.gen_expr(e.right)
            return f'({left} {e.op} {right})'
        if isinstance(e, ast.Assign):
            return f'{self.gen_expr(e.target)} {e.op} {self.gen_expr(e.value)}'
        if isinstance(e, ast.AddrOf):
            return f'&{self.gen_expr(e.expr)}'
        if isinstance(e, ast.Deref):
            return f'*{self.gen_expr(e.expr)}'
        if isinstance(e, ast.Cast):
            return f'({self.gen_type(e.type)}){self.gen_expr(e.expr)}'
        if isinstance(e, ast.RangeExpr):
            # Used in for loops - handled specially
            start = self.gen_expr(e.start)
            end = self.gen_expr(e.end) if e.end else ''
            return f'{start}..{end}'
        if isinstance(e, ast.EnumVariantAccess):
            # .variant → EnumName_variant if we know the enum
            if e.name in self.enum_variants:
                return f'{self.enum_variants[e.name]}_{e.name}'
            return e.name
        if isinstance(e, ast.CatchExpr):
            # Simplified: just evaluate the expression
            return self.gen_expr(e.expr)
        if isinstance(e, ast.NullCheck):
            return self.gen_expr(e.expr)
        return '/* unknown expr */'

    def gen_program(self, program: ast.Program) -> str:
        # First pass: collect uses, assets, fn names, and enum/variant info
        for decl in program.decls:
            if isinstance(decl, ast.UseDecl):
                self.uses.append(decl.path)
            elif isinstance(decl, ast.AssetDecl):
                self.assets.append(decl)
            elif isinstance(decl, ast.ModuleDecl):
                self.module_name = decl.path
            elif isinstance(decl, ast.FnDecl):
                self.fn_names.append(decl.name)
            elif isinstance(decl, ast.EnumDecl):
                for v in decl.variants:
                    self.enum_variants[v.name] = decl.name
            elif isinstance(decl, ast.VariantDecl):
                for c in decl.cases:
                    self.enum_variants[c.name] = decl.name

        # Build output
        out_lines = []
        out_lines.append(f'/* Generated by Pak Compiler - {self.filename} */')
        out_lines.append('')

        # Standard includes
        out_lines.append('#include <libdragon.h>')
        out_lines.append('#include <stdint.h>')
        out_lines.append('#include <stdbool.h>')
        out_lines.append('#include <string.h>')

        # Module-based includes
        seen_includes = set()
        for use_path in self.uses:
            inc = USE_INCLUDES.get(use_path)
            if inc and inc not in seen_includes:
                out_lines.append(inc)
                seen_includes.add(inc)

        # PakFS header if assets are present
        if self.assets:
            out_lines.append('#include <pakfs.h>')

        # Timer helper if n64.timer is used
        if 'n64.timer' in self.uses:
            out_lines.append('')
            out_lines.append('static uint32_t _pak_last_tick = 0;')
            out_lines.append('static inline float _pak_delta_time(void) {')
            out_lines.append('    uint32_t now = TICKS_READ();')
            out_lines.append('    float dt = (float)TIMER_MICROS(now - _pak_last_tick) / 1000000.0f;')
            out_lines.append('    _pak_last_tick = now;')
            out_lines.append('    return dt;')
            out_lines.append('}')

        out_lines.append('')

        # Asset declarations
        for asset in self.assets:
            out_lines.append(f'/* asset: {asset.name} from "{asset.path}" */')
            out_lines.append(f'static const char *{asset.name}_path = "pak:/{asset.path}";')
        if self.assets:
            out_lines.append('')

        # Generate declarations
        body_lines = []
        has_entry = False
        for decl in program.decls:
            if isinstance(decl, (ast.UseDecl, ast.AssetDecl, ast.ModuleDecl)):
                continue
            result = self.gen_decl(decl)
            if result:
                body_lines.append(result)
                body_lines.append('')
            if isinstance(decl, ast.EntryBlock):
                has_entry = True

        out_lines.extend(body_lines)
        return '\n'.join(out_lines)

    def gen_decl(self, decl) -> str:
        if isinstance(decl, ast.StructDecl):
            return self.gen_struct(decl)
        if isinstance(decl, ast.EnumDecl):
            return self.gen_enum(decl)
        if isinstance(decl, ast.VariantDecl):
            return self.gen_variant(decl)
        if isinstance(decl, ast.FnDecl):
            return self.gen_fn(decl)
        if isinstance(decl, ast.EntryBlock):
            return self.gen_entry(decl)
        if isinstance(decl, ast.ExternBlock):
            return self.gen_extern(decl)
        if isinstance(decl, ast.StaticDecl):
            return self.gen_static_decl(decl)
        if isinstance(decl, ast.LetDecl):
            return self.gen_let_decl_global(decl)
        return f'/* unhandled decl: {type(decl).__name__} */'

    def gen_struct(self, s: ast.StructDecl) -> str:
        attrs = []
        for ann in s.annotations:
            if '@packed' in ann:
                attrs.append('__attribute__((packed))')
            elif '@aligned' in ann:
                n = ann[ann.index('(')+1:ann.index(')')]
                attrs.append(f'__attribute__((aligned({n})))')
        attr_str = ' '.join(attrs)
        lines = [f'typedef struct {{']
        for field in s.fields:
            decl = self.gen_array_decl(field.name, field.type)
            lines.append(f'    {decl};')
        suffix = f' {attr_str}' if attr_str else ''
        lines.append(f'}} {s.name}{suffix};')
        return '\n'.join(lines)

    def gen_enum(self, e: ast.EnumDecl) -> str:
        base = PRIMITIVE_TYPES.get(e.base_type, 'int') if e.base_type else 'int'
        lines = [f'typedef enum {{']
        for v in e.variants:
            if v.value is not None:
                lines.append(f'    {e.name}_{v.name} = {self.gen_expr(v.value)},')
            else:
                lines.append(f'    {e.name}_{v.name},')
        lines.append(f'}} {e.name};')
        return '\n'.join(lines)

    def gen_variant(self, v: ast.VariantDecl) -> str:
        lines = []
        # Generate inner structs for each case
        for case in v.cases:
            if case.fields:
                lines.append(f'typedef struct {{')
                for i, f in enumerate(case.fields):
                    if isinstance(f, tuple):
                        name, typ = f
                        lines.append(f'    {self.gen_array_decl(name, typ)};')
                    else:
                        lines.append(f'    {self.gen_type(f)} field{i};')
                lines.append(f'}} {v.name}_{case.name};')
                lines.append('')

        # Tag enum
        lines.append(f'typedef enum {{')
        for case in v.cases:
            lines.append(f'    {v.name}_tag_{case.name},')
        lines.append(f'}} {v.name}_tag;')
        lines.append('')

        # Tagged union struct
        lines.append(f'typedef struct {{')
        lines.append(f'    {v.name}_tag tag;')
        lines.append(f'    union {{')
        for case in v.cases:
            if case.fields:
                lines.append(f'        {v.name}_{case.name} {case.name};')
        lines.append(f'    }} data;')
        lines.append(f'}} {v.name};')
        return '\n'.join(lines)

    def gen_fn(self, fn: ast.FnDecl, prefix: str = '') -> str:
        lines = []
        annotations = fn.annotations or []

        ret = self.gen_type(fn.ret_type)

        # Build param list
        params = []
        for p in fn.params:
            if isinstance(p.type, ast.TypeArray):
                params.append(self.gen_array_decl(p.name, p.type))
            else:
                params.append(f'{self.gen_type(p.type)} {p.name}')
        param_str = ', '.join(params) if params else 'void'

        # Annotations → C attributes
        attrs = []
        for ann in annotations:
            if ann == '@hot':
                attrs.append('__attribute__((hot))')
            elif ann == '@inline':
                attrs.append('static inline')
            elif ann == '@no_alloc':
                pass  # compile-time check only
            elif ann.startswith('@export'):
                pass  # already has the right name

        name = fn.name
        if prefix:
            name = f'{prefix}_{name}'

        attr_str = ' '.join(attrs)
        if attr_str:
            lines.append(f'{attr_str}')

        if fn.body is None:
            lines.append(f'{ret} {name}({param_str});')
            return '\n'.join(lines)

        lines.append(f'{ret} {name}({param_str}) {{')
        self.scope_push()
        for p in fn.params:
            self.scope_set(p.name, p.type)
        for stmt in fn.body.stmts:
            stmt_str = self.gen_stmt(stmt, indent=1)
            if stmt_str:
                lines.append(stmt_str)
        self.scope_pop()
        lines.append('}')
        return '\n'.join(lines)

    def gen_entry(self, entry: ast.EntryBlock) -> str:
        lines = ['int main(void) {']
        self.scope_push()
        for stmt in entry.body.stmts:
            s = self.gen_stmt(stmt, indent=1)
            if s:
                lines.append(s)
        self.scope_pop()
        lines.append('    return 0;')
        lines.append('}')
        return '\n'.join(lines)

    def gen_extern(self, ext: ast.ExternBlock) -> str:
        lines = [f'/* extern "{ext.abi}" */']
        for decl in ext.decls:
            lines.append(self.gen_fn(decl))
        return '\n'.join(lines)

    def gen_static_decl(self, s: ast.StaticDecl) -> str:
        decl = self.gen_array_decl(s.name, s.type) if s.type else f'auto {s.name}'
        if '@aligned' in ' '.join(s.annotations):
            for ann in s.annotations:
                if '@aligned' in ann:
                    n = ann[ann.index('(')+1:ann.index(')')]
                    decl = f'__attribute__((aligned({n}))) ' + decl
        if '@uncached' in s.annotations:
            decl = '/* @uncached */ ' + decl
        if s.value and not isinstance(s.value, ast.UndefinedLit):
            return f'static {decl} = {self.gen_expr(s.value)};'
        return f'static {decl};'

    def gen_let_decl_global(self, s: ast.LetDecl) -> str:
        decl = self.gen_array_decl(s.name, s.type) if s.type else f'auto {s.name}'
        if s.value and not isinstance(s.value, ast.UndefinedLit):
            return f'{decl} = {self.gen_expr(s.value)};'
        return f'{decl};'

    def gen_stmt(self, stmt, indent: int = 0) -> str:
        pad = '    ' * indent

        if isinstance(stmt, ast.LetDecl):
            return self.gen_let_stmt(stmt, pad)
        if isinstance(stmt, ast.StaticDecl):
            return self.gen_static_stmt(stmt, pad)
        if isinstance(stmt, ast.Return):
            if stmt.value is not None:
                return f'{pad}return {self.gen_expr(stmt.value)};'
            return f'{pad}return;'
        if isinstance(stmt, ast.Break):
            return f'{pad}break;'
        if isinstance(stmt, ast.Continue):
            return f'{pad}continue;'
        if isinstance(stmt, ast.ExprStmt):
            return f'{pad}{self.gen_expr(stmt.expr)};'
        if isinstance(stmt, ast.IfStmt):
            return self.gen_if(stmt, pad, indent)
        if isinstance(stmt, ast.NullCheckStmt):
            return self.gen_null_check(stmt, pad, indent)
        if isinstance(stmt, ast.LoopStmt):
            return self.gen_loop(stmt, pad, indent)
        if isinstance(stmt, ast.WhileStmt):
            return self.gen_while(stmt, pad, indent)
        if isinstance(stmt, ast.ForStmt):
            return self.gen_for(stmt, pad, indent)
        if isinstance(stmt, ast.MatchStmt):
            return self.gen_match(stmt, pad, indent)
        if isinstance(stmt, ast.DeferStmt):
            return self.gen_defer(stmt, pad, indent)
        if isinstance(stmt, ast.StructDecl):
            return self.gen_struct(stmt)
        if isinstance(stmt, ast.EnumDecl):
            return self.gen_enum(stmt)
        if isinstance(stmt, ast.VariantDecl):
            return self.gen_variant(stmt)
        if isinstance(stmt, ast.Block):
            return self.gen_block_inline(stmt, pad, indent)
        return f'{pad}/* unhandled stmt: {type(stmt).__name__} */'

    def gen_let_stmt(self, s: ast.LetDecl, pad: str) -> str:
        annotations = s.annotations or []
        prefix = ''
        if '@aligned' in ' '.join(annotations):
            for ann in annotations:
                if '@aligned' in ann:
                    n = ann[ann.index('(')+1:ann.index(')')]
                    prefix = f'__attribute__((aligned({n}))) '
        if '@dma_safe' in annotations:
            prefix = '__attribute__((aligned(16))) ' + prefix
        if '@uncached' in annotations:
            prefix = '/* @uncached */ ' + prefix

        if s.type:
            decl = self.gen_array_decl(s.name, s.type)
            self.scope_set(s.name, s.type)
        else:
            decl = f'__auto_type {s.name}'
            # Infer pointer type from value if possible
            if isinstance(s.value, ast.AddrOf):
                self.scope_set(s.name, ast.TypePointer(inner=ast.TypeName(name='auto')))

        if s.value is not None and not isinstance(s.value, ast.UndefinedLit):
            val = self.gen_expr(s.value)
            return f'{pad}{prefix}{decl} = {val};'
        elif isinstance(s.value, ast.UndefinedLit):
            return f'{pad}{prefix}{decl}; /* undefined */'
        else:
            return f'{pad}{prefix}{decl};'

    def gen_static_stmt(self, s: ast.StaticDecl, pad: str) -> str:
        annotations = s.annotations or []
        prefix = 'static '
        if '@aligned' in ' '.join(annotations):
            for ann in annotations:
                if '@aligned' in ann:
                    n = ann[ann.index('(')+1:ann.index(')')]
                    prefix += f'__attribute__((aligned({n}))) '
        if s.type:
            decl = self.gen_array_decl(s.name, s.type)
        else:
            decl = f'__auto_type {s.name}'

        if s.value is not None and not isinstance(s.value, ast.UndefinedLit):
            val = self.gen_expr(s.value)
            return f'{pad}{prefix}{decl} = {val};'
        return f'{pad}{prefix}{decl};'

    def gen_if(self, s: ast.IfStmt, pad: str, indent: int) -> str:
        cond = self.gen_expr(s.condition)
        lines = [f'{pad}if ({cond}) {{']
        for stmt in s.then.stmts:
            lines.append(self.gen_stmt(stmt, indent + 1))
        lines.append(f'{pad}}}')
        for ec, eb in s.elif_branches:
            lines.append(f'{pad}else if ({self.gen_expr(ec)}) {{')
            for stmt in eb.stmts:
                lines.append(self.gen_stmt(stmt, indent + 1))
            lines.append(f'{pad}}}')
        if s.else_branch:
            lines.append(f'{pad}else {{')
            for stmt in s.else_branch.stmts:
                lines.append(self.gen_stmt(stmt, indent + 1))
            lines.append(f'{pad}}}')
        return '\n'.join(l for l in lines if l is not None)

    def gen_null_check(self, s: ast.NullCheckStmt, pad: str, indent: int) -> str:
        expr = self.gen_expr(s.expr)
        lines = [f'{pad}if ({expr} != NULL) {{']
        inner_pad = '    ' * (indent + 1)
        lines.append(f'{inner_pad}__typeof__({expr}) {s.binding} = {expr};')
        for stmt in s.then.stmts:
            lines.append(self.gen_stmt(stmt, indent + 1))
        lines.append(f'{pad}}}')
        if s.else_branch:
            lines.append(f'{pad}else {{')
            for stmt in s.else_branch.stmts:
                lines.append(self.gen_stmt(stmt, indent + 1))
            lines.append(f'{pad}}}')
        return '\n'.join(l for l in lines if l is not None)

    def gen_loop(self, s: ast.LoopStmt, pad: str, indent: int) -> str:
        lines = [f'{pad}while (true) {{']
        for stmt in s.body.stmts:
            lines.append(self.gen_stmt(stmt, indent + 1))
        lines.append(f'{pad}}}')
        return '\n'.join(l for l in lines if l is not None)

    def gen_while(self, s: ast.WhileStmt, pad: str, indent: int) -> str:
        cond = self.gen_expr(s.condition)
        lines = [f'{pad}while ({cond}) {{']
        for stmt in s.body.stmts:
            lines.append(self.gen_stmt(stmt, indent + 1))
        lines.append(f'{pad}}}')
        return '\n'.join(l for l in lines if l is not None)

    def gen_for(self, s: ast.ForStmt, pad: str, indent: int) -> str:
        iterable = s.iterable
        inner_pad = '    ' * (indent + 1)
        lines = []

        if isinstance(iterable, ast.RangeExpr):
            start = self.gen_expr(iterable.start)
            end = self.gen_expr(iterable.end) if iterable.end else '0'
            if s.index:
                lines.append(f'{pad}for (int {s.index} = {start}, {s.binding} = {start}; {s.index} < {end}; {s.index}++, {s.binding}++) {{')
            else:
                lines.append(f'{pad}for (int {s.binding} = {start}; {s.binding} < {end}; {s.binding}++) {{')
        elif isinstance(iterable, ast.Call) or isinstance(iterable, ast.DotAccess):
            # for item in collection - use index-based loop
            coll = self.gen_expr(iterable)
            if s.index:
                lines.append(f'{pad}for (int {s.index} = 0; {s.index} < (int)({coll}_len); {s.index}++) {{')
                lines.append(f'{inner_pad}__typeof__(({coll})[0]) {s.binding} = ({coll})[{s.index}];')
            else:
                lines.append(f'{pad}{{')
                lines.append(f'{inner_pad}int _i = 0;')
                lines.append(f'{inner_pad}for (; _i < (int)({coll}_len); _i++) {{')
                lines.append(f'{inner_pad}    __typeof__(({coll})[0]) {s.binding} = ({coll})[_i];')
                # close inner for later
        else:
            coll = self.gen_expr(iterable)
            if s.index:
                lines.append(f'{pad}for (int {s.index} = 0; {s.index} < (int)(sizeof({coll})/sizeof({coll}[0])); {s.index}++) {{')
                lines.append(f'{inner_pad}__typeof__({coll}[0]) {s.binding} = {coll}[{s.index}];')
            else:
                lines.append(f'{pad}for (int _i_{s.binding} = 0; _i_{s.binding} < (int)(sizeof({coll})/sizeof({coll}[0])); _i_{s.binding}++) {{')
                lines.append(f'{inner_pad}__typeof__({coll}[0]) {s.binding} = {coll}[_i_{s.binding}];')

        for stmt in s.body.stmts:
            lines.append(self.gen_stmt(stmt, indent + 1))
        lines.append(f'{pad}}}')
        return '\n'.join(l for l in lines if l is not None)

    def gen_match(self, s: ast.MatchStmt, pad: str, indent: int) -> str:
        expr = self.gen_expr(s.expr)
        inner_pad = '    ' * (indent + 1)
        inner2_pad = '    ' * (indent + 2)
        lines = [f'{pad}switch ({expr}) {{']

        for arm in s.arms:
            pat = arm.pattern
            if isinstance(pat, ast.Ident) and pat.name == '_':
                lines.append(f'{inner_pad}default:')
            elif isinstance(pat, ast.EnumVariantAccess):
                if pat.name in self.enum_variants:
                    lines.append(f'{inner_pad}case {self.enum_variants[pat.name]}_{pat.name}:')
                else:
                    lines.append(f'{inner_pad}case {pat.name}:')
            elif isinstance(pat, ast.DotAccess):
                # EnumName.variant
                variant = pat.field
                obj_name = self.gen_expr(pat.obj)
                lines.append(f'{inner_pad}case {obj_name}_{variant}:')
            elif isinstance(pat, ast.IntLit):
                lines.append(f'{inner_pad}case {pat.value}:')
            elif isinstance(pat, ast.BoolLit):
                lines.append(f'{inner_pad}case {"1" if pat.value else "0"}:')
            else:
                lines.append(f'{inner_pad}case /* {self.gen_expr(pat)} */:')

            # Body
            if isinstance(arm.body, ast.Block):
                for stmt in arm.body.stmts:
                    lines.append(self.gen_stmt(stmt, indent + 2))
            else:
                lines.append(f'{inner2_pad}{self.gen_expr(arm.body)};')
            lines.append(f'{inner2_pad}break;')

        lines.append(f'{pad}}}')
        return '\n'.join(l for l in lines if l is not None)

    def gen_defer(self, s: ast.DeferStmt, pad: str, indent: int) -> str:
        lines = [f'{pad}/* defer: */']
        if isinstance(s.body, ast.Block):
            for stmt in s.body.stmts:
                lines.append(self.gen_stmt(stmt, indent))
        return '\n'.join(lines)

    def gen_block_inline(self, block: ast.Block, pad: str, indent: int) -> str:
        lines = [f'{pad}{{']
        for stmt in block.stmts:
            lines.append(self.gen_stmt(stmt, indent + 1))
        lines.append(f'{pad}}}')
        return '\n'.join(l for l in lines if l is not None)


def generate(program: ast.Program, filename: str = '<unknown>') -> str:
    cg = Codegen(filename)
    return cg.gen_program(program)
