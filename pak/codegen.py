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

    # t3d.anim — skeletal animation
    ('t3d', 'anim_create'):        't3d_anim_create',
    ('t3d', 'anim_destroy'):       't3d_anim_destroy',
    ('t3d', 'anim_set_playing'):   't3d_anim_set_playing',
    ('t3d', 'anim_set_looping'):   't3d_anim_set_looping',
    ('t3d', 'anim_set_speed'):     't3d_anim_set_speed',
    ('t3d', 'anim_update'):        't3d_anim_update',
    ('t3d', 'anim_attach'):        't3d_anim_attach',

    # t3d.skeleton
    ('t3d', 'skeleton_create'):    't3d_skeleton_create',
    ('t3d', 'skeleton_destroy'):   't3d_skeleton_destroy',
    ('t3d', 'skeleton_update'):    't3d_skeleton_update',
    ('t3d', 'skeleton_draw'):      't3d_skeleton_draw',

    # n64.rumble — Rumble Pak
    ('rumble', 'init'):            'rumble_init',
    ('rumble', 'start'):           'rumble_start',
    ('rumble', 'stop'):            'rumble_stop',
    ('rumble', 'is_plugged'):      lambda args: f'(joypad_get_accessory_type({args[0] if args else "0"}) == JOYPAD_ACCESSORY_TYPE_RUMBLE_PAK)',

    # n64.cpak — Controller Pak (memory card)
    ('cpak', 'init'):              'cpak_init',
    ('cpak', 'is_plugged'):        'cpak_is_plugged',
    ('cpak', 'is_formatted'):      'cpak_is_formatted',
    ('cpak', 'format'):            'cpak_format',
    ('cpak', 'read_sector'):       'cpak_read_sector',
    ('cpak', 'write_sector'):      'cpak_write_sector',
    ('cpak', 'get_free_space'):    'cpak_get_free_space',

    # n64.tpak — Transfer Pak (GB/GBC cartridge adapter)
    ('tpak', 'init'):              'tpak_init',
    ('tpak', 'set_power'):         'tpak_set_power',
    ('tpak', 'get_status'):        'tpak_get_status',
    ('tpak', 'read'):              'tpak_read',
    ('tpak', 'write'):             'tpak_write',

    # n64.backup — Save memory (EEPROM / SRAM / FlashRAM unified API)
    ('backup', 'type'):            'backup_type',
    ('backup', 'read'):            'backup_read',
    ('backup', 'write'):           'backup_write',
    ('backup', 'size'):            'backup_size',

    # n64.eeprom — Direct EEPROM access
    ('eeprom', 'init'):            'eeprom_init',
    ('eeprom', 'read'):            'eeprom_read',
    ('eeprom', 'write'):           'eeprom_write',

    # n64.sram — SRAM save memory
    ('sram', 'read'):              'sram_read',
    ('sram', 'write'):             'sram_write',

    # n64.flashram — FlashRAM save memory
    ('flashram', 'read'):          'flashram_read',
    ('flashram', 'write'):         'flashram_write',
    ('flashram', 'erase_sector'):  'flashram_erase_sector',

    # n64.rtc — Real-Time Clock (cartridge RTC, e.g. Pokémon Stadium)
    ('rtc', 'init'):               'rtc_init',
    ('rtc', 'get'):                'rtc_get',
    ('rtc', 'set'):                'rtc_set',
    ('rtc', 'is_stopped'):         'rtc_is_stopped',
    ('rtc', 'is_running'):         lambda args: '!rtc_is_stopped()',

    # n64.mouse — N64 Mouse accessory
    ('mouse', 'init'):             'joypad_init',
    ('mouse', 'poll'):             'joypad_poll',
    ('mouse', 'get_delta_x'):      lambda args: f'joypad_get_axis_pressed({args[0] if args else "0"}, JOYPAD_AXIS_STICK_X)',
    ('mouse', 'get_delta_y'):      lambda args: f'joypad_get_axis_pressed({args[0] if args else "0"}, JOYPAD_AXIS_STICK_Y)',
    ('mouse', 'get_buttons'):      lambda args: f'joypad_get_buttons_pressed({args[0] if args else "0"})',

    # n64.vru — Voice Recognition Unit
    ('vru', 'init'):               'vru_init',
    ('vru', 'close'):              'vru_close',
    ('vru', 'read_word'):          'vru_read_word',
    ('vru', 'write_word_list'):    'vru_write_word_list',
    ('vru', 'is_ready'):           'vru_is_ready',

    # n64.system — Expansion Pak, memory, CPU timing
    ('system', 'memory_size'):     'get_memory_size',
    ('system', 'has_expansion'):   lambda args: '(get_memory_size() > 0x400000)',
    ('system', 'ticks'):           lambda args: 'TICKS_READ()',
    ('system', 'ticks_to_ms'):     lambda args: f'TICKS_TO_MS({args[0]})',
    ('system', 'reset'):           lambda args: 'n64sys_reset()',
    ('system', 'tv_type'):         lambda args: 'sys_tv_type()',

    # n64.disk — 64DD disk drive
    ('disk', 'init'):              'disk_init',
    ('disk', 'close'):             'disk_close',
    ('disk', 'read_sector'):       'disk_read_sector',
    ('disk', 'write_sector'):      'disk_write_sector',
    ('disk', 'get_disk_type'):     'disk_get_disk_type',
    ('disk', 'is_present'):        'disk_is_present',

    # n64.rsp — RSP microcode / RSPQ command queue
    ('rsp', 'init'):               'rspq_init',
    ('rsp', 'close'):              'rspq_close',
    ('rsp', 'wait'):               'rspq_wait',
    ('rsp', 'syncpoint_new'):      'rspq_syncpoint_new',
    ('rsp', 'syncpoint_check'):    'rspq_syncpoint_check',
    ('rsp', 'block_begin'):        'rspq_block_begin',
    ('rsp', 'block_end'):          'rspq_block_end',
    ('rsp', 'block_run'):          'rspq_block_run',
    ('rsp', 'block_free'):         'rspq_block_free',

    # n64.rdpq.tex — Texture loading helpers
    ('rdpq_tex', 'upload'):        'rdpq_tex_upload',
    ('rdpq_tex', 'upload_sub'):    'rdpq_tex_upload_sub',
    ('rdpq_tex', 'multi_begin'):   'rdpq_tex_multi_begin',
    ('rdpq_tex', 'multi_end'):     'rdpq_tex_multi_end',

    # n64.rdpq.font — Font / text rendering
    ('rdpq_font', 'load'):         'rdpq_font_load',
    ('rdpq_font', 'free'):         'rdpq_font_free',
    ('rdpq_font', 'draw_text'):    'rdpq_text_print',
    ('rdpq_font', 'measure'):      'rdpq_text_measure',
    ('rdpq_font', 'register'):     'rdpq_font_register',

    # n64.rdpq.mode — Blending / combine modes
    ('rdpq_mode', 'push'):         'rdpq_mode_push',
    ('rdpq_mode', 'pop'):          'rdpq_mode_pop',
    ('rdpq_mode', 'standard'):     'rdpq_set_mode_standard',
    ('rdpq_mode', 'copy'):         'rdpq_set_mode_copy',
    ('rdpq_mode', 'zbuf'):         lambda args: f'rdpq_mode_zbuf(true, {args[0] if args else "true"})',
    ('rdpq_mode', 'blending'):     lambda args: f'rdpq_mode_blending({args[0] if args else "RDPQ_BLENDING_MULTIPLY"})',
    ('rdpq_mode', 'antialias'):    lambda args: f'rdpq_mode_antialias({args[0] if args else "AA_STANDARD"})',

    # n64.audio.mixer — Software mixer
    ('mixer', 'init'):             'mixer_init',
    ('mixer', 'close'):            'mixer_close',
    ('mixer', 'ch_play'):          'mixer_ch_play',
    ('mixer', 'ch_stop'):          'mixer_ch_stop',
    ('mixer', 'ch_set_vol'):       'mixer_ch_set_vol',
    ('mixer', 'ch_set_freq'):      'mixer_ch_set_freq',
    ('mixer', 'poll'):             'audio_poll',

    # n64.audio.xm — XM tracker music
    ('xm64', 'open'):              'xm64player_open',
    ('xm64', 'close'):             'xm64player_close',
    ('xm64', 'play'):              'xm64player_play',
    ('xm64', 'stop'):              'xm64player_stop',
    ('xm64', 'set_vol'):           'xm64player_set_vol',

    # n64.audio.wav — WAV sample playback
    ('wav64', 'open'):             'wav64_open',
    ('wav64', 'close'):            'wav64_close',
    ('wav64', 'play'):             'wav64_play',
    ('wav64', 'set_loop'):         'wav64_set_loop',

    # n64.surface — Off-screen surfaces / render targets
    ('surface', 'alloc'):          'surface_alloc',
    ('surface', 'free'):           'surface_free',
    ('surface', 'make_sub'):       'surface_make_sub',

    # n64.math — Fixed-point / vector math helpers
    ('math', 'abs_i32'):           lambda args: f'abs({args[0]})',
    ('math', 'min_i32'):           lambda args: f'MIN({args[0]}, {args[1]})',
    ('math', 'max_i32'):           lambda args: f'MAX({args[0]}, {args[1]})',
    ('math', 'clamp_i32'):         lambda args: f'CLAMP({args[0]}, {args[1]}, {args[2]})',
    ('math', 'sin_f'):             lambda args: f'sinf({args[0]})',
    ('math', 'cos_f'):             lambda args: f'cosf({args[0]})',
    ('math', 'sqrt_f'):            lambda args: f'sqrtf({args[0]})',
    ('math', 'atan2_f'):           lambda args: f'atan2f({args[0]}, {args[1]})',
    ('math', 'lerp_f'):            lambda args: f'({args[0]} + ({args[1]} - {args[0]}) * {args[2]})',
    ('math', 'fix_to_f'):          lambda args: f'((float)({args[0]}) / 65536.0f)',
    ('math', 'f_to_fix'):          lambda args: f'((int32_t)(({args[0]}) * 65536.0f))',

    # Aliases for nested module keys — allow `mixer.ch_play(...)` etc.
    ('mixer', 'init'):             'mixer_init',
    ('mixer', 'close'):            'mixer_close',
    ('mixer', 'ch_play'):          'mixer_ch_play',
    ('mixer', 'ch_stop'):          'mixer_ch_stop',
    ('mixer', 'ch_set_vol'):       'mixer_ch_set_vol',
    ('mixer', 'ch_set_freq'):      'mixer_ch_set_freq',
    ('mixer', 'poll'):             'audio_poll',

    ('xm64', 'open'):              'xm64player_open',
    ('xm64', 'close'):             'xm64player_close',
    ('xm64', 'play'):              'xm64player_play',
    ('xm64', 'stop'):              'xm64player_stop',
    ('xm64', 'set_vol'):           'xm64player_set_vol',

    ('wav64', 'open'):             'wav64_open',
    ('wav64', 'close'):            'wav64_close',
    ('wav64', 'play'):             'wav64_play',
    ('wav64', 'set_loop'):         'wav64_set_loop',

    ('rdpq_tex', 'upload'):        'rdpq_tex_upload',
    ('rdpq_tex', 'upload_sub'):    'rdpq_tex_upload_sub',
    ('rdpq_tex', 'multi_begin'):   'rdpq_tex_multi_begin',
    ('rdpq_tex', 'multi_end'):     'rdpq_tex_multi_end',

    ('rdpq_font', 'load'):         'rdpq_font_load',
    ('rdpq_font', 'free'):         'rdpq_font_free',
    ('rdpq_font', 'draw_text'):    'rdpq_text_print',
    ('rdpq_font', 'measure'):      'rdpq_text_measure',
    ('rdpq_font', 'register'):     'rdpq_font_register',

    ('rdpq_mode', 'push'):         'rdpq_mode_push',
    ('rdpq_mode', 'pop'):          'rdpq_mode_pop',
    ('rdpq_mode', 'standard'):     'rdpq_set_mode_standard',
    ('rdpq_mode', 'copy'):         'rdpq_set_mode_copy',
    ('rdpq_mode', 'zbuf'):         lambda args: f'rdpq_mode_zbuf(true, {args[0] if args else "true"})',
    ('rdpq_mode', 'blending'):     lambda args: f'rdpq_mode_blending({args[0] if args else "RDPQ_BLENDING_MULTIPLY"})',
    ('rdpq_mode', 'antialias'):    lambda args: f'rdpq_mode_antialias({args[0] if args else "AA_STANDARD"})',

    ('sram', 'read'):              'sram_read',
    ('sram', 'write'):             'sram_write',

    ('flashram', 'read'):          'flashram_read',
    ('flashram', 'write'):         'flashram_write',
    ('flashram', 'erase_sector'):  'flashram_erase_sector',

    ('eeprom', 'init'):            'eeprom_init',
    ('eeprom', 'read'):            'eeprom_read',
    ('eeprom', 'write'):           'eeprom_write',

    ('surface', 'alloc'):          'surface_alloc',
    ('surface', 'free'):           'surface_free',
    ('surface', 'make_sub'):       'surface_make_sub',

    ('rsp', 'init'):               'rspq_init',
    ('rsp', 'close'):              'rspq_close',
    ('rsp', 'wait'):               'rspq_wait',
    ('rsp', 'syncpoint_new'):      'rspq_syncpoint_new',
    ('rsp', 'syncpoint_check'):    'rspq_syncpoint_check',
    ('rsp', 'block_begin'):        'rspq_block_begin',
    ('rsp', 'block_end'):          'rspq_block_end',
    ('rsp', 'block_run'):          'rspq_block_run',
    ('rsp', 'block_free'):         'rspq_block_free',

    ('disk', 'init'):              'disk_init',
    ('disk', 'close'):             'disk_close',
    ('disk', 'read_sector'):       'disk_read_sector',
    ('disk', 'write_sector'):      'disk_write_sector',
    ('disk', 'get_disk_type'):     'disk_get_disk_type',
    ('disk', 'is_present'):        'disk_is_present',
}


def _addr(args, i):
    """Return &args[i] if not already a pointer expression."""
    if i < len(args):
        a = args[i]
        if a.startswith('&') or a.startswith('*'):
            return a
        return f'&{a}'
    return 'NULL'


_FIXPOINT_SHIFTS = {'fix16.16': 16, 'fix10.5': 5, 'fix1.15': 15}

def _fixpoint_shift(typ) -> int:
    """Return the fractional bit count for a fixed-point type, or 0."""
    if isinstance(typ, ast.TypeName):
        return _FIXPOINT_SHIFTS.get(typ.name, 0)
    return 0


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
    # Core display / rendering
    'n64.display':      '#include <display.h>',
    'n64.controller':   '#include <joypad.h>',
    'n64.rdpq':         '#include <rdpq.h>\n#include <rdpq_gfx.h>',
    'n64.sprite':       '#include <rdpq_sprite.h>',
    'n64.surface':      '#include <surface.h>',

    # Audio
    'n64.audio':        '#include <audio.h>\n#include <xm64.h>\n#include <wav64.h>',
    'n64.mixer':        '#include <audio.h>\n#include <mixer.h>',
    'n64.xm64':         '#include <xm64.h>',
    'n64.wav64':        '#include <wav64.h>',

    # System
    'n64.timer':        '#include <n64sys.h>',
    'n64.system':       '#include <n64sys.h>',
    'n64.dma':          '#include <dma.h>',
    'n64.cache':        '#include <n64sys.h>',
    'n64.debug':        '#include <debug.h>',
    'n64.math':         '#include <n64sys.h>\n#include <math.h>',
    'n64.mem':          '#include <malloc.h>',
    'n64.rsp':          '#include <rspq.h>',

    # Save memory
    'n64.eeprom':       '#include <eeprom.h>',
    'n64.backup':       '#include <backup.h>',
    'n64.sram':         '#include <backup.h>',
    'n64.flashram':     '#include <backup.h>',

    # RDP texture / font / mode helpers
    'n64.rdpq_tex':     '#include <rdpq_tex.h>',
    'n64.rdpq_font':    '#include <rdpq_font.h>\n#include <rdpq_text.h>',
    'n64.rdpq_mode':    '#include <rdpq_mode.h>',

    # Accessories
    'n64.rumble':       '#include <joypad.h>\n#include <rumble.h>',
    'n64.cpak':         '#include <cpak.h>',
    'n64.tpak':         '#include <tpak.h>',
    'n64.mouse':        '#include <joypad.h>',
    'n64.vru':          '#include <vru.h>',
    'n64.rtc':          '#include <rtc.h>',

    # 64DD disk drive
    'n64.disk':         '#include <disk.h>',

    # Tiny3D
    't3d.core':         '#include <t3d/t3d.h>',
    't3d.model':        '#include <t3d/t3dmodel.h>',
    't3d.math':         '#include <t3d/t3dmath.h>',
    't3d.anim':         '#include <t3d/t3danim.h>',
    't3d.light':        '#include <t3d/t3dlight.h>',
    't3d.viewport':     '#include <t3d/t3d.h>',
    't3d.skeleton':     '#include <t3d/t3dskeleton.h>',
}


class CodegenError(Exception):
    pass


class Codegen:
    def __init__(self, filename: str = '<unknown>', module_headers: dict = None):
        self.filename = filename
        self.indent = 0
        self.lines: List[str] = []
        self.includes: List[str] = []
        self.forward_decls: List[str] = []
        self.uses: List[str] = []
        self.assets: List[ast.AssetDecl] = []
        self.module_name: str = ''
        self.fn_names: List[str] = []
        self.enum_variants: dict = {}  # case_name → enum_or_variant_type_name
        self.variant_types: set = set()  # names of variant (tagged-union) types
        # struct_name → {field_name: type_node} — populated in gen_program pass 1
        self.struct_fields: dict = {}
        # Ordered list of (typedef_name, inner_c_type) for fat slices — deduped
        self._slice_typedefs: List[tuple] = []
        self._slice_typedef_names: set = set()
        # Map of user module path → generated header filename (for cross-module includes)
        self.module_headers: dict = module_headers or {}
        # Scope stack: {name: type_node}
        self.scopes: List[dict] = [{}]
        # Defer stack: each entry is a list of DeferStmt nodes for the current block
        # Outer list = stack of scopes; inner list = defers in that scope (LIFO)
        self._defer_stack: List[List[ast.DeferStmt]] = [[]]

    # ── Scope helpers ─────────────────────────────────────────────────────────

    def scope_push(self):
        self.scopes.append({})
        self._defer_stack.append([])

    def scope_pop(self):
        self.scopes.pop()
        self._defer_stack.pop()

    def _defer_push(self, stmt: ast.DeferStmt):
        """Register a defer in the current scope."""
        self._defer_stack[-1].append(stmt)

    def _emit_defers_for_scope(self, scope_idx: int, pad: str, indent: int) -> List[str]:
        """Emit all defers for a given scope level in LIFO order."""
        lines = []
        for d in reversed(self._defer_stack[scope_idx]):
            if isinstance(d.body, ast.Block):
                for stmt in d.body.stmts:
                    s = self.gen_stmt(stmt, indent)
                    if s:
                        lines.append(s)
        return lines

    def _emit_all_defers(self, pad: str, indent: int) -> List[str]:
        """Emit ALL active defers (all scopes, innermost first). Used before return."""
        lines = []
        for scope_idx in range(len(self._defer_stack) - 1, -1, -1):
            lines.extend(self._emit_defers_for_scope(scope_idx, pad, indent))
        return lines

    def scope_set(self, name: str, typ):
        self.scopes[-1][name] = typ

    def scope_get(self, name: str):
        for s in reversed(self.scopes):
            if name in s:
                return s[name]
        return None

    def is_pointer(self, name: str) -> bool:
        t = self.scope_get(name)
        return isinstance(t, ast.TypePointer)

    def _expr_type(self, e):
        """Best-effort: return the type node for an expression."""
        if isinstance(e, ast.Ident):
            return self.scope_get(e.name)
        if isinstance(e, ast.DotAccess) and isinstance(e.obj, ast.Ident):
            obj_type = self.scope_get(e.obj.name)
            # Unwrap pointer to get the struct name
            struct_name = None
            if isinstance(obj_type, ast.TypeName):
                struct_name = obj_type.name
            elif isinstance(obj_type, ast.TypePointer) and isinstance(obj_type.inner, ast.TypeName):
                struct_name = obj_type.inner.name
            if struct_name and struct_name in self.struct_fields:
                return self.struct_fields[struct_name].get(e.field)
        return None

    def _match_type_name(self, expr) -> str:
        """Return the base type name of a match expression (for variant/enum detection)."""
        t = self._expr_type(expr)
        if isinstance(t, ast.TypeName):
            return t.name
        if isinstance(t, ast.TypePointer) and isinstance(t.inner, ast.TypeName):
            return t.inner.name
        return ''

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

    def _slice_typedef(self, inner_type) -> str:
        """Return the C typedef name for a fat slice of inner_type.
        Registers the typedef for emission before the code body.
        """
        c_inner = self.gen_type(inner_type)
        # Sanitize inner type name for use in a C identifier
        safe = (c_inner.replace(' ', '_').replace('*', 'p')
                       .replace(',', '').replace('(', '').replace(')', ''))
        typedef_name = f'PakSlice_{safe}'
        if typedef_name not in self._slice_typedef_names:
            self._slice_typedef_names.add(typedef_name)
            self._slice_typedefs.append((typedef_name, c_inner))
        return typedef_name

    def gen_type(self, t) -> str:
        if t is None:
            return 'void'
        if isinstance(t, ast.TypeName):
            return PRIMITIVE_TYPES.get(t.name, t.name)
        if isinstance(t, ast.TypePointer):
            inner = self.gen_type(t.inner)
            return f'{inner} *'
        if isinstance(t, ast.TypeSlice):
            # Fat slice: struct { T *data; int32_t len; }
            return self._slice_typedef(t.inner)
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
            obj_str = self.gen_expr(e.obj)
            obj_type = self._expr_type(e.obj)
            idx_str = self.gen_expr(e.index)
            if isinstance(obj_type, ast.TypeSlice):
                return f'({obj_str}).data[{idx_str}]'
            return f'{obj_str}[{idx_str}]'
        if isinstance(e, ast.SliceExpr):
            obj_str = self.gen_expr(e.obj)
            start = self.gen_expr(e.start) if e.start else '0'
            obj_type = self._expr_type(e.obj)
            if e.end:
                end_str = self.gen_expr(e.end)
                length = f'({end_str}) - ({start})'
            elif isinstance(obj_type, ast.TypeArray) and isinstance(obj_type.size, ast.IntLit):
                # arr[start..] — use full array size minus start
                length = f'(int)(sizeof({obj_str})/sizeof(({obj_str})[0])) - ({start})'
            else:
                length = f'/* slice length unknown */ 0'
            # Determine inner type for the PakSlice typedef
            if isinstance(obj_type, ast.TypeArray):
                inner_type = obj_type.inner
            elif isinstance(obj_type, ast.TypeSlice):
                inner_type = obj_type.inner
            else:
                inner_type = ast.TypeName(name='auto')
            typedef_name = self._slice_typedef(inner_type)
            return f'({typedef_name}){{ .data = &({obj_str})[{start}], .len = {length} }}'
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
            # Fixed-point arithmetic: detect operand types from scope
            ltype = self._expr_type(e.left)
            rtype = self._expr_type(e.right)
            shift = _fixpoint_shift(ltype) or _fixpoint_shift(rtype)
            if shift and e.op == '*':
                # fix * fix → (int32_t)(((int64_t)(a) * (b)) >> shift)
                return f'(int32_t)(((int64_t)({left}) * ({right})) >> {shift})'
            if shift and e.op == '/':
                # fix / fix → (int32_t)(((int64_t)(a) << shift) / (b))
                return f'(int32_t)(((int64_t)({left}) << {shift}) / ({right}))'
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
            # CatchExpr is a statement-level expression that requires a pre-statement.
            # We emit the inner expression inline; the handler is emitted as a separate
            # statement by gen_let_stmt when it detects a CatchExpr value.
            # For standalone use (not in a let binding), just evaluate the inner expr.
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
            elif isinstance(decl, ast.StructDecl):
                self.struct_fields[decl.name] = {f.name: f.type for f in decl.fields}
            elif isinstance(decl, ast.EnumDecl):
                for v in decl.variants:
                    self.enum_variants[v.name] = decl.name
            elif isinstance(decl, ast.VariantDecl):
                self.variant_types.add(decl.name)
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
            elif not inc and use_path in self.module_headers:
                # User-defined module — include its generated header
                header_line = f'#include "{self.module_headers[use_path]}"'
                if header_line not in seen_includes:
                    out_lines.append(header_line)
                    seen_includes.add(header_line)

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

        # Generate declarations — this populates _slice_typedefs as a side effect
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

        # Fat-slice typedefs (emitted after includes so inner types are visible,
        # and after body generation so all slices have been encountered)
        if self._slice_typedefs:
            out_lines.append('')
            for typedef_name, c_inner in self._slice_typedefs:
                out_lines.append(f'typedef struct {{ {c_inner} *data; int32_t len; }} {typedef_name};')

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
        # Emit defers at natural function exit (LIFO, current scope only)
        for d_line in self._emit_defers_for_scope(-1, '    ', 1):
            lines.append(d_line)
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
        for d_line in self._emit_defers_for_scope(-1, '    ', 1):
            lines.append(d_line)
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
        decl = self.gen_array_decl(s.name, s.type) if s.type else f'__auto_type {s.name}'
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
        decl = self.gen_array_decl(s.name, s.type) if s.type else f'__auto_type {s.name}'
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
            # Emit all active defers before returning (LIFO across scopes)
            defers = self._emit_all_defers(pad, indent)
            val = f' {self.gen_expr(stmt.value)}' if stmt.value is not None else ''
            lines = defers + [f'{pad}return{val};']
            return '\n'.join(lines)
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
            # Register the defer — don't emit it yet
            self._defer_push(stmt)
            return None
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
        self.scope_push()
        for stmt in s.then.stmts:
            lines.append(self.gen_stmt(stmt, indent + 1))
        for d in self._emit_defers_for_scope(-1, pad, indent + 1):
            lines.append(d)
        self.scope_pop()
        lines.append(f'{pad}}}')
        for ec, eb in s.elif_branches:
            lines.append(f'{pad}else if ({self.gen_expr(ec)}) {{')
            self.scope_push()
            for stmt in eb.stmts:
                lines.append(self.gen_stmt(stmt, indent + 1))
            for d in self._emit_defers_for_scope(-1, pad, indent + 1):
                lines.append(d)
            self.scope_pop()
            lines.append(f'{pad}}}')
        if s.else_branch:
            lines.append(f'{pad}else {{')
            self.scope_push()
            for stmt in s.else_branch.stmts:
                lines.append(self.gen_stmt(stmt, indent + 1))
            for d in self._emit_defers_for_scope(-1, pad, indent + 1):
                lines.append(d)
            self.scope_pop()
            lines.append(f'{pad}}}')
        return '\n'.join(l for l in lines if l is not None)

    def gen_null_check(self, s: ast.NullCheckStmt, pad: str, indent: int) -> str:
        expr = self.gen_expr(s.expr)
        inner_pad = '    ' * (indent + 1)
        lines = [f'{pad}if ({expr} != NULL) {{']
        self.scope_push()
        self.scope_set(s.binding, ast.TypePointer(inner=ast.TypeName(name='auto')))
        lines.append(f'{inner_pad}__typeof__({expr}) {s.binding} = {expr};')
        for stmt in s.then.stmts:
            lines.append(self.gen_stmt(stmt, indent + 1))
        for d in self._emit_defers_for_scope(-1, pad, indent + 1):
            lines.append(d)
        self.scope_pop()
        lines.append(f'{pad}}}')
        if s.else_branch:
            lines.append(f'{pad}else {{')
            self.scope_push()
            for stmt in s.else_branch.stmts:
                lines.append(self.gen_stmt(stmt, indent + 1))
            for d in self._emit_defers_for_scope(-1, pad, indent + 1):
                lines.append(d)
            self.scope_pop()
            lines.append(f'{pad}}}')
        return '\n'.join(l for l in lines if l is not None)

    def gen_loop(self, s: ast.LoopStmt, pad: str, indent: int) -> str:
        lines = [f'{pad}while (true) {{']
        self.scope_push()
        for stmt in s.body.stmts:
            lines.append(self.gen_stmt(stmt, indent + 1))
        for d in self._emit_defers_for_scope(-1, pad, indent + 1):
            lines.append(d)
        self.scope_pop()
        lines.append(f'{pad}}}')
        return '\n'.join(l for l in lines if l is not None)

    def gen_while(self, s: ast.WhileStmt, pad: str, indent: int) -> str:
        cond = self.gen_expr(s.condition)
        lines = [f'{pad}while ({cond}) {{']
        self.scope_push()
        for stmt in s.body.stmts:
            lines.append(self.gen_stmt(stmt, indent + 1))
        for d in self._emit_defers_for_scope(-1, pad, indent + 1):
            lines.append(d)
        self.scope_pop()
        lines.append(f'{pad}}}')
        return '\n'.join(l for l in lines if l is not None)

    def gen_for(self, s: ast.ForStmt, pad: str, indent: int) -> str:
        iterable = s.iterable
        inner_pad = '    ' * (indent + 1)
        lines = []

        if isinstance(iterable, ast.RangeExpr):
            # for i in start..end  →  for (int i = start; i < end; i++)
            start = self.gen_expr(iterable.start)
            end = self.gen_expr(iterable.end) if iterable.end else '0'
            if s.index:
                lines.append(f'{pad}for (int {s.index} = {start}; {s.index} < {end}; {s.index}++) {{')
                lines.append(f'{inner_pad}int {s.binding} = {s.index};')
            else:
                lines.append(f'{pad}for (int {s.binding} = {start}; {s.binding} < {end}; {s.binding}++) {{')
        else:
            coll = self.gen_expr(iterable)
            coll_type = self._expr_type(iterable)
            self.scope_set(s.binding, ast.TypeName(name='auto'))

            if isinstance(coll_type, ast.TypeSlice):
                # Fat slice: iterate via .data and .len
                idx = s.index if s.index else f'_i_{s.binding}'
                lines.append(f'{pad}for (int {idx} = 0; {idx} < ({coll}).len; {idx}++) {{')
                lines.append(f'{inner_pad}__typeof__(({coll}).data[0]) {s.binding} = ({coll}).data[{idx}];')
            else:
                # Fixed-size C array ([N]T): iterate using sizeof/sizeof
                idx = s.index if s.index else f'_i_{s.binding}'
                lines.append(f'{pad}for (int {idx} = 0; {idx} < (int)(sizeof({coll})/sizeof(({coll})[0])); {idx}++) {{')
                lines.append(f'{inner_pad}__typeof__(({coll})[0]) {s.binding} = ({coll})[{idx}];')

        self.scope_push()
        for stmt in s.body.stmts:
            lines.append(self.gen_stmt(stmt, indent + 1))
        # Emit defers before closing the loop body
        for d_line in self._emit_defers_for_scope(-1, inner_pad, indent + 1):
            lines.append(d_line)
        self.scope_pop()
        lines.append(f'{pad}}}')
        return '\n'.join(l for l in lines if l is not None)

    def gen_match(self, s: ast.MatchStmt, pad: str, indent: int) -> str:
        expr = self.gen_expr(s.expr)
        inner_pad = '    ' * (indent + 1)
        inner2_pad = '    ' * (indent + 2)

        # Determine if the matched expression is a variant (tagged union).
        # Variants need switch(expr.tag); enums switch(expr) directly.
        match_type = self._match_type_name(s.expr)
        is_variant = match_type in self.variant_types
        switch_expr = f'{expr}.tag' if is_variant else expr
        lines = [f'{pad}switch ({switch_expr}) {{']

        for arm in s.arms:
            pat = arm.pattern
            if isinstance(pat, ast.Ident) and pat.name == '_':
                lines.append(f'{inner_pad}default:')
            elif isinstance(pat, ast.EnumVariantAccess):
                type_name = self.enum_variants.get(pat.name, '')
                if type_name in self.variant_types:
                    # Tagged union: case uses _tag_ infix
                    lines.append(f'{inner_pad}case {type_name}_tag_{pat.name}:')
                elif type_name:
                    lines.append(f'{inner_pad}case {type_name}_{pat.name}:')
                else:
                    lines.append(f'{inner_pad}case {pat.name}:')
            elif isinstance(pat, ast.DotAccess):
                # EnumName.variant or VariantName.Case explicit form
                variant = pat.field
                obj_name = self.gen_expr(pat.obj)
                if obj_name in self.variant_types:
                    lines.append(f'{inner_pad}case {obj_name}_tag_{variant}:')
                else:
                    lines.append(f'{inner_pad}case {obj_name}_{variant}:')
            elif isinstance(pat, ast.IntLit):
                lines.append(f'{inner_pad}case {pat.value}:')
            elif isinstance(pat, ast.BoolLit):
                lines.append(f'{inner_pad}case {"1" if pat.value else "0"}:')
            else:
                lines.append(f'{inner_pad}case /* {self.gen_expr(pat)} */:')

            # Wrap body in {} so variable declarations are always valid in C
            lines.append(f'{inner_pad}{{')
            self.scope_push()
            # Emit variant binding if pattern has one: Type.Case(binding)
            if isinstance(pat, ast.DotAccess) and hasattr(pat, '_binding') and pat._binding:
                obj_name = self.gen_expr(pat.obj)
                if obj_name in self.variant_types:
                    field_name = pat.field.lower()
                    lines.append(f'{inner2_pad}__auto_type {pat._binding} = {expr}.data.{field_name};')
                    self.scope_set(pat._binding, ast.TypeName(name='auto'))
            if isinstance(arm.body, ast.Block):
                for stmt in arm.body.stmts:
                    lines.append(self.gen_stmt(stmt, indent + 2))
            else:
                lines.append(f'{inner2_pad}{self.gen_expr(arm.body)};')
            for d_line in self._emit_defers_for_scope(-1, inner2_pad, indent + 2):
                lines.append(d_line)
            self.scope_pop()
            lines.append(f'{inner2_pad}break;')
            lines.append(f'{inner_pad}}}')

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


def generate(program: ast.Program, filename: str = '<unknown>', module_headers: dict = None) -> str:
    cg = Codegen(filename, module_headers=module_headers)
    return cg.gen_program(program)
